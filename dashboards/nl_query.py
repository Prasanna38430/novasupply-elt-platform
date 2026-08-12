"""Natural-language-to-SQL for the dashboard's "Ask your data" panel.

Sends the question plus the mart schema to a local Ollama model and returns the SQL it
drafts. The schema is passed in full on every call rather than retrieved from a vector
store: the mart layer is seven tables, the whole thing fits in the prompt, and Ollama
caches the fixed prefix so re-sending it costs almost nothing. See
docs/adr/0007-local-llm-for-nl-to-sql.md.

Three things do the heavy lifting for accuracy on a small model:

  * the schema is real DDL, which the model has seen millions of in training, rather than
    a compact notation invented here that it has seen none of;
  * a glossary maps the business words people actually type ("stockout", "late") onto the
    columns that hold them, and pins the two grain traps in this warehouse;
  * worked examples, because a 3B model pattern-matches far more than it reasons.

When the warehouse rejects the generated SQL, the error is fed back for one repair
attempt. That recovers most of what this size of model gets wrong, which is overwhelmingly
alias and column slips rather than misunderstood questions.

Nothing leaves the machine: Ollama is a local HTTP server, not a cloud API.
"""
from __future__ import annotations

import json
import re
from typing import Callable

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

# A code-tuned 3B model rather than a general 8B chat model: better at drafting SQL for its
# size, and it fits in memory on an 8GB dev machine, which llama3.1:8b does not (ADR 0007).
MODEL = "qwen2.5-coder:3b"

# Keep the model resident between questions. The default 5 minutes expires mid-demo and
# costs a ~9 second reload on the next question; generation is slow enough already.
KEEP_ALIVE = "30m"

# Generation runs at single-digit tokens/sec on CPU, so a runaway answer is a hang. No
# reasonable query against seven tables needs more than this.
MAX_OUTPUT_TOKENS = 400

# The panel renders results in a dataframe, not a report; capping keeps a careless
# "show me everything" from pulling half a million sales rows into the browser.
MAX_ROWS = 500

REQUEST_TIMEOUT = 300

# Real DDL, generated from information_schema against the built warehouse rather than
# written from memory, so it cannot drift into describing columns that do not exist.
# {marts} is the placeholder dashboards/app.py's query() swaps per warehouse, so the SQL
# that comes back runs unchanged against either DuckDB or Snowflake.
SCHEMA_DDL = """
CREATE TABLE {marts}.dim_suppliers (
    supplier_id VARCHAR PRIMARY KEY,
    supplier_name VARCHAR,
    country VARCHAR,
    city VARCHAR,
    nominal_lead_time_days INTEGER,
    reliability_score DOUBLE,          -- 0..1
    reliability_tier VARCHAR,          -- 'High' | 'Medium' | 'Low'
    valid_from DATE
);

CREATE TABLE {marts}.dim_products (
    product_id VARCHAR PRIMARY KEY,
    product_name VARCHAR,
    category VARCHAR,
    supplier_id VARCHAR REFERENCES dim_suppliers(supplier_id),
    unit_cost_eur DOUBLE,
    unit_price_eur DOUBLE,
    unit_margin_eur DOUBLE,
    margin_pct DOUBLE                  -- 0..1
);

CREATE TABLE {marts}.dim_stores (
    store_id VARCHAR PRIMARY KEY,
    store_name VARCHAR,
    city VARCHAR,
    region VARCHAR
);

CREATE TABLE {marts}.dim_date (
    date_day DATE PRIMARY KEY,
    year BIGINT,
    month BIGINT,
    day_of_month BIGINT,
    iso_day_of_week BIGINT,            -- 1 = Monday .. 7 = Sunday
    iso_week BIGINT,
    weekday_name VARCHAR,
    is_weekend BOOLEAN
);

CREATE TABLE {marts}.fct_sales (          -- one row per sale line
    sale_id VARCHAR PRIMARY KEY,
    sale_date DATE REFERENCES dim_date(date_day),
    store_id VARCHAR REFERENCES dim_stores(store_id),
    product_id VARCHAR REFERENCES dim_products(product_id),
    quantity INTEGER,
    unit_price_eur DOUBLE,
    discount_pct DOUBLE,
    amount_eur DOUBLE                  -- revenue; sum this for turnover
);

CREATE TABLE {marts}.fct_inventory (      -- DAILY SNAPSHOT: one row per day/store/product
    snapshot_date DATE REFERENCES dim_date(date_day),
    store_id VARCHAR REFERENCES dim_stores(store_id),
    product_id VARCHAR REFERENCES dim_products(product_id),
    on_hand_qty INTEGER,
    reorder_point INTEGER,
    in_transit_qty INTEGER,            -- >0 means replenishment already on the way
    avg_daily_units DOUBLE,
    is_stockout BOOLEAN,               -- true when on_hand_qty = 0
    below_reorder_point BOOLEAN,
    days_of_cover DOUBLE               -- null when there is no recent demand
);

CREATE TABLE {marts}.fct_purchase_orders ( -- one row per replenishment order
    po_id VARCHAR PRIMARY KEY,
    order_date DATE,
    supplier_id VARCHAR REFERENCES dim_suppliers(supplier_id),
    product_id VARCHAR REFERENCES dim_products(product_id),
    store_id VARCHAR REFERENCES dim_stores(store_id),
    ordered_qty INTEGER,
    received_qty INTEGER,
    promised_date DATE,
    actual_delivery_date DATE,
    promised_lead_time_days BIGINT,
    actual_lead_time_days BIGINT,
    delay_days BIGINT,                 -- days past promised_date; null while open
    is_open BOOLEAN,                   -- true while not yet delivered
    is_late BOOLEAN                    -- delivered after promised_date
);
""".strip()

