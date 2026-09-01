"""NovaSupply operations dashboard.

Answers the question the platform exists for: which SKUs are about to stock out, and which
supplier delays are behind it.

Reads the marts from either warehouse. DuckDB is the default because it needs no
credentials; set NOVASUPPLY_WAREHOUSE=snowflake in .env, or pick Snowflake in the sidebar,
to point it at the cloud instead. The queries are identical either way -- the marts have
the same shape in both, which is the whole argument for the layered dbt build.

    streamlit run dashboards/app.py
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import contract_qa
import nl_query

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)

st.set_page_config(page_title="NovaSupply", page_icon="📦", layout="wide")


# Connections

@st.cache_resource(show_spinner=False)
def duckdb_connection():
    import duckdb

    path = REPO_ROOT / os.getenv("DUCKDB_PATH", "data/novasupply.duckdb")
    if not path.exists():
        raise FileNotFoundError(f"no warehouse at {path} - run the pipeline first")
    # read_only lets the dashboard stay open while dbt rebuilds.
    return duckdb.connect(str(path), read_only=True)


@st.cache_resource(show_spinner=False)
def snowflake_connection():
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role="NOVASUPPLY_TRANSFORMER",
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        login_timeout=60,
    )


def _decimals_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """Snowflake returns NUMBER as Python Decimal, which pandas keeps as object dtype.

    Charts then misread the values -- 0.56 renders as 56 -- so anything that really is a
    Decimal becomes a float. Checking the value's type rather than trying to parse the
    column leaves genuine strings alone.
    """
    for column in df.columns:
        values = df[column]
        if values.dtype == "object":
            non_null = values.dropna()
            if len(non_null) and isinstance(non_null.iloc[0], Decimal):
                df[column] = values.astype(float)
    return df


@st.cache_data(ttl=300, show_spinner="Querying the warehouse...")
def query(sql: str, warehouse: str) -> pd.DataFrame:
    if warehouse == "snowflake":
        cur = snowflake_connection().cursor()
        cur.execute(sql.replace("{marts}", "NOVASUPPLY.MARTS"))
        df = cur.fetch_pandas_all()
        df.columns = [c.lower() for c in df.columns]
        return _decimals_to_float(df)
    return duckdb_connection().sql(sql.replace("{marts}", "marts")).fetchdf()


# Sidebar

st.sidebar.title("NovaSupply")
st.sidebar.caption("Retail supply-chain analytics")

default_warehouse = os.getenv("NOVASUPPLY_WAREHOUSE", "duckdb")
warehouse = st.sidebar.radio(
    "Warehouse",
    ["duckdb", "snowflake"],
    index=0 if default_warehouse == "duckdb" else 1,
    format_func=lambda v: "DuckDB (local)" if v == "duckdb" else "Snowflake (cloud)",
)

try:
    probe = query("select max(snapshot_date) as d from {marts}.fct_inventory", warehouse)
    as_of = pd.to_datetime(probe["d"].iloc[0]).date()
except Exception as exc:  # noqa: BLE001 - surface the real reason to the user
    st.error(f"Could not reach the {warehouse} warehouse.\n\n{exc}")
    st.stop()

st.sidebar.metric("Data as of", str(as_of))
cover_threshold = st.sidebar.slider("Stockout risk threshold (days of cover)", 1, 21, 7)

stores = query("select store_id, store_name from {marts}.dim_stores order by store_id", warehouse)
store_choice = st.sidebar.multiselect(
    "Stores", stores["store_id"].tolist(), default=stores["store_id"].tolist(),
    format_func=lambda sid: stores.set_index("store_id").loc[sid, "store_name"],
)
store_filter = "'" + "','".join(store_choice) + "'" if store_choice else "''"


# Headline numbers

st.title("Operations overview")

kpis = query(f"""
    with latest as (
        select * from {{marts}}.fct_inventory
        where snapshot_date = (select max(snapshot_date) from {{marts}}.fct_inventory)
          and store_id in ({store_filter})
    )
    select
        (select count(*) from latest where is_stockout)                          as stockouts,
        (select count(*) from latest
          where days_of_cover is not null
            and days_of_cover < {cover_threshold}
            and in_transit_qty = 0)                                              as at_risk,
        (select count(*) from {{marts}}.fct_purchase_orders where is_open)        as open_orders,
        (select round(sum(amount_eur), 0) from {{marts}}.fct_sales
          where store_id in ({store_filter}))                                    as revenue
