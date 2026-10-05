import re
from typing import Any

from playwright.async_api import Locator, expect
from config import ELEMENT_TIMEOUT


async def read_grid_rows(
    grid: Locator, *, timeout: int = ELEMENT_TIMEOUT, max_rows: int | None = None,
    on_progress=None,
) -> list[dict[str, Any]]:
    """Collect grid rows, stopping scrolling and pagination at max_rows."""
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive.")
    current_page = grid.locator('[ref="lbCurrent"]')
    first = grid.locator('[ref="btFirst"]')
    await first.wait_for(state="attached", timeout=timeout)
    if await first.get_attribute("aria-disabled") == "false":
        await first.locator("button").first.click(timeout=timeout)
        await expect(current_page).to_have_text("1", timeout=timeout)

    records = []
    visited_pages = set()
    while True:
        # A visible panel can still be initializing: AG Grid may render cells
        # before replacing the pagination placeholders (page 0 / zero rows).
        await grid.locator(
            '.ag-center-cols-container [role="gridcell"], '
            '.ag-overlay-no-rows-center'
        ).filter(visible=True).first.wait_for(state="visible", timeout=timeout)
        if await grid.locator('.ag-center-cols-container [role="gridcell"]').count():
            for ref in ("lbCurrent", "lbRecordCount", "lbFirstRowOnPage", "lbLastRowOnPage"):
                await expect(grid.locator(f'[ref="{ref}"]')).to_have_text(
                    re.compile(r"^\s*[1-9][\d,]*\s*$"), timeout=timeout,
                )
        page_number = (await current_page.inner_text(timeout=timeout)).strip()
        if page_number in visited_pages:
            raise ValueError(f"Grid repeated page {page_number}.")
        visited_pages.add(page_number)

        async def count(ref: str) -> int:
            text = await grid.locator(f'[ref="{ref}"]').inner_text(timeout=timeout)
            return int(text.replace(",", "").strip())

        total = await count("lbRecordCount")
        first_row = await count("lbFirstRowOnPage")
        last_row = await count("lbLastRowOnPage")
        expected = last_row - first_row + 1 if total else 0
        if expected:
            await grid.locator('.ag-body-viewport').evaluate(
                "viewport => { viewport.scrollTop = 0; }"
            )
            await grid.locator(
                f'.ag-center-cols-container [role="row"][row-index="{first_row - 1}"]'
            ).wait_for(state="attached", timeout=timeout)
        remaining = None if max_rows is None else max_rows - len(records)
        rows = await _read_rendered_rows(grid, max_rows=remaining)
        wanted = expected if remaining is None else min(expected, remaining)
        if len(rows) != wanted:
            raise ValueError(
                f"Grid page {page_number}: expected {wanted} rows, read {len(rows)}."
            )
        records.extend(rows)
        if on_progress is not None:
            on_progress()
        if max_rows is not None and len(records) >= max_rows:
            return records

        next_button = grid.locator('[ref="btNext"]')
        if await next_button.get_attribute("aria-disabled") == "true":
            if len(records) != total:
                raise ValueError(f"Expected {total} rows, read {len(records)}.")
            return records
        await next_button.locator("button").first.click(timeout=timeout)
        await expect(current_page).not_to_have_text(page_number, timeout=timeout)


async def _read_rendered_rows(
    grid: Locator, *, max_rows: int | None = None,
) -> list[dict[str, str]]:
    """Merge cells by row index while scrolling, avoiding pinned-row duplicates."""
    return await grid.evaluate("""async (grid, limit) => {
        const vertical = grid.querySelector('.ag-body-viewport');
        const horizontal = grid.querySelector('.ag-body-horizontal-scroll-viewport');
        if (!vertical) throw new Error('Missing grid viewport');
        const originalTop = vertical.scrollTop;
        const originalLeft = horizontal ? horizontal.scrollLeft : 0;
        const rows = new Map();
        const frame = () => new Promise(resolve => requestAnimationFrame(
            () => requestAnimationFrame(resolve)));
        const positions = (max, size) => {
            const values = [0];
            for (let n = Math.max(1, size / 2); n < max; n += Math.max(1, size / 2))
                values.push(n);
            if (max > 0) values.push(max);
            return values;
        };
        try {
            const ys = positions(vertical.scrollHeight - vertical.clientHeight,
                                 vertical.clientHeight);
            const xs = horizontal ? positions(
                horizontal.scrollWidth - horizontal.clientWidth,
                horizontal.clientWidth) : [0];
            for (const y of ys) {
                vertical.scrollTop = y;
                // Negative offsets cover RTL grids; positive offsets cover LTR.
                for (const x of [...xs, ...xs.map(x => -x)]) {
                    if (horizontal) horizontal.scrollLeft = x;
                    await frame();
                    for (const row of grid.querySelectorAll(
                        '.ag-body-viewport [role="row"][row-index]')) {
                        const cells = row.querySelectorAll('[role="gridcell"][col-id]');
                        if (!cells.length) continue;
                        const index = Number(row.getAttribute('row-index'));
                        if (limit !== null && rows.size >= limit && !rows.has(index)) continue;
                        const data = rows.get(index) || {};
                        for (const cell of cells) {
                            data[cell.getAttribute('col-id')] = cell.innerText.trim();
                            const column = cell.getAttribute('aria-colindex');
                            if (column) data['_column_' + column] = cell.innerText.trim();
                        }
                        const details = row.querySelector('a[href*=":btnDetails"]');
                        if (details) {
                            const match = details.getAttribute('href').match(/,\s*["'](\d+)["']\)/);
                            if (match) data.DetailsID = match[1];
                        }
                        const relatedCase = row.querySelector(
                            '[col-id="CaseDisplayIdentifier"] a[href], [aria-colindex="2"] a[href*=":btnCase"]');
                        if (relatedCase) {
                            const match = relatedCase.getAttribute('href').match(/,\s*["'](\d+)["']\)/);
                            if (match) data.RelatedCaseID = match[1];
                        }
                        rows.set(index, data);
                    }
                }
                if (limit !== null && rows.size >= limit) break;
            }
            return [...rows].sort((a, b) => a[0] - b[0]).map(entry => entry[1]);
        } finally {
            vertical.scrollTop = originalTop;
            if (horizontal) horizontal.scrollLeft = originalLeft;
            await frame();
        }
    }""", max_rows)

