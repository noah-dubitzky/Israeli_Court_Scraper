"""Count cases on 100 random completed days from the last ten years."""

import argparse
import asyncio
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from court_search import (
    navigate_to_date_search, open_court_page, populate_cases, search_cases_on_page,
)
from main import save_checkpoint


def sample_days(today: date, seed: int | None = None) -> list[date]:
    """Sample without replacement, including weekends and holidays."""
    try:
        start = today.replace(year=today.year - 10)
    except ValueError:  # February 29 in a non-leap starting year.
        start = today.replace(year=today.year - 10, day=28)
    offsets = random.Random(seed).sample(range((today - start).days), 100)
    return sorted(start + timedelta(days=offset) for offset in offsets)


def summarize(result: dict) -> None:
    counts = [entry["count"] for entry in result["days"]
              if entry["count"] is not None]
    result["successful_days"] = len(counts)
    result["failed_days"] = sum(entry["error"] is not None for entry in result["days"])
    result["total_cases"] = sum(counts)
    result["average_cases_per_day"] = sum(counts) / len(counts) if counts else None
    result["complete"] = len(counts) == len(result["days"])


def is_search_page(page) -> bool:
    return urlsplit(page.url).path.lower().endswith("/searchcase/casessearchview.aspx")


async def count_date(page, search_date: str, case_type_id: int | None) -> int:
    """Reuse search, restoring it via the menu if the site returned home."""
    if not is_search_page(page):
        if urlsplit(page.url).path.lower().endswith("/homepage.aspx"):
            print("Site returned home; reopening the date-search menu...", flush=True)
            await navigate_to_date_search(page)
        else:
            await open_court_page(page)
    grid = await search_cases_on_page(page, search_date, case_type_id=case_type_id)
    if not is_search_page(page):
        raise RuntimeError("Site left the search page during search.")
    cases = await populate_cases(grid)
    if not is_search_page(page):
        raise RuntimeError("Site left the search page during collection.")
    return len(cases)


async def count_days(context, days: list[date], output: Path,
                     case_type_id: int | None = None, seed: int | None = None) -> dict:
    started = perf_counter()
    result = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": 0.0,
        "seed": seed,
        "case_type_id": case_type_id,
        "days": [{"date": day.strftime("%d/%m/%Y"), "count": None, "error": None}
                 for day in days],
    }
    summarize(result)
    save_checkpoint(output, result)
    print("Sampled dates: " + ", ".join(entry["date"] for entry in result["days"]), flush=True)
    page = await context.new_page()
    try:
        for index, entry in enumerate(result["days"], 1):
            for attempt in range(1, 4):
                try:
                    entry["count"] = await count_date(page, entry["date"], case_type_id)
                    entry["error"] = None
                    break
                except Exception as error:
                    entry["error"] = f"{type(error).__name__}: {error}"
                    print(f"{entry['date']}: attempt {attempt}/3 failed: {entry['error']}", flush=True)
            summarize(result)
            result["elapsed_seconds"] = perf_counter() - started
            save_checkpoint(output, result)
            value = entry["count"] if entry["count"] is not None else "FAILED"
            print(f"[{index}/{len(days)}] {entry['date']}: {value} cases", flush=True)
    finally:
        await page.close()
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["elapsed_seconds"] = perf_counter() - started
    save_checkpoint(output, result)
    print(f"\nTotal cases: {result['total_cases']}")
    print(f"Days counted: {result['successful_days']}/{len(days)}")
    elapsed = result["elapsed_seconds"]
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"Time to record {len(days)} days: {hours:02d}:{minutes:02d}:{seconds:02d} "
          f"({elapsed:.2f} seconds)")
    average = result["average_cases_per_day"]
    print(f"Average cases per day: {average:.2f}" if average is not None
          else "Average cases per day: unavailable")
    if result["failed_days"]:
        print(f"Incomplete sample: {result['failed_days']} failed days excluded from the average.")
    print(f"Saved to: {output.resolve()}", flush=True)
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="Repeat the same sample when run on the same date.")
    parser.add_argument("--case-type-id", type=int, default=None,
                        help="Optional case-type filter; defaults to all types.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    today = date.today()
    days = sample_days(today, args.seed)
    output = args.output or Path("output") / datetime.now().strftime(
        "average_cases_per_day_%Y%m%d_%H%M%S_%f.json")
    print("Sampling 100 distinct dates in the last ten years, through yesterday.")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)
        try:
            context = await browser.new_context()
            result = await count_days(context, days, output, args.case_type_id, args.seed)
        finally:
            await browser.close()
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
