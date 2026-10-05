import asyncio

from playwright.async_api import async_playwright

from court_search import (
    open_results_page,
    populate_cases,
)


TEST_DATE = "06/09/2026"


async def main() -> None:
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=False
        )

        try:
            page = await browser.new_page()

            print("\n========================================")
            print("PHASE 1 TEST")
            print("========================================")
            print("Search date:", TEST_DATE)

            results_grid = await open_results_page(
                page,
                TEST_DATE,
            )

            results = await populate_cases(
                results_grid
            )

            print("\n========================================")
            print("RESULTS")
            print("========================================")
            print("Total cases:", len(results))

            for index, result in enumerate(
                results,
                start=1,
            ):
                print(
                    "\n----------------------------------------"
                )

                print(f"CASE #{index}")

                print(
                    "----------------------------------------"
                )

                result.print()

            await asyncio.to_thread(
                input,
                "\nPress ENTER to close..."
            )

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())