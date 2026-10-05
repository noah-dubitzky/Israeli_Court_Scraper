"""Live related cases test: python tests/test_related_cases_extraction.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import CASE_TABS, _extract_tab_body, open_case_folder, open_case_tab


EXPECTED = {
    "case_type": "עא",
    "case_number": "3241-1/04",
    "case_name": 'הכשרת הישוב חברה לביטוח בע"מ  ואח\' נ\' בסאם מחמוד עיראקי',
    "case_interest": "ערעור שכנגד",
    "court": "העליון",
    "status": "סגור",
    "relationship": "אחר תיק מאוחד - סגור ערעור וערעור שכנגד",
    "case_id": "81632103",
}


def compare_results(body: dict) -> None:
    records = body["records"]
    if len(records) != 1:
        raise AssertionError(f"Expected 1 related case, received {len(records)}.")
    failures = []
    for field, expected in EXPECTED.items():
        actual = records[0].get(field)
        # Browser-rendered text collapses whitespace from the supplied HTML.
        matches = isinstance(actual, str) and " ".join(actual.split()) == " ".join(expected.split())
        print(
            f"{'PASS' if matches else 'FAIL'}: {field}: "
            f"expected={expected!r}, actual={actual!r}", flush=True,
        )
        if not matches:
            failures.append(field)
    if failures:
        raise AssertionError("Mismatched related-case fields: " + ", ".join(failures))


async def main() -> None:
    # User supplied 00200-0404; lookup expects number 00200 and month/year 04-04.
    selected_case = case(
        type="", number="00200-04-04", name="", interest="",
        court="", status="", ID="",
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500, timeout=0)
        try:
            context = await browser.new_context()
            context.set_default_timeout(0)
            context.set_default_navigation_timeout(0)
            page = await open_case_folder(context, selected_case, disable_timeouts=True)
            tab = next(tab for tab in CASE_TABS if tab.folder_id == "24")
            if not await open_case_tab(page, tab, disable_timeouts=True):
                raise AssertionError("Could not open Related cases.")
            body = await _extract_tab_body(page, tab, timeout=0)
            selected_case.details["tabs"] = {tab.key: {"body": body}}
            compare_results(body)
            print(f"\nPASS: related case matches for {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
