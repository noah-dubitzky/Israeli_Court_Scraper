"""Live decision test: python tests/test_decisions_extraction.py."""

import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from config import ELEMENT_TIMEOUT, PAGE_TIMEOUT
from main import save_checkpoint
from case_details import CASE_TABS, _extract_tab_body, open_case_folder, open_case_tab


# Fixed expectations transcribed from the decision table and both Details pages.
EXPECTED = json.loads(
    Path(__file__).with_name("fixtures").joinpath("decisions_expected.json")
    .read_text(encoding="utf-8")
)


def compare_results(body: dict) -> None:
    records = body["records"]
    if len(records) != len(EXPECTED):
        raise AssertionError(f"Expected 2 decisions, received {len(records)}.")
    by_id = {record["decision_id"]: record for record in records}
    if set(by_id) != {record["decision_id"] for record in EXPECTED}:
        raise AssertionError(f"Unexpected or duplicate decision IDs: {list(by_id)}")

    failures = []

    def compare(actual: dict, expected: dict, path: str) -> None:
        for field, value in expected.items():
            label = f"{path}.{field}"
            received = actual.get(field)
            if isinstance(value, dict) and isinstance(received, dict):
                compare(received, value, label)
                continue
            matches = field in actual and type(received) is type(value) and received == value
            # These spans are read with inner_text(), which collapses HTML
            # whitespace. The fixture preserves the original repeated spaces.
            if field in {"decision_name", "document_name"} and isinstance(received, str):
                matches = " ".join(received.split()) == " ".join(value.split())
            print(
                f"{'PASS' if matches else 'FAIL'}: {label}: "
                f"expected={value!r}, actual={received!r}", flush=True,
            )
            if not matches:
                failures.append(label)

    for record in EXPECTED:
        decision_id = record["decision_id"]
        compare(by_id[decision_id], record, str(decision_id))
    if failures:
        raise AssertionError("Mismatched decision fields: " + ", ".join(failures))


async def main() -> None:
    selected_case = case(
        type="", number="45026-12-19", name="", interest="",
        court="", status="", ID="",
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500, timeout=PAGE_TIMEOUT)
        try:
            context = await browser.new_context()
            context.set_default_timeout(ELEMENT_TIMEOUT)
            context.set_default_navigation_timeout(PAGE_TIMEOUT)
            page = await open_case_folder(context, selected_case)
            tab = next(tab for tab in CASE_TABS if tab.folder_id == "18")
            if not await open_case_tab(page, tab):
                raise AssertionError("Could not open Decisions in the case.")
            body = await _extract_tab_body(page, tab, timeout=ELEMENT_TIMEOUT)
            selected_case.details["tabs"] = {tab.key: {"body": body}}
            output = Path("output") / f"decisions_{selected_case.number}.json"
            save_checkpoint(output, {"case_number": selected_case.number, **body})
            print(f"Extracted {len(body['records'])} decisions. Saved to: {output.resolve()}", flush=True)
            compare_results(body)
            print(f"\nPASS: both decisions and their Details match for {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
