"""Capture the screenshots the README embeds.

Screenshots go stale quietly. The ones in this repo drifted a month behind the code before
anybody noticed, so regenerating them is a script rather than a memory of which windows to
arrange. Run it after changing anything the README shows.

It drives the Chrome already installed on the machine (`channel="chrome"`), so there is no
browser to download. Playwright is a development tool and is deliberately not in
requirements.txt, which describes what the platform needs to run:

    pip install playwright

    # dashboard panels: needs the app and Ollama running
    streamlit run dashboards/app.py
    python scripts/capture_screenshots.py

    # the DAG: needs the Airflow stack up, with at least one finished run
    docker compose up -d --build
    python scripts/capture_screenshots.py --airflow

    # the lineage graph: needs dbt docs served
    cd dbt && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir . --port 8081
    python scripts/capture_screenshots.py --lineage

Both AI panels are captured after a real answer, and generation is slow on CPU, hence the
unusually patient timeouts.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = REPO_ROOT / "docs" / "images"
APP_URL = "http://localhost:8501"
AIRFLOW_URL = "http://localhost:8080"
DBT_DOCS_URL = "http://localhost:8081"

VIEWPORT = {"width": 1440, "height": 1000}

# A question answered by a 3B model on CPU can take the better part of a minute, and the
# first one after an idle period also pays to load the model.
ANSWER_TIMEOUT_MS = 180_000

# Both answers stream, so anything that appears while they are still arriving is a trap:
# the first version of this script waited on the code block and on an expander, and caught
# both panels mid-spinner with half a query and no results. Each readiness check below can
# only become true once the panel has actually finished.
SHOTS = [
    {
        "name": "ask-your-data.png",
        "placeholder": "Which category has the most stockouts",
        "question": "Which suppliers deliver late most often?",
        "heading": "Ask your data (AI)",
        # A results grid that was not on the page before the question was asked. The SQL
        # itself streams in token by token, so its presence proves nothing.
        "ready": "() => document.querySelectorAll('[data-testid=\"stDataFrame\"]').length > {before}",
        "count": "[data-testid='stDataFrame']",
    },
    {
        "name": "ask-contracts.png",
        "placeholder": "Quel préavis faut-il",
        "question": "Sous combien de jours Regnier doit-il livrer une commande ?",
        "heading": "Ask about the contracts",
        # A document reference can only be on the page once retrieval has returned clauses
        # and the model has cited one.
        "ready": "() => document.body.innerText.includes('CTR-2026')",
        "count": None,
    },
]


def capture(page, shot: dict) -> None:
    before = page.locator(shot["count"]).count() if shot["count"] else 0

    box = page.get_by_placeholder(shot["placeholder"])
    box.scroll_into_view_if_needed()
    box.fill(shot["question"])
    box.press("Enter")

    print(f"  waiting for an answer to: {shot['question']}")
    page.wait_for_function(shot["ready"].format(before=before), timeout=ANSWER_TIMEOUT_MS)
    # The status widget collapses to "Done" a beat after the content lands.
    page.wait_for_timeout(3_000)

    # Put the heading just under the top of the frame, so the answer and the clauses
    # beneath it are what fills the shot.
    page.evaluate(
        """(heading) => {
            const el = [...document.querySelectorAll('h1,h2,h3')]
                .find(h => h.innerText.trim() === heading);
            if (el) { el.scrollIntoView({block: 'start'}); window.scrollBy(0, -24); }
        }""",
        shot["heading"],
    )
    page.wait_for_timeout(1_000)

    out = IMAGES_DIR / shot["name"]
    page.screenshot(path=str(out))
    print(f"  wrote {out.relative_to(REPO_ROOT)}")


def capture_airflow(page) -> None:
    """Screenshot the DAG's graph view, with a finished run selected.

    The credentials are the throwaway pair docker-compose sets for local development and
    the README documents; there is nothing here worth protecting.
    """
    page.goto(f"{AIRFLOW_URL}/login/", wait_until="domcontentloaded", timeout=60_000)
    if page.locator("input[name='username']").count():
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "admin")
        page.click("input[type='submit'], button[type='submit']")
        page.wait_for_load_state("networkidle", timeout=60_000)

    page.goto(
        f"{AIRFLOW_URL}/dags/novasupply_pipeline/graph",
        wait_until="networkidle",
        timeout=60_000,
    )
    # The graph is drawn client-side after the run data arrives.
    page.wait_for_selector("text=generate_supplier_documents", timeout=60_000)
    page.wait_for_timeout(4_000)

    # The graph canvas reserves far more height than seven nodes in a row need, so the
    # full viewport is mostly empty grid. Crop to the band that actually carries content.
    out = IMAGES_DIR / "airflow-dag.png"
    page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": 1440, "height": 700})
    print(f"  wrote {out.relative_to(REPO_ROOT)}")


def capture_lineage(page) -> None:
    """Screenshot dbt's lineage graph, with Elementary's own models filtered out.

    dbt docs encodes the graph's state in the URL fragment, so the exclusion goes straight
    into the address rather than being typed into the filter box and submitted: `g_v=1`
    opens the graph, `g_e` is the --exclude expression. Elementary contributes thirty
    models of its own, which bury the ones this project actually built.
    """
    page.goto(
        f"{DBT_DOCS_URL}/#!/overview?g_v=1&g_e=package:elementary",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.wait_for_timeout(3_000)

    # The fragment fills the --exclude box but does not redraw: the graph stays empty until
    # the button is pressed, so the URL alone gets you a blank canvas with a filter set.
    page.click("input[value='Update Graph']")

    # The graph draws onto a canvas rather than into SVG, so there is no node text to wait
    # for and no way to assert on its contents from the DOM. Wait for the canvas to be
    # laid out, then give the renderer a fixed moment. This one is checked by eye.
    page.wait_for_function(
        "() => { const c = document.querySelector('#graph-viz-wrapper canvas');"
        "return c && c.clientWidth > 200; }",
        timeout=60_000,
    )
    page.wait_for_timeout(6_000)

    out = IMAGES_DIR / "dbt-lineage.png"
    page.screenshot(path=str(out))
    print(f"  wrote {out.relative_to(REPO_ROOT)}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    airflow_only = "--airflow" in sys.argv
    lineage_only = "--lineage" in sys.argv

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)

        if airflow_only:
            print("airflow-dag.png")
            capture_airflow(page)
        elif lineage_only:
            print("dbt-lineage.png")
            capture_lineage(page)
        else:
            page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
            page.wait_for_selector("h1", timeout=60_000)
            for shot in SHOTS:
                print(shot["name"])
                capture(page, shot)

        browser.close()


if __name__ == "__main__":
    main()
