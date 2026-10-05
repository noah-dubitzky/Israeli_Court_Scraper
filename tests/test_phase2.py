import asyncio

from playwright.async_api import async_playwright

from case import case
from case_details import open_case_folder
from config import PAGE_TIMEOUT


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

        browser = await p.chromium.launch(
            headless=False
        )

        try:
            context = await browser.new_context()

            print("\n========================================")
            print("PHASE 2 TEST")
            print("========================================")
            print("Case number:", TEST_CASE.number)

            page = await open_case_folder(
                context,
                TEST_CASE,
            )

            print("\n========================================")
            print("SUCCESS")
            print("========================================")
            print("Case number:", TEST_CASE.number)
            print("Current URL:", page.url)
            print("Page title:", await page.title())

            await page.wait_for_load_state(
                "load",
                timeout=PAGE_TIMEOUT,
            )

            print("\n========================================")
            print("CASE PAGE CONTENT")
            print("========================================")
            print(await page.locator("body").inner_text())

            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                body = frame.locator("body")
                if await body.count():
                    frame_text = await body.inner_text()
                    if frame_text.strip():
                        print("\nFRAME:", frame.url)
                        print(frame_text)

            await asyncio.to_thread(
                input,
                "\nPress ENTER to close..."
            )

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
