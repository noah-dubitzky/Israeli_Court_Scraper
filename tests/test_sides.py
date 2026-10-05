"""Live Sides test: python tests/test_sides.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from case import case
from case_details import GetCaseDetails, open_case_folder


EXPECTED = [
    {
        "role": "מבקש 1",
        "full_name": "מדינת ישראל",
        "party_characteristic": "",
        "representative_names": "לא מזוהה לא מזוהה",
        "judgment_result": None,
        "proceeding_type": "כתב טענות עיקרי",
        "activity_status_id": 1,
        "case_party_id": 80841455,
    },
    {
        "role": "חשוד 1",
        "full_name": "יוסף אליהו",
        "party_characteristic": "",
        "representative_names": "",
        "judgment_result": None,
        "proceeding_type": "כתב טענות עיקרי",
        "activity_status_id": 1,
        "case_party_id": 80841457,
    },
]


def compare_records(records: list[dict]) -> None:
    """Compare by party ID so grid sorting does not affect the result."""
    if len(records) != len(EXPECTED):
        raise AssertionError(f"Expected 2 parties, received {len(records)}: {records!r}")
    actual_by_id = {record["case_party_id"]: record for record in records}
    expected_ids = {record["case_party_id"] for record in EXPECTED}
    if set(actual_by_id) != expected_ids:
        raise AssertionError(
            f"Expected party IDs {expected_ids}, received "
            f"{[record['case_party_id'] for record in records]}"
        )

    failures = []
    for expected_record in EXPECTED:
        party_id = expected_record["case_party_id"]
        actual_record = actual_by_id[party_id]
        for field, expected in expected_record.items():
            actual = actual_record[field]
            matches = actual == expected
            print(
                f"{'PASS' if matches else 'FAIL'}: party {party_id}, {field}: "
                f"expected={expected!r}, actual={actual!r}", flush=True,
            )
            if not matches:
                failures.append(f"{party_id}.{field}")
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
            compare_records(result.details["tabs"]["sides"]["body"]["records"])
            print(f"\nPASS: both parties match for case {selected_case.number}.")
            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
