"""Measure extraction time and saved JSON size for a sample of court cases."""

import argparse
import asyncio
import json
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from playwright.async_api import async_playwright

from case import case
from case_details import CASE_TABS, GetCaseDetails, open_case_folder, split_case_number
from main import save_checkpoint


def load_cases(path: Path) -> list[case]:
    """Accept case numbers, case records, or the existing pipeline's output."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    records = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError("Input must be a list or an object with a 'cases' list.")
    items, seen = [], set()
    for record in records:
        if isinstance(record, str):
            record = {"number": record}
        if not isinstance(record, dict):
            raise ValueError("Each entry must be a case number or case object.")
        record = record.get("case", record)
        if not isinstance(record, dict) or not isinstance(record.get("number"), str):
            raise ValueError("Each case must have a string 'number'.")
        number = record["number"].strip()
        split_case_number(number)
        key = (number, str(record.get("court", "")))
        if key in seen:
            continue
        seen.add(key)
        # Start with fresh details so prior extraction cannot inflate results.
        items.append(case(**{field: str(record.get(field, "")) for field in
                             ("type", "name", "interest", "court", "status", "ID")},
                          number=number))
    return items


def update_summary(run: dict) -> None:
    entries = run["cases"]
    measured = [entry for entry in entries if entry["status"] in ("completed", "partial")]
    run["summary"] = {
        "attempted_cases": len(entries),
        "completed_cases": sum(entry["status"] == "completed" for entry in entries),
        "partial_cases": sum(entry["status"] == "partial" for entry in entries),
        "failed_cases": sum(entry["status"] == "failed" for entry in entries),
        "average_extraction_seconds": (sum(entry["extraction_seconds"] for entry in measured)
                                       / len(measured) if measured else None),
        "average_storage_bytes": (sum(entry["storage_bytes"] for entry in measured)
                                  / len(measured) if measured else None),
        "total_storage_bytes": sum(entry["storage_bytes"] for entry in entries),
        "average_basis": "completed and partial cases; failed attempts excluded",
    }


async def measure_cases(context, selected: list[case], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    run = {"started_at": datetime.now(timezone.utc).isoformat(),
           "requested_cases": len(selected), "cases": []}
    summary_path = output_dir / "summary.json"
    update_summary(run)
    save_checkpoint(summary_path, run)
    for index, item in enumerate(selected, 1):
        print(f"\n[{index}/{len(selected)}] Extracting {item.number}...", flush=True)
        page = None
        entry = {"number": item.number, "status": "failed", "error": None}
        started = perf_counter()
        try:
            page = await open_case_folder(context, item)
            await GetCaseDetails(item, page)
            missing = [tab.key for tab in CASE_TABS if tab.key not in item.details.get("tabs", {})]
            entry["missing_tabs"] = missing
            entry["status"] = "partial" if missing else "completed"
        except Exception as error:
            entry["error"] = f"{type(error).__name__}: {error}"
        finally:
            entry["extraction_seconds"] = perf_counter() - started
            if page is not None:
                try:
                    await page.close()
                except Exception as error:
                    entry["cleanup_error"] = f"{type(error).__name__}: {error}"
            filename = f"case_{index:03d}.json"
            payload = json.dumps(asdict(item), ensure_ascii=False, indent=2).encode("utf-8")
            (output_dir / filename).write_bytes(payload)
            entry["file"] = filename
            entry["storage_bytes"] = (output_dir / filename).stat().st_size
            run["cases"].append(entry)
            update_summary(run)
            save_checkpoint(summary_path, run)
        print(f"[{index}/{len(selected)}] {item.number}: {entry['status']} | "
              f"{entry['extraction_seconds']:.2f} seconds | "
              f"{entry['storage_bytes']} bytes ({entry['storage_bytes'] / 1024:.2f} KiB)", flush=True)
        if entry["error"]:
            print(entry["error"], flush=True)
    run["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(summary_path, run)
    summary = run["summary"]
    print(f"\nCompleted: {summary['completed_cases']}; partial: {summary['partial_cases']}; "
          f"failed: {summary['failed_cases']}")
    if summary["average_extraction_seconds"] is not None:
        print(f"Average extraction time: {summary['average_extraction_seconds']:.2f} seconds")
        print(f"Average storage: {summary['average_storage_bytes']:.2f} bytes "
              f"({summary['average_storage_bytes'] / 1024:.2f} KiB)")
        print("Averages include completed and partial cases; failed attempts are excluded.")
    else:
        print("Averages unavailable: no successful extractions.")
    print(f"Saved to: {output_dir.resolve()}", flush=True)
    return run


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("Case_Test_Output.json"))
    parser.add_argument("--count", "-x", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.count is None:
        while True:
            try:
                args.count = int(input("Number of cases to extract [10]: ").strip() or "10")
                if args.count > 0:
                    break
            except ValueError:
                pass
            print("Enter a positive integer.")
    if args.count < 1:
        parser.error("--count must be positive")
    try:
        items = load_cases(args.input)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if len(items) < args.count:
        parser.error(f"Requested {args.count} cases, but {args.input} contains only "
                     f"{len(items)} unique cases. Supply more cases or lower --count.")
    selected = random.Random(args.seed).sample(items, args.count)
    output_dir = args.output_dir or Path("output") / datetime.now().strftime(
        "case_consumption_%Y%m%d_%H%M%S_%f")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)
        try:
            context = await browser.new_context()
            run = await measure_cases(context, selected, output_dir)
        finally:
            await browser.close()
    if run["summary"]["failed_cases"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
