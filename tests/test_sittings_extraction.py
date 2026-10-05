"""Live hearings test: python tests/test_sittings_extraction.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import (
    CASE_TABS,
    _extract_tab_body,
    open_case_folder,
    open_case_tab,
)


# Expected values from the supplied HTML, including the blank motion number.
# The current-hearings HTML contains only three columns; other fields are
# deliberately not asserted because the reference provides no values for them.
EXPECTED = {
    "all_hearings": [{
        "meeting_date": "18/09/2010",
        "start_time": "20:30",
        "finish_time": "21:00",
        "hearing_type": "דיון",
        "motion_number": "",
        "hearing_status": "התקיים",
        "protocol_exists": "כן",
        "judges": "רים נדאף",
    }],
    "current_hearings": [{
        "meeting_date": "18/09/2010",
        "start_time": "20:30",
        "hearing_type": "דיון",
    }],
}


def compare_results(body: dict) -> None:
    failures = []
    for subtab, expected_records in EXPECTED.items():
        records = body[subtab]["records"]
        if len(records) != len(expected_records):
            message = (
                f"{subtab}: expected {len(expected_records)} hearing, "
                f"received {len(records)}: {records!r}"
            )
            print(f"FAIL: {message}", flush=True)
            failures.append(message)
            continue
        for actual_record, expected_record in zip(records, expected_records):
            for field, expected in expected_record.items():
                actual = actual_record.get(field)
                matches = field in actual_record and actual == expected
                print(
                    f"{'PASS' if matches else 'FAIL'}: {subtab}.{field}: "
                    f"expected={expected!r}, actual={actual!r}", flush=True,
                )
                if not matches:
                    failures.append(f"{subtab}.{field}")
    if failures:
        raise AssertionError("Hearing comparison failed: " + "; ".join(failures))


async def main() -> None:
    selected_case = case(
        type="", number="26571-09-10", name="", interest="",
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
            tab = next(tab for tab in CASE_TABS if tab.folder_id == "10")
            if not await open_case_tab(page, tab, disable_timeouts=True):
                raise AssertionError("Could not open Discussion dates.")
            body = await _extract_tab_body(page, tab, timeout=0)
            selected_case.details["tabs"] = {tab.key: {"body": body}}
            compare_results(body)
            print(
                f"\nPASS: both hearing tabs match for case {selected_case.number}.",
                flush=True,
            )
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