# The words people type are not the words in the schema, and the two grain traps below
# are the difference between a plausible number and a correct one.
GLOSSARY = """
- "stockout" / "out of stock" -> fct_inventory.is_stockout = true
- "at risk" / "about to run out" -> fct_inventory.days_of_cover below some threshold
  AND in_transit_qty = 0 (stock already on the way is not at risk)
- "late" / "delayed" supplier or delivery -> fct_purchase_orders.is_late = true
- "revenue" / "turnover" / "sales" in money -> sum(fct_sales.amount_eur)
- "units sold" -> sum(fct_sales.quantity)
- "reliable supplier" -> dim_suppliers.reliability_tier or reliability_score

The data is a French retailer, so the values in these columns are French. Match them
exactly, do not translate:
- dim_products.category: 'Boissons', 'Frais', 'Hygiene', 'Surgeles', 'Epicerie'
  (the last three carry accents in the data: Hygiene -> Hygiène, Surgeles -> Surgelés,
  Epicerie -> Épicerie)
- dim_stores.region: 'Auvergne-Rhône-Alpes', 'Grand Est', 'Hauts-de-France',
  'Nouvelle-Aquitaine', 'Occitanie', 'Pays de la Loire',
  "Provence-Alpes-Côte d'Azur", 'Île-de-France'

GRAIN TRAPS, get these wrong and the number is meaningless:
1. fct_inventory holds a snapshot for EVERY day. For any "right now" / "currently" /
   "today" question, filter to the newest snapshot:
       where snapshot_date = (select max(snapshot_date) from {marts}.fct_inventory)
   Without that filter you are counting the same SKU up to 90 times.
2. fct_purchase_orders holds open orders too, and is_late/delay_days are null for those.
   For delivery-performance questions filter to is_open = false.
""".strip()

# Worked examples, chosen to teach the mistakes this model actually makes: losing track of
# which alias belongs to which table, and ignoring both grain traps above.
FEW_SHOT = """
Question: Total revenue by store, highest first
SQL:
select st.store_name, sum(s.amount_eur) as revenue_eur
from {marts}.fct_sales s
join {marts}.dim_stores st on s.store_id = st.store_id
group by st.store_name
order by revenue_eur desc

Question: Which category has the most stockouts right now?
SQL:
select p.category, count(*) as stockouts
from {marts}.fct_inventory i
join {marts}.dim_products p on i.product_id = p.product_id
where i.snapshot_date = (select max(snapshot_date) from {marts}.fct_inventory)
  and i.is_stockout
group by p.category
order by stockouts desc

Question: Which suppliers deliver late most often?
SQL:
select sup.supplier_name,
       count(*) as delivered_orders,
       round(100.0 * avg(case when po.is_late then 1.0 else 0 end), 1) as late_pct
from {marts}.fct_purchase_orders po
join {marts}.dim_suppliers sup on po.supplier_id = sup.supplier_id
where po.is_open = false
group by sup.supplier_name
having count(*) > 20
order by late_pct desc
""".strip()

PROMPT_TEMPLATE = """You are a SQL analyst. Write ONE read-only SQL query answering the \
question, against the schema below. Reply with the SQL and nothing else: no explanation, \
no markdown fences, no trailing semicolon.

Schema:
{schema}

Notes on the data:
{glossary}

Examples:
{few_shot}

Rules:
- SELECT queries only. Never write, alter or drop anything.
- Prefix every table with the literal `{{marts}}.` exactly as in the schema and examples.
- Give every table a short alias and use that same alias on every one of its columns. \
Never reference an alias you did not define.
- Only use columns that appear in the schema above.
- Standard SQL that runs on both DuckDB and Snowflake.

Question: {question}
SQL:"""

REPAIR_TEMPLATE = """The SQL below was written for this question but the database \
rejected it. Fix it and reply with ONLY the corrected SQL: no explanation, no markdown \
fences, no trailing semicolon.

Schema:
{schema}

Notes on the data:
{glossary}

Question: {question}

SQL that failed:
{failed_sql}

Database error:
{error}

Look closely at whether every alias is defined before it is used and whether every column \
exists on the table it is read from.
Corrected SQL:"""

