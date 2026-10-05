"""Live folder 5 test: python tests/test_representatives.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import GetCaseDetails, open_case_folder


EXPECTED = {
    "role": "בא כוח מבקשים",
    "full_name": "לא מזוהה לא מזוהה",
    "proceeding_type": "כתב טענות עיקרי",
    "activity_status_id": 1,
    "case_party_id": 80841456,
}


def compare_records(records: list[dict]) -> None:
    if len(records) != 1:
        raise AssertionError(f"Expected 1 representative, received {len(records)}: {records!r}")
    failures = []
    for field, expected in EXPECTED.items():
        actual = records[0][field]
        matches = actual == expected
        print(
            f"{'PASS' if matches else 'FAIL'}: {field}: "
            f"expected={expected!r}, actual={actual!r}", flush=True,
        )
        if not matches:
            failures.append(field)
    if failures:
        raise AssertionError("Mismatched fields: " + ", ".join(failures))


async def main() -> None:
    selected_case = case(
        type="", number="00010-10-10", name="", interest="",
        court="", status="", ID="",
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500, timeout=0)
        try:
            context = await browser.new_context()
            context.set_default_timeout(0)
            context.set_default_navigation_timeout(0)
            page = await open_case_folder(
                context, selected_case, disable_timeouts=True,
            )
            result = await GetCaseDetails(
                selected_case, page, disable_timeouts=True,
            )
            if result is not selected_case:
                raise AssertionError("GetCaseDetails did not return the supplied case.")
            compare_records(
                result.details["tabs"]["power_of_attorney"]["body"]["records"]
            )
            print(f"\nPASS: representative matches for case {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