""", warehouse)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Out of stock today", int(kpis["stockouts"].iloc[0]))
c2.metric(f"At risk (<{cover_threshold}d cover)", int(kpis["at_risk"].iloc[0]))
c3.metric("Orders in transit", int(kpis["open_orders"].iloc[0]))
c4.metric("Revenue (90 days)", f"EUR {kpis['revenue'].iloc[0]:,.0f}")

st.divider()


# The question the platform exists to answer

st.subheader("SKUs at risk of stocking out")
st.caption(
    "Latest stock position, projected against recent demand. Items already being "
    "replenished are excluded, those are handled; these are not."
)

at_risk = query(f"""
    with latest as (
        select * from {{marts}}.fct_inventory
        where snapshot_date = (select max(snapshot_date) from {{marts}}.fct_inventory)
          and store_id in ({store_filter})
    )
    select
        s.store_name,
        p.product_name,
        p.category,
        l.on_hand_qty,
        round(l.avg_daily_units, 2) as daily_demand,
        l.days_of_cover,
        sup.supplier_name,
        sup.reliability_tier
    from latest l
    join {{marts}}.dim_products  p   on l.product_id = p.product_id
    join {{marts}}.dim_stores    s   on l.store_id   = s.store_id
    join {{marts}}.dim_suppliers sup on p.supplier_id = sup.supplier_id
    where l.days_of_cover is not null
      and l.days_of_cover < {cover_threshold}
      and l.in_transit_qty = 0
    order by l.days_of_cover
    limit 40
""", warehouse)

if at_risk.empty:
    st.success(f"Nothing below {cover_threshold} days of cover without a replenishment already on the way.")
else:
    st.dataframe(at_risk, width='stretch', hide_index=True)

st.divider()


# Supplier performance

left, right = st.columns(2)

with left:
    st.subheader("Supplier lateness")
    st.caption("Share of delivered orders that arrived after the promised date.")
    late = query("""
        select
            sup.supplier_name,
            count(*)                                                       as orders,
            round(100.0 * avg(case when po.is_late then 1.0 else 0 end), 1) as late_pct,
            round(avg(case when po.is_late then po.delay_days end), 1)      as avg_days_late
        from {marts}.fct_purchase_orders po
        join {marts}.dim_suppliers sup on po.supplier_id = sup.supplier_id
        where po.is_open = false
        group by sup.supplier_name
        having count(*) > 20
        order by late_pct desc
        limit 10
    """, warehouse)
    st.dataframe(late, width='stretch', hide_index=True)

with right:
    st.subheader("Does supplier reliability show up in stockouts?")
    st.caption("Stockout rate of each supplier's SKUs, grouped by their reliability tier.")
    tiers = query("""
        select
            sup.reliability_tier,
            round(100.0 * sum(case when i.is_stockout then 1.0 else 0 end) / count(*), 2) as stockout_rate_pct
        from {marts}.fct_inventory i
        join {marts}.dim_products  p   on i.product_id  = p.product_id
        join {marts}.dim_suppliers sup on p.supplier_id = sup.supplier_id
        group by sup.reliability_tier
    """, warehouse)
    order = {"High": 0, "Medium": 1, "Low": 2}
    tiers = tiers.sort_values("reliability_tier", key=lambda s: s.map(order))
    st.bar_chart(tiers.set_index("reliability_tier")["stockout_rate_pct"], height=280)

st.divider()


# Sales trend

st.subheader("Revenue by day")
sales = query(f"""
    select f.sale_date, round(sum(f.amount_eur), 2) as revenue_eur
    from {{marts}}.fct_sales f
    where f.store_id in ({store_filter})
    group by f.sale_date
    order by f.sale_date
