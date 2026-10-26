"""Search cases, enrich them sequentially, and checkpoint results to JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

from playwright.async_api import async_playwright

from case import case
from case_details import CASE_TABS, CaseLookupError, GetCaseDetails, open_case_folder
from config import DEFAULT_SEARCH_DATE
from court_search import open_results_page, populate_cases


EXTRACTION_TABS = tuple(tab for tab in CASE_TABS if tab.key == "sides")


def save_checkpoint(path: Path, run: dict) -> None:
    """Replace a checkpoint only after its new JSON has been written fully."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 5:
                raise
            sleep(0.2 * (2 ** attempt))


async def run_pipeline(context, date: str, case_type_id: int | None,
                       output: Path, *, checkpoint: dict | None = None,
                       progress_to_stderr: bool = False) -> dict:
    search_page = None
    detail_page = None
    try:
        if checkpoint is None:
            search_page = await context.new_page()
            grid = await open_results_page(search_page, date, case_type_id=case_type_id)
            cases = await populate_cases(grid)
            run = {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "search_date": date,
                "case_type_id": case_type_id,
                "cases": [{"status": "pending", "error": None, "case": asdict(item)}
                          for item in cases],
            }
        else:
            run = checkpoint
            cases = [case(**entry["case"]) for entry in run["cases"]]
        run.pop("finished_at", None)
        save_checkpoint(output, run)
        selected = cases
        for index, item in enumerate(selected):
            entry = run["cases"][index]
            if entry["status"] == "completed" and "sides" in item.details.get("tabs", {}):
                continue
            entry["status"] = "in_progress"
            entry["error"] = None
            entry.pop("missing_tabs", None)
            save_checkpoint(output, run)
            if progress_to_stderr:
                print(f"Extracting case {index + 1}/{len(selected)}", file=sys.stderr, flush=True)
            print(f"\n[{index + 1}/{len(selected)}] Extracting {item.number}...", flush=True)
            try:
                try:
                    detail_page = await open_case_folder(context, item, page=detail_page)
                except CaseLookupError:
                    if detail_page is None:
                        raise
                    print("Case lookup returned an error; retrying in a new page.", flush=True)
                    await detail_page.close()
                    detail_page = None
                    detail_page = await open_case_folder(context, item)
                await GetCaseDetails(item, detail_page, tabs=EXTRACTION_TABS)
                missing = [tab.key for tab in EXTRACTION_TABS
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
                save_checkpoint(output, run)
                print(f"\nRESULT FOR CASE {item.number}", flush=True)
                print(json.dumps(entry, ensure_ascii=False, indent=2), flush=True)
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_checkpoint(output, run)
        counts = {status: sum(entry["status"] == status for entry in run["cases"])
                  for status in ("completed", "partial", "failed", "pending")}
        print(f"\nResults: {counts}\nSaved to: {output.resolve()}", flush=True)
        return run
    finally:
        try:
            if detail_page is not None:
                await detail_page.close()
        finally:
            if search_page is not None:
                await search_page.close()


def load_checkpoint(path: Path) -> dict:
    """Validate saved case data before launching a browser or changing the file."""
    run = json.loads(path.read_text(encoding="utf-8"))
    datetime.strptime(run["search_date"], "%d/%m/%Y")
    if run["case_type_id"] is not None and type(run["case_type_id"]) is not int:
        raise ValueError("Checkpoint case_type_id must be an integer or null.")
    if not isinstance(run["cases"], list):
        raise ValueError("Checkpoint cases must be a list.")
    for entry in run["cases"]:
        if entry["status"] not in {"pending", "in_progress", "failed", "partial", "completed"}:
            raise ValueError("Unknown checkpoint case status.")
        item = case(**entry["case"])
        if not isinstance(item.details, dict) or not isinstance(item.details.get("tabs", {}), dict):
            raise ValueError("Invalid checkpoint case details.")
    return run


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None)
    parser.add_argument("--case-type-id", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--progress-to-stderr", action="store_true",
                        help="Emit concise case progress even when stdout is suppressed.")
    parser.add_argument("--resume", type=Path, help="Resume this JSON file, or create it on the first run.")
    parser.add_argument("--non-interactive", action="store_true", help="Require --date; omitted case type means all types.")
    args = parser.parse_args()
    if args.resume and args.output and args.resume.resolve() != args.output.resolve():
        parser.error("--resume and --output must refer to the same file")
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

    return args


async def main() -> None:
    args = parse_args()
    checkpoint = load_checkpoint(args.resume) if args.resume and args.resume.exists() else None
    if checkpoint is not None:
        if args.date is not None and args.date != checkpoint["search_date"]:
            raise ValueError("--date conflicts with the checkpoint search date")
        if args.case_type_id is not None and args.case_type_id != checkpoint["case_type_id"]:
            raise ValueError("--case-type-id conflicts with the checkpoint filter")
        args.date, args.case_type_id = checkpoint["search_date"], checkpoint["case_type_id"]
        if all(entry["status"] == "completed" and "sides" in entry["case"].get("details", {}).get("tabs", {})
               for entry in checkpoint["cases"]):
            print("Checkpoint is already complete.", flush=True)
            return
    elif args.non_interactive:
        if args.date is None:
            raise ValueError("--date is required when creating a non-interactive run")
        datetime.strptime(args.date, "%d/%m/%Y")
    else:
        args = prompt_search_options(args)
    output = args.resume or args.output or Path("output") / (
        datetime.now().strftime("cases_%Y%m%d_%H%M%S_%f.json")
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        try:
            context = await browser.new_context()
            result = await run_pipeline(context, args.date, args.case_type_id, output,
                                        checkpoint=checkpoint,
                                        progress_to_stderr=args.progress_to_stderr)
            if any(entry["status"] != "completed" for entry in result["cases"]):
                raise SystemExit(1)
        finally:
            await browser.close()


if __name__ == "__main__":
    started = perf_counter()
    try:
        asyncio.run(main())
    finally:
        elapsed = perf_counter() - started
        print(f"\nTotal script runtime: {elapsed:.2f} seconds ({elapsed / 60:.2f} minutes)", flush=True)
