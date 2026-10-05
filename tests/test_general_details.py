"""Live General details test: python tests/test_general_details.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import GetCaseDetails, open_case_folder


EXPECTED = {
    "case_title": "מדינת ישראל נ' אליהו",
    "filing_description": "פרטי כתב בקשה למעצר",
    "access_status": "פתוח לציבור",
    "case_status": "סגור",
    "claim_amount": None,
    "filing_id": 0,
}


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

            records = result.details["tabs"]["general_details"]["body"]["records"]
            if len(records) != 1:
                raise AssertionError(f"Expected 1 record, received {len(records)}: {records!r}")

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

            print(f"\nPASS: all six fields match for case {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
