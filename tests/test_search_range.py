"""Search-only run with fixed settings: python tests/test_search_range.py."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from court_search import open_court_page, search_cases_on_page, populate_cases


START_DATE = date(2000, 1, 1)
END_DATE = date(2000, 1, 10)
CASE_TYPE_ID = None  # None searches all case types.
MAX_ENTRIES = None  # None collects all entries in the date range.
MAX_SEARCH_ATTEMPTS = 3
STALL_SECONDS = 25


async def dismiss_error_popup(page) -> bool:
    """Dismiss recognizable HTML dialogs without reading or saving their messages."""
    dialogs = page.locator(
        '[role="dialog"]:visible, [role="alertdialog"]:visible, '
        '.ui-dialog:visible, .modal:visible'
    )
    close_name = re.compile(r"^(?:OK|Close|Dismiss|Cancel|אישור|אשר|סגור|סגירה|ביטול|×|✕)$", re.I)
    for dialog in await dialogs.all():
        buttons = dialog.get_by_role("button", name=close_name).or_(
            dialog.locator('.ui-dialog-titlebar-close, .btn-close, [data-dismiss="modal"], [data-bs-dismiss="modal"]')
        ).filter(visible=True)
        if await buttons.count():
            await buttons.first.click(timeout=2000)
            return True
    return False


async def dismiss_browser_dialog(dialog):
    # Native dialogs block page operations, so dismiss them as soon as they fire.
    await dialog.dismiss()


def is_search_page(url: str) -> bool:
    return urlsplit(url).path.lower().endswith("/searchcase/casessearchview.aspx")


async def search_date_with_recovery(page, search_date: str, case_type_id: int | None,
                                    remaining: int | None):
    """Retry the same date if navigation interrupts searching or collection."""
    for attempt in range(1, MAX_SEARCH_ATTEMPTS + 1):
        try:
            if attempt > 1 or not is_search_page(page.url):
                print("Resetting from the homepage and reopening search...", flush=True)
                await open_court_page(page)
            redirected = asyncio.Event()
            last_progress = asyncio.get_running_loop().time()

            def progress():
                nonlocal last_progress
                last_progress = asyncio.get_running_loop().time()

            def on_navigation(frame):
                if frame == page.main_frame and not is_search_page(frame.url):
                    redirected.set()

            async def collect():
                if not is_search_page(page.url):
                    raise RuntimeError("Left the search page before search submission.")
                grid = await search_cases_on_page(page, search_date, case_type_id=case_type_id)
                progress()
                if redirected.is_set() or not is_search_page(page.url):
                    raise RuntimeError("Left the search page before collecting results.")
                cases = await populate_cases(grid, max_cases=remaining, on_progress=progress)
                if redirected.is_set() or not is_search_page(page.url):
                    raise RuntimeError("Left the search page while collecting results.")
                return cases

            page.on("framenavigated", on_navigation)
            work = asyncio.create_task(collect())
            watch = asyncio.create_task(redirected.wait())
            try:
                while not work.done() and not redirected.is_set():
                    wait = max(0, STALL_SECONDS - (asyncio.get_running_loop().time() - last_progress))
                    done, _ = await asyncio.wait(
                        (work, watch), timeout=wait, return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        break
                    print("No progress for 25 seconds; checking popup and search page...", flush=True)
                    dismissed = await dismiss_error_popup(page)
                    # Check the page after attempting to dismiss the popup.
                    if not is_search_page(page.url) or not await page.locator("#caseTypeIDDropDown").is_visible():
                        raise RuntimeError("Search page unavailable after inactivity; reset required.")
                    if not dismissed:
                        raise RuntimeError("Search stalled without a recognizable popup; reset required.")
                    print("Popup dismissed; continuing the current search.", flush=True)
                    progress()
                if redirected.is_set():
                    raise RuntimeError("Site navigated away from the search page.")
                return await work
            finally:
                page.remove_listener("framenavigated", on_navigation)
                for task in (work, watch):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(work, watch, return_exceptions=True)
        except Exception:
            if attempt == MAX_SEARCH_ATTEMPTS:
                raise
            print(
                f"Retrying {search_date} ({attempt + 1}/{MAX_SEARCH_ATTEMPTS})...",
                flush=True,
            )


def save_results(output: Path, result: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)


async def search_range(page, start: date, end: date, case_type_id: int | None,
                       maximum: int | None, output: Path) -> dict:
    """Search each opening date and save summaries without visiting any case."""
    if end < start or (maximum is not None and maximum < 1):
        raise ValueError("An ordered date range and a positive maximum or None are required.")
    result = {
        "start_date": start.strftime("%d/%m/%Y"),
        "end_date": end.strftime("%d/%m/%Y"),
        "case_type_id": case_type_id,
        "maximum_entries": maximum,
        "searched_dates": [],
        "errors": [],
        "cases": [],
    }
    seen = set()
    save_results(output, result)
    await open_court_page(page)
    current = start
    while current <= end and (maximum is None or len(result["cases"]) < maximum):
        search_date = current.strftime("%d/%m/%Y")
        remaining = None if maximum is None else maximum - len(result["cases"])
        limit_message = "no entry limit" if remaining is None else f"room for {remaining} more entries"
        print(f"\nSearching {search_date}; {limit_message}...", flush=True)
        try:
            cases = await search_date_with_recovery(page, search_date, case_type_id, remaining)
            for item in cases:
                key = ("id", item.ID) if item.ID else ("case", item.number, item.court)
                if key in seen:
                    continue
                seen.add(key)
                summary = asdict(item)
                summary.pop("details", None)
                summary["search_date"] = search_date
                result["cases"].append(summary)
                if maximum is not None and len(result["cases"]) >= maximum:
                    break
            result["searched_dates"].append(search_date)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            result["errors"].append({"date": search_date, "error": message})
            print(f"Search failed for {search_date}: {message}", flush=True)
        save_results(output, result)
        if current == end:
            break
        current += timedelta(days=1)
    result["limit_reached"] = maximum is not None and len(result["cases"]) >= maximum
    save_results(output, result)
    print("\nSEARCH RESULTS", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    print(f"\nRecorded {len(result['cases'])} cases. Saved to: {output.resolve()}", flush=True)
    return result


async def main() -> None:
    output = Path(__file__).resolve().parents[1] / "output" / (
        datetime.now().strftime("search_only_%Y%m%d_%H%M%S_%f.json")
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page.on("dialog", dismiss_browser_dialog)
            await search_range(page, START_DATE, END_DATE, CASE_TYPE_ID, MAX_ENTRIES, output)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