""", warehouse)
st.line_chart(sales.set_index("sale_date")["revenue_eur"], height=260)

st.divider()


# Data quality

st.subheader("Data quality")
st.caption(
    "Rows failing validation are diverted to quarantine rather than failing the pipeline, "
    "so a malformed row degrades the numbers slightly instead of stopping the nightly run."
)

try:
    quarantine_schema = "NOVASUPPLY.QUARANTINE" if warehouse == "snowflake" else "quarantine"
    q = query(f"select count(*) as n from {quarantine_schema}.quarantine_sales", warehouse)
    quarantined = int(q["n"].iloc[0])
except Exception:  # noqa: BLE001 - quarantine table may not exist on a fresh build
    quarantined = None

try:
    # Counted from Elementary's own record of the last build rather than typed in here.
    # The hardcoded figure this replaces went stale twice in a single afternoon, once for
    # every batch of models added, and a dashboard advertising the wrong number of tests is
    # worse than one advertising none.
    elementary_schema = "NOVASUPPLY.ELEMENTARY" if warehouse == "snowflake" else "elementary"
    t = query(f"select count(*) as n from {elementary_schema}.dbt_tests", warehouse)
    test_count = int(t["n"].iloc[0])
except Exception:  # noqa: BLE001 - Elementary is excluded from fast local builds
    test_count = None

d1, d2 = st.columns(2)
d1.metric("Quarantined sale rows", quarantined if quarantined is not None else "n/a")
d2.metric("dbt tests in the build", test_count if test_count is not None else "n/a")

if quarantined == 0:
    st.success("No rows quarantined in the latest load.")
elif quarantined:
    st.warning(f"{quarantined} row(s) quarantined, inspect `quarantine_sales` for the reason.")

st.divider()


# Ask your data (AI)

st.subheader("Ask your data (AI)")
st.caption(
    "Natural-language question -> SQL, drafted locally by Ollama and run against the "
    "warehouse selected above. The generated SQL is always shown, so you can check it "
    "before trusting the answer. Nothing here calls a cloud API."
)

EXAMPLE_QUESTIONS = [
    "Which category has the most stockouts right now?",
    "Total revenue by store, highest first",
    "Which suppliers deliver late most often?",
    "Top 10 products by revenue in Hauts-de-France",
    "Average days of cover by category, lowest first",
]

question = st.text_input(
    "Ask a question about sales, inventory or suppliers",
    placeholder=EXAMPLE_QUESTIONS[0],
)
st.caption("Try: " + "  •  ".join(f"*{q}*" for q in EXAMPLE_QUESTIONS[:3]))

if question:
    sql_box = st.empty()
    try:
        with st.status("Thinking...", expanded=True) as status_box:
            # The model streams into the code block so the query visibly takes shape;
            # on a CPU-only machine the alternative is fifteen silent seconds.
            sql, rows, repaired = nl_query.answer(
                question,
                runner=lambda s: query(s, warehouse),
                on_token=lambda partial: sql_box.code(partial, language="sql"),
                on_status=lambda message: status_box.update(label=message),
            )
            status_box.update(label="Done", state="complete", expanded=False)
        sql_box.code(sql, language="sql")
        if repaired:
            st.caption(
                "The first attempt was rejected by the warehouse; this is the model's "
                "corrected second attempt."
            )
        st.dataframe(rows, width='stretch', hide_index=True)
    except nl_query.OllamaUnavailable as exc:
        st.info(str(exc))
    except Exception as exc:  # noqa: BLE001 - surface the model's mistake, not a stack trace
        st.error(f"That didn't run: {exc}")

st.divider()


# Ask about the contracts

st.subheader("Ask about the contracts")
st.caption(
    "The panel above queries the numbers. This one reads the supplier contracts, which "
    "are prose. The clauses behind every answer are shown underneath it, so the answer "
    "can be checked against the text rather than taken on trust."
)

CONTRACT_QUESTIONS = [
    "Quel préavis faut-il pour résilier le contrat avec Regnier ?",
    "Quelle pénalité s'applique si Guilbert S.A. livre en retard ?",
    "Sous quel délai faut-il payer les factures de Martinez SA ?",
]

if warehouse == "snowflake":
    st.info(
        "The contract index is built locally into DuckDB by ingestion/embed_documents.py, "
        "so this panel runs against DuckDB only. Snowflake has a native VECTOR type and "
        "VECTOR_COSINE_SIMILARITY, so the same design ports; it just is not built yet."
    )
else:
    contract_question = st.text_input(
        "Ask a question about the supplier contracts",
        placeholder=CONTRACT_QUESTIONS[0],
    )
    st.caption("Try: " + "  •  ".join(f"*{q}*" for q in CONTRACT_QUESTIONS[:2]))

    if contract_question:
        answer_box = st.empty()
        try:
            suppliers_for_lookup = query(
                "select supplier_id, supplier_name from {marts}.dim_suppliers", warehouse
            )
            with st.status("Searching the contracts...", expanded=True) as contract_status:
                text, clauses, supplier_id = contract_qa.answer(
                    duckdb_connection(),
                    contract_question,
                    suppliers_for_lookup,
                    on_token=lambda partial: answer_box.markdown(partial),
                )
                contract_status.update(label="Done", state="complete", expanded=False)
            answer_box.markdown(text)

            if supplier_id:
                st.caption(
                    f"Recognised {supplier_id} in the question and searched only their "
                    "documents. Superseded clauses are excluded."
                )
            for clause in clauses.itertuples():
                label = (
                    f"{clause.document_id} - {clause.article_title}"
                    f"{'  (avenant)' if clause.document_type == 'avenant' else ''}"
                )
                with st.expander(label):
                    st.text(clause.chunk_text)
        except contract_qa.ollama.OllamaUnavailable as exc:
            st.info(str(exc))
        except Exception as exc:  # noqa: BLE001 - show what broke, not a stack trace
            st.error(f"That didn't run: {exc}")