_FENCE_RE = re.compile(r"^```sql\s*|^```\s*|```$", re.IGNORECASE | re.MULTILINE)
_UNSAFE_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|merge|copy|call|"
    r"attach|detach|install|load|export|pragma|set|use)\b",
    re.IGNORECASE,
)
_SELECT_RE = re.compile(r"(?i)^(select|with)\b")
_TRAILING_LIMIT_RE = re.compile(r"(?is)\blimit\s+\d+\s*$")


class OllamaUnavailable(RuntimeError):
    """The local Ollama server isn't reachable."""


class ModelError(RuntimeError):
    """Ollama reached, but it failed to produce a completion."""


class UnsafeGeneratedSQL(ValueError):
    """The model drafted something other than a read-only SELECT."""


def is_safe_select(sql: str) -> bool:
    """Read-only gate.

    Deliberately a denylist over a parser: the model is told to emit one SELECT, so
    anything carrying a write keyword is already off-script and worth rejecting outright
    rather than reasoning about. Statement separators are rejected too, so a second
    statement cannot ride along behind a legitimate-looking first one.
    """
    stripped = sql.strip().lstrip("(")
    if not _SELECT_RE.match(stripped):
        return False
    if _UNSAFE_RE.search(sql):
        return False
    # A semicolon anywhere but the very end means more than one statement.
    return ";" not in sql.strip().rstrip(";")


def cap_rows(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Add a LIMIT when the query has none, so a broad question can't flood the browser.

    Appending rather than wrapping in a subquery keeps ORDER BY doing what it says; a
    query that already limits itself is left alone.
    """
    return sql if _TRAILING_LIMIT_RE.search(sql.strip()) else f"{sql}\nlimit {max_rows}"


def _clean(raw: str) -> str:
    return _FENCE_RE.sub("", raw).strip().rstrip(";").strip()


def _complete(prompt: str, on_token: Callable[[str], None] | None = None) -> str:
    """Stream one completion from Ollama.

    Streamed rather than awaited in one lump purely for how it feels: generation runs at
    single-digit tokens per second on CPU, so a blocking call is fifteen seconds of blank
    screen, while streaming shows the query taking shape immediately. `on_token` receives
    the text accumulated so far, which is what a Streamlit placeholder wants to render.
    """
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": MAX_OUTPUT_TOKENS},
    }
    parts: list[str] = []
    try:
        with requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ModelError(chunk["error"])
                token = chunk.get("response", "")
                if token:
                    parts.append(token)
                    if on_token is not None:
                        on_token(_clean("".join(parts)))
                if chunk.get("done"):
                    break
    except requests.exceptions.ConnectionError as exc:
        raise OllamaUnavailable(
            f"Can't reach Ollama at {OLLAMA_URL}. Install it from ollama.com, run "
            f"`ollama pull {MODEL}` once, and make sure Ollama is running, then retry."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise ModelError(
            f"Ollama did not answer within {REQUEST_TIMEOUT}s. On a CPU-only machine the "
            f"first question after a pause also pays for loading the model."
        ) from exc
    return _clean("".join(parts))


def _drafted(sql: str) -> str:
    if not is_safe_select(sql):
        raise UnsafeGeneratedSQL(
            f"Refusing to run this, it is not a plain read-only SELECT:\n\n{sql}"
        )
    return sql


def generate_sql(question: str, on_token: Callable[[str], None] | None = None) -> str:
    """Draft SQL for a question. Raises UnsafeGeneratedSQL if it isn't a read-only SELECT."""
    prompt = PROMPT_TEMPLATE.format(
        schema=SCHEMA_DDL, glossary=GLOSSARY, few_shot=FEW_SHOT, question=question
    )
    return _drafted(_complete(prompt, on_token))


def repair_sql(
    question: str,
    failed_sql: str,
    error: str,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """Show the model its own failed SQL and the database's complaint, and let it retry."""
    prompt = REPAIR_TEMPLATE.format(
        schema=SCHEMA_DDL,
        glossary=GLOSSARY,
        question=question,
        failed_sql=failed_sql,
        error=error,
    )
    return _drafted(_complete(prompt, on_token))


def answer(
    question: str,
    runner: Callable[[str], object],
    on_token: Callable[[str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
):
    """Draft SQL, run it, and on a database error repair it once and run that.

    `runner` executes SQL and returns rows; injecting it keeps this module independent of
    which warehouse the dashboard happens to be pointed at, and makes the repair path
    testable without a database. Returns (sql, rows, repaired).
    """
    def status(message: str) -> None:
        if on_status is not None:
            on_status(message)

    status("Drafting SQL...")
    sql = cap_rows(generate_sql(question, on_token))
    try:
        status("Running the query...")
        return sql, runner(sql), False
    except Exception as first_error:  # noqa: BLE001 - any warehouse error is repairable input
        status("The warehouse rejected that. Showing the model its error and retrying...")
        repaired = cap_rows(repair_sql(question, sql, str(first_error), on_token))
        try:
            status("Running the corrected query...")
            return repaired, runner(repaired), True
        except Exception as second_error:  # noqa: BLE001 - surfaced to the user as-is
            raise RuntimeError(
                f"Both attempts failed.\n\nFirst error: {first_error}\n\n"
                f"After repair: {second_error}"
            ) from second_error
