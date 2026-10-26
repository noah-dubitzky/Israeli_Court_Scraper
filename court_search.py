from __future__ import annotations

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, expect

from case import case
from grid_reader import read_grid_rows
from config import (
    ELEMENT_TIMEOUT,
    HOME_URL,
    PAGE_TIMEOUT,
)


async def open_court_page(
    page: Page, *, disable_timeouts: bool = False,
) -> None:
    """Open the homepage and navigate through the menu to the date-search page."""

    print("Opening court website...")

    await page.goto(
        HOME_URL,
        wait_until="domcontentloaded",
        timeout=0 if disable_timeouts else PAGE_TIMEOUT,
    )

    print("Initial URL:", page.url)
    print("Title:", await page.title())

    await navigate_to_date_search(page, disable_timeouts=disable_timeouts)


async def navigate_to_date_search(
    page: Page, *, disable_timeouts: bool = False,
) -> None:
    """Open the date-search menu on the current page, without visiting home."""
    # STEP 1 — HANDLE MODAL
    await _dismiss_optional_modal(page, disable_timeouts=disable_timeouts)

    await page.wait_for_load_state(
        "domcontentloaded",
        timeout=0 if disable_timeouts else PAGE_TIMEOUT,
    )

    await page.wait_for_timeout(2000)


    # STEP 2 — OPEN CASE SEARCH MENU
    print("\nFinding case-search menu...")

    menu_container = page.locator(
        "#Header1_UpperMenu1_tdSearchCase"
    )

    await menu_container.wait_for(
        state="visible",
        timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
    )

    dropdown_button = menu_container.locator(
        "button.dropdown-toggle"
    )

    await dropdown_button.click()

    await page.wait_for_timeout(500)


    # STEP 3 — OPEN DATE SEARCH
    case_date = page.locator(
        "#Header1_UpperMenu1_btnCaseDate"
    )

    await case_date.wait_for(
        state="visible",
        timeout=0 if disable_timeouts else 10000,
    )

    await case_date.click()

    # STEP 4 — WAIT FOR SEARCH PAGE
    await page.wait_for_load_state(
        "domcontentloaded",
        timeout=0 if disable_timeouts else PAGE_TIMEOUT,
    )

    await page.wait_for_timeout(3000)

    print("\nSEARCH PAGE")
    print("URL:", page.url)
    print("TITLE:", await page.title())


async def _dismiss_optional_modal(
    page: Page, *, disable_timeouts: bool = False,
) -> None:
    """Allow a briefly delayed modal, but continue when the session suppresses it."""
    confirm = page.locator("#btUploadDocumentsConfirm")
    try:
        # This is an optional-presence check, even when action timeouts are off.
        # An unlimited wait here would hang every visit with a saved session.
        await confirm.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        print("No confirmation modal; continuing with the current session.")
        return
    print("Confirmation modal found; dismissing...")
    await confirm.click(timeout=0 if disable_timeouts else ELEMENT_TIMEOUT)
    await confirm.wait_for(
        state="hidden", timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
    )


async def open_results_page(
    page: Page,
    new_date: str,
    case_type_id: int | None = None,
) -> Locator:
    """
    Open the court search page, search by opening date,
    optionally filter by an option value in caseTypeIDDropDown, and return
    the results grid. Omitting case_type_id preserves the default search.
    """

    if case_type_id is not None and type(case_type_id) is not int:
        raise TypeError("case_type_id must be an integer or None.")

    await open_court_page(page)
    return await search_cases_on_page(page, new_date, case_type_id)


async def search_cases_on_page(
    page: Page,
    new_date: str,
    case_type_id: int | None = None,
) -> Locator:
    """Search a new date on the existing search page without visiting home."""
    if case_type_id is not None and type(case_type_id) is not int:
        raise TypeError("case_type_id must be an integer or None.")

    # STEP 5 — ENTER DATE
    date_input = page.locator(
        "#openDateCalendar"
    )

    for attempt in range(2):
        try:
            await date_input.wait_for(state="visible", timeout=10000)
            break
        except PlaywrightTimeoutError:
            print("Date input missing after 10 seconds; returning home.")
            await open_court_page(page)
            if attempt == 1:
                raise

    if case_type_id is not None:
        await _select_case_type(page, case_type_id)

    print("Searching date:", new_date)

    await date_input.click()
    await date_input.press("Control+A")

    await date_input.press_sequentially(
        new_date,
        delay=50,
    )

    # STEP 6 — SUBMIT SEARCH
    search_button = page.locator(
        "#buttonsGroup_searchButton"
    )

    await search_button.wait_for(
        state="visible",
        timeout=ELEMENT_TIMEOUT,
    )

    print("Submitting search...")

    await search_button.click()

    # STEP 7 — WAIT FOR RESULTS
    await page.wait_for_load_state(
        "domcontentloaded",
        timeout=PAGE_TIMEOUT,
    )

    await page.wait_for_timeout(5000)

    # STEP 8 — FIND GRID
    results_grid = page.locator(
        "#CaseSearchResultsGrid"
    )

    await results_grid.wait_for(
        state="visible",
        timeout=ELEMENT_TIMEOUT,
    )

    print("Results grid found.")

    return results_grid


async def _select_case_type(page: Page, case_type_id: int) -> None:
    """Select by option value and finish the onchange postback before typing dates."""
    dropdown = page.locator("#caseTypeIDDropDown")
    await dropdown.wait_for(state="visible", timeout=ELEMENT_TIMEOUT)
    value = str(case_type_id)
    if not await dropdown.locator(f'option[value="{value}"]').count():
        raise ValueError(f"No case-type option has value {case_type_id}.")
    if await dropdown.input_value() != value:
        # The supplied onchange handler schedules __doPostBack(...).
        async with page.expect_event("domcontentloaded", timeout=PAGE_TIMEOUT):
            await dropdown.select_option(value=value, timeout=ELEMENT_TIMEOUT)
    await expect(page.locator("#caseTypeIDDropDown")).to_have_value(
        value, timeout=ELEMENT_TIMEOUT,
    )


async def populate_cases(results_grid: Locator, max_cases: int | None = None, *, on_progress=None) -> list[case]:
    """Collect at most max_cases search rows, then deduplicate cases."""
    rows = await read_grid_rows(results_grid, max_rows=max_cases, on_progress=on_progress)
    results = []
    seen = set()
    fields = ("CaseTypeShortName", "CaseDisplayIdentifier", "CaseName",
              "CaseInterestName", "CourtName", "CaseStatusName")
    for row in rows:
        values = [row.get(field, row.get(f"_column_{index}"))
                  for index, field in enumerate(fields, start=1)]
        if any(value is None for value in values) or not values[1]:
            raise ValueError(f"Incomplete search result row: {row!r}")
        internal_id = row.get("RelatedCaseID", "")
        key = ("id", internal_id) if internal_id else ("case", values[1], values[4])
        if key in seen:
            continue
        seen.add(key)
        results.append(case(*values, ID=internal_id))
    print(f"Collected {len(results)} unique cases from {len(rows)} result rows.")
    return results
