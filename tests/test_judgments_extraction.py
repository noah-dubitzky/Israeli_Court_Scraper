"""Live judgments test: python tests/test_judgments_extraction.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import CASE_TABS, _extract_tab_body, open_case_folder, open_case_tab


EXPECTED = {
    "decision_id": 84224191,
    "description": 'פסק דין  מתאריך  17/02/13  שניתנה ע"י  שכיב סרחאן',
    "signed_at": "17/02/2013",
    "signed_by": "שכיב סרחאן",
    "details": {
        "decision_name": 'פסק דין  מתאריך  17/02/13  שניתנה ע"י  שכיב סרחאן',
        "document_name": 'פסק דין  מתאריך  17/02/13  שניתנה ע"י  שכיב סרחאן',
        "given_by": "שכיב סרחאן",
        "signature_date": "17/02/2013",
        "description": "",
        "confidentiality": "פתוח לציבור",
        "decision_type": "פסק דין",
        "given_ex_parte": False,
        "release_to_other_side": False,
        "show_in_selected_decisions": False,
        "is_substantive": False,
        "is_technical": True,
    },
}


def compare_results(body: dict) -> None:
    records = body["records"]
    if len(records) != 1:
        raise AssertionError(f"Expected 1 judgment, received {len(records)}.")
    failures = []

    def compare(actual: dict, expected: dict, path: str) -> None:
        for field, value in expected.items():
            label = f"{path}.{field}"
            received = actual.get(field)
            if isinstance(value, dict) and isinstance(received, dict):
                compare(received, value, label)
                continue
            matches = field in actual and type(received) is type(value) and received == value
            # Rendered spans and grid cells collapse whitespace in source HTML.
            if isinstance(value, str) and isinstance(received, str):
                matches = " ".join(received.split()) == " ".join(value.split())
            print(
                f"{'PASS' if matches else 'FAIL'}: {label}: "
                f"expected={value!r}, actual={received!r}", flush=True,
            )
            if not matches:
                failures.append(label)

    compare(records[0], EXPECTED, "judgment")
    if failures:
        raise AssertionError("Mismatched judgment fields: " + ", ".join(failures))


async def main() -> None:
    selected_case = case(
        type="", number="00100-04-04", name="", interest="",
        court="", status="", ID="",
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500, timeout=0)
        try:
            context = await browser.new_context()
            context.set_default_timeout(0)
            context.set_default_navigation_timeout(0)
            page = await open_case_folder(context, selected_case, disable_timeouts=True)
            tab = next(tab for tab in CASE_TABS if tab.folder_id == "21")
            if not await open_case_tab(page, tab, disable_timeouts=True):
                raise AssertionError("Could not open Judgments.")
            body = await _extract_tab_body(page, tab, timeout=0)
            selected_case.details["tabs"] = {tab.key: {"body": body}}
            compare_results(body)
            print(f"\nPASS: judgment row and Details match for {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
