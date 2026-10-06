"""Collect all case-search summaries for one random day in the last ten years."""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from playwright.async_api import async_playwright

from court_search import open_results_page, populate_cases
from main import save_checkpoint


def choose_date(today: date, seed: int | None = None) -> date:
    try:
        start = today.replace(year=today.year - 10)
    except ValueError:
        start = today.replace(year=today.year - 10, day=28)
    return start + timedelta(days=random.Random(seed).randrange((today - start).days))


async def collect_cases(context, selected_date: date, output: Path,
                        seed: int | None = None) -> dict:
    started = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    search_date = selected_date.strftime("%d/%m/%Y")
    print(f"Selected random date: {search_date}", flush=True)
    page = await context.new_page()
    try:
        for attempt in range(1, 4):
            try:
                grid = await open_results_page(page, search_date)

                def progress():
                    print("Collected another results page...", flush=True)

                cases = await populate_cases(grid, on_progress=progress)
                records = []
                for item in cases:
                    record = asdict(item)
                    record.pop("details", None)
                    records.append(record)
                result = {
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "search_date": search_date,
                    "seed": seed,
                    "total_cases": len(records),
                    "elapsed_seconds": perf_counter() - started,
                    "cases": records,
                }
                # Replace the input only after the entire search was collected.
                save_checkpoint(output, result)
                print(f"Saved {len(records)} cases to {output.resolve()}", flush=True)
                print(f"Elapsed time: {result['elapsed_seconds']:.2f} seconds", flush=True)
                if len(records) < 10:
                    print("This date has fewer than 10 cases. Use a smaller --count in the "
                          "consumption script, or run this collector again for another date.", flush=True)
                return result
            except Exception as error:
                print(f"Attempt {attempt}/3 failed for {search_date}: {error}", flush=True)
                if attempt == 3:
                    raise
    finally:
        await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="Repeat the chosen date when run on the same day.")
    parser.add_argument("--output", type=Path, default=Path("Case_Test_Output.json"))
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    selected_date = choose_date(date.today(), args.seed)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)
        try:
            context = await browser.new_context()
            await collect_cases(context, selected_date, args.output, args.seed)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
