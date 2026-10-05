"""Live case-type filter test: python tests/test_filters.py."""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright, expect

from court_search import open_results_page, populate_cases


TEST_DATE = "06/09/2026"
CASE_TYPE_ID = 10071


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        try:
            page = await browser.new_page()
            print(f"Searching date {TEST_DATE} with case type {CASE_TYPE_ID}...", flush=True)
            grid = await open_results_page(
                page, TEST_DATE, case_type_id=CASE_TYPE_ID,
            )
            await expect(page.locator("#caseTypeIDDropDown")).to_have_value(str(CASE_TYPE_ID))
            await expect(page.locator("#openDateCalendar")).to_have_value(TEST_DATE)
            await expect(grid).to_be_visible()

            results = await populate_cases(grid)
            print(f"\nPASS: filter and date retained; results grid loaded.")
            print(f"Extracted {len(results)} visible cases.")
            for index, result in enumerate(results, start=1):
                print(f"\nCASE #{index}")
                result.print()

            await asyncio.to_thread(input, "\nPress ENTER to close the browser...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
