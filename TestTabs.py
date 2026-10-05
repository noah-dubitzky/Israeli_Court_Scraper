"""Live tab navigation test. Run with: python TestTabs.py"""

import asyncio

from playwright.async_api import async_playwright

from case import case
from case_details import CASE_TABS, open_case_folder, open_case_tab

TEST_CASE = case(
    type="",
    number="10195-09-26",
    name="",
    interest="",
    court="",
    status="",
    ID="",
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500, timeout=0)
        try:
            context = await browser.new_context()
            context.set_default_timeout(0)
            context.set_default_navigation_timeout(0)
            # open_case_folder calls open_court_page and looks up this case.
            page = await open_case_folder(
                context, TEST_CASE, disable_timeouts=True,
            )
            opened = 0

            for index, tab in enumerate(CASE_TABS, start=1):
                print(
                    f"\n[{index}/{len(CASE_TABS)}] Opening "
                    f"{tab.key} (folder {tab.folder_id})...",
                    flush=True,
                )
                try:
                    await open_case_tab(page, tab, disable_timeouts=True)
                except Exception:
                    print(f"FAILED: {tab.key}. Current URL: {page.url}")
                    raise

                opened += 1
                print(f"PASS: {tab.key}", flush=True)

            print(f"\nTabs completed: {opened} opened.")
            await asyncio.to_thread(
                input, "\nPress ENTER to close the browser..."
            )
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
