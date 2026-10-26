"""Run main.py for type 1, starting today and moving backward one day at a time."""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MIB = 1024 * 1024


def search_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use DD/MM/YYYY") from error


def run_days(start: date, output: Path, min_disk_mib: int,
             max_days: int | None = None) -> int:
    output.mkdir(parents=True, exist_ok=True)
    current = start
    count = 0
    while max_days is None or count < max_days:
        disk = shutil.disk_usage(output).free / MIB
        if disk < min_disk_mib:
            print(f"Stopping before {current}: free disk {disk:.0f} MiB. Checkpoints preserved.", flush=True)
            return 2
        checkpoint = output / f"type_1_{current.isoformat()}.json"
        command = [sys.executable, "-u", str(ROOT / "main.py"),
                   "--date", current.strftime("%d/%m/%Y"),
                   "--case-type-id", "1", "--headless", "--non-interactive",
                   "--progress-to-stderr",
                   "--resume", str(checkpoint.resolve())]
        print(f"Extracting day: {current.strftime('%d/%m/%Y')}", flush=True)
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        # Discard verbose scraper output without buffering it in RAM or a log.
        # Keep stderr visible so a fatal failure can still be diagnosed.
        result = subprocess.run(command, cwd=ROOT, env=child_env,
                                stdout=subprocess.DEVNULL)
        if result.returncode != 0:
            print(f"main.py exited with {result.returncode}; stopping on {current}. "
                  "Restart this command to resume.", flush=True)
            return 1
        count += 1
        if current == date.min:
            return 0
        current -= timedelta(days=1)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=search_date, default=None,
                        help="DD/MM/YYYY; defaults to today's EC2 system date")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "daily_type_1")
    parser.add_argument("--min-disk-mib", type=int, default=512)
    parser.add_argument("--max-days", type=int, help="Optional limit for a short run")
    args = parser.parse_args()
    if args.min_disk_mib < 0:
        parser.error("Disk threshold must be nonnegative")
    if args.max_days is not None and args.max_days < 1:
        parser.error("--max-days must be positive")
    try:
        return run_days(args.start_date or date.today(), args.output_dir,
                        args.min_disk_mib, args.max_days)
    except KeyboardInterrupt:
        print("Stopped. Restart the command to resume saved checkpoints.", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
