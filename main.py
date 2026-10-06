"""Search cases, enrich them sequentially, and checkpoint results to JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from case_details import CASE_TABS, GetCaseDetails, open_case_folder
from config import DEFAULT_SEARCH_DATE
from court_search import open_results_page, populate_cases


def save_checkpoint(path: Path, run: dict) -> None:
    """Replace a checkpoint only after its new JSON has been written fully."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def run_pipeline(context, date: str, case_type_id: int | None,
                       output: Path, max_cases: int | None = None) -> dict:
    if max_cases is not None and max_cases < 1:
        raise ValueError("max_cases must be positive.")
    search_page = await context.new_page()
    try:
        grid = await open_results_page(search_page, date, case_type_id=case_type_id)
        cases = await populate_cases(grid, max_cases=max_cases)
        run = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "search_date": date,
            "case_type_id": case_type_id,
            "cases": [{"status": "pending", "error": None, "case": asdict(item)}
                      for item in cases],
        }
        save_checkpoint(output, run)
        selected = cases if max_cases is None else cases[:max_cases]
        for index, item in enumerate(selected):
            entry = run["cases"][index]
            entry["status"] = "in_progress"
            save_checkpoint(output, run)
            print(f"\n[{index + 1}/{len(selected)}] Extracting {item.number}...", flush=True)
            detail_page = None
            try:
                detail_page = await open_case_folder(context, item)
                await GetCaseDetails(item, detail_page)
                missing = [tab.key for tab in CASE_TABS
                           if tab.key not in item.details.get("tabs", {})]
                entry["status"] = "partial" if missing else "completed"
                entry["missing_tabs"] = missing
            except Exception as error:
                entry["status"] = "failed"
                entry["error"] = f"{type(error).__name__}: {error}"
                print(f"FAILED {item.number}: {entry['error']}", flush=True)
            finally:
                # Save partial data even on cancellation; in_progress marks an
                # interrupted attempt that can be identified for a later retry.
                entry["case"] = asdict(item)
                try:
                    save_checkpoint(output, run)
                finally:
                    if detail_page is not None:
                        try:
                            await detail_page.close()
                        except Exception as error:
                            print(f"Could not close detail page: {error}", flush=True)
                print(f"\nRESULT FOR CASE {item.number}", flush=True)
                print(json.dumps(entry, ensure_ascii=False, indent=2), flush=True)
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_checkpoint(output, run)
        counts = {status: sum(entry["status"] == status for entry in run["cases"])
                  for status in ("completed", "partial", "failed", "pending")}
        print(f"\nResults: {counts}\nSaved to: {output.resolve()}", flush=True)
        return run
    finally:
        await search_page.close()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None)
    parser.add_argument("--case-type-id", type=int, default=None)
    parser.add_argument("--max-cases", type=int, default=None,
                        help="Limit both search-result collection and detail lookups.")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")
    return args


def prompt_search_options(args):
    """Prompt for search settings not supplied on the command line."""
    while True:
        value = args.date or input(
            f"Search date (DD/MM/YYYY) [{DEFAULT_SEARCH_DATE}]: "
        ).strip() or DEFAULT_SEARCH_DATE
        try:
            args.date = datetime.strptime(value, "%d/%m/%Y").strftime("%d/%m/%Y")
            break
        except ValueError:
            print("Enter a valid date in DD/MM/YYYY format.")
            args.date = None

    if args.case_type_id is None:
        while True:
            value = input("Case-type filter (integer; ENTER for no filter): ").strip()
            if not value:
                break
            try:
                args.case_type_id = int(value)
                break
            except ValueError:
                print("Enter an integer or leave the filter blank.")

    if args.max_cases is None:
        while True:
            value = input("Maximum cases to extract (positive integer; ENTER for all): ").strip()
            if not value:
                break
            try:
                maximum = int(value)
                if maximum < 1:
                    raise ValueError
                args.max_cases = maximum
                break
            except ValueError:
                print("Enter a positive integer or leave the maximum blank.")
    return args


async def main() -> None:
    args = prompt_search_options(parse_args())
    output = args.output or Path("output") / (
        datetime.now().strftime("cases_%Y%m%d_%H%M%S_%f.json")
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        try:
            context = await browser.new_context()
            await run_pipeline(context, args.date, args.case_type_id, output, args.max_cases)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
