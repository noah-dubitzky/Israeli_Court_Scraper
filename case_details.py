import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from case import case
from config import (
    ELEMENT_TIMEOUT,
    PAGE_TIMEOUT,
)
from court_search import open_court_page
from grid_reader import read_grid_rows as _read_paginated_grid


@dataclass(frozen=True)
class CaseTab:
    """A known folder ID and whether it belongs to the Factors group."""

    key: str
    folder_id: str
    nested: bool = False

    @property
    def selector(self) -> str:
        # ASP.NET changes the naming-container prefix between pages.
        # Match the stable control suffix and exact folder argument instead.
        return (
            '#browser a[href*="ElectronicCaseFolderTreeView1$NavigateToFolder"]'
            f'[href$="\',\'{self.folder_id}\')"]'
        )


CASE_TABS: tuple[CaseTab, ...] = (
    CaseTab("general_details", "1"),
    CaseTab("sides", "4", nested=True),
    CaseTab("power_of_attorney", "5", nested=True),
    CaseTab("discussion_dates", "10"),
    CaseTab("decisions", "18"),
    CaseTab("judgments", "21"),
    CaseTab("related_cases", "24"),
)


async def GetCaseDetails(
    selected_case: case,
    page: Page,
    *,
    disable_timeouts: bool = False,
) -> case:
    """Collect each tab's body into details and return the supplied case.

    Pass the page returned by open_case_folder. The caller owns the page
    and browser lifecycle. Only tabs with implemented body extractors are
    collected; other tabs are added as their markup becomes available.

    Intended usage:
        selected_case = await GetCaseDetails(selected_case, detail_page)
    """

    tab_details = selected_case.details.setdefault("tabs", {})

    for tab in CASE_TABS:
        if not await open_case_tab(page, tab, disable_timeouts=disable_timeouts):
            continue
        tab_details[tab.key] = {
            "href": await page.locator(tab.selector).get_attribute("href"),
            "body": await _extract_tab_body(
                page, tab, timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
            ),
        }

    # Preserve completed tabs even if a later tab fails.
    selected_case.details["tabs"] = tab_details
    return selected_case


async def open_case_tab(
    page: Page, tab: CaseTab, *, disable_timeouts: bool = False,
) -> bool:
    """Return False if the tab cannot be revealed within three seconds.

    Activation failures still propagate; only visibility timeouts skip tabs.
    """
    timeout = 0 if disable_timeouts else ELEMENT_TIMEOUT

    async def reveal_tab() -> None:
        if tab.nested:
            await _expand_tab_parent(page, tab, timeout=timeout)
        await page.locator(tab.selector).wait_for(
            state="visible", timeout=0 if disable_timeouts else 3000,
        )

    try:
        await asyncio.wait_for(reveal_tab(), timeout=None if disable_timeouts else 3)
    except (asyncio.TimeoutError, PlaywrightTimeoutError):
        print(f"SKIP: {tab.key} was not visible within 3 seconds.", flush=True)
        return False
    await _activate_case_tab(page, tab, timeout=timeout)
    return True


async def _expand_tab_parent(
    page: Page, tab: CaseTab, *, timeout: int = ELEMENT_TIMEOUT,
) -> None:
    """Reveal a nested link without closing an already expanded group."""
    link = page.locator(tab.selector)
    await link.wait_for(state="attached", timeout=timeout)
    if not await link.is_visible():
        parent = link.locator("xpath=ancestor::li[ul][1]")
        await parent.locator(":scope > div.hitarea").click(
            timeout=timeout,
        )
    await link.wait_for(state="visible", timeout=timeout)


async def _activate_case_tab(
    page: Page, tab: CaseTab, *, timeout: int = ELEMENT_TIMEOUT,
) -> None:
    """Wait for selection after either a full or partial page update."""
    link = page.locator(tab.selector)
    await link.wait_for(state="visible", timeout=timeout)
    await link.click(timeout=timeout)
    await expect(
        page.locator(tab.selector).locator(".chosen_folder")
    ).to_have_count(1, timeout=timeout)


async def _extract_tab_body(
    page: Page, tab: CaseTab, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Extract the active tab using its known body structure."""
    if tab.folder_id == "1":
        return await _extract_general_details(page, timeout=timeout)
    if tab.folder_id == "4":
        return await _extract_sides(page, timeout=timeout)
    if tab.folder_id == "5":
        return await _extract_representatives(page, timeout=timeout)
    if tab.folder_id == "10":
        return await _extract_discussion_dates(page, timeout=timeout)
    if tab.folder_id == "18":
        return await _extract_decisions(page, timeout=timeout)
    if tab.folder_id == "21":
        return await _extract_judgments(page, timeout=timeout)
    if tab.folder_id == "24":
        return await _extract_related_cases(page, timeout=timeout)
    raise NotImplementedError(f"Body extraction is not implemented for {tab.key}.")


def _parse_general_details(value: str) -> list[dict[str, Any]]:
    """Decode the grid's backing data, preserving nulls and additional fields."""
    records = json.loads(value)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("CaseDetailsGridArrayStore must contain a list of objects.")

    fields = {
        "CaseDisplay": "case_title",
        "PleaDisplay": "filing_description",
        "PrivilegeDisplay": "access_status",
        "ClaimAmount": "claim_amount",
        "CaseStatusDisplay": "case_status",
        "PleaID": "filing_id",
    }
    return [
        {
            **{target: record.get(source) for source, target in fields.items()},
            "source_fields": record,
        }
        for record in records
    ]


async def _extract_general_details(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Read backing JSON rather than only the grid's rendered/visible rows."""
    store = page.locator("#CaseDetailsGridArrayStore")
    await store.wait_for(state="attached", timeout=timeout)
    # input_value already decodes HTML entities; do not unescape JSON again.
    records = _parse_general_details(await store.input_value())
    links = page.locator('#CaseDetailsGrid [col-id="Details"] a[href]')
    details_links = []
    for link in await links.all():
        details_links.append({
            "href": await link.get_attribute("href"),
            "label": await link.get_attribute("alt") or (await link.inner_text()).strip(),
        })
    return {"records": records, "details_links": details_links}


def _parse_sides(value: str) -> list[dict[str, Any]]:
    """Decode party records without interpreting undocumented status codes."""
    records = json.loads(value)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("CasePartiesGridArrayStore must contain a list of objects.")

    fields = {
        "RoleName": "role",
        "FullName": "full_name",
        "PartyPropertyName": "party_characteristic",
        "RepresentatedOrRepresentativesNames": "representative_names",
        "VerdictOrSentence": "judgment_result",
        "ProceedingType": "proceeding_type",
        "ActivityStatusID": "activity_status_id",
        "CasePartyID": "case_party_id",
    }
    return [
        {
            **{target: record.get(source) for source, target in fields.items()},
            "source_fields": record,
        }
        for record in records
    ]


async def _extract_sides(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Read parties as currently displayed; leave the deleted-party filter alone."""
    store = page.locator("#CasePartiesGridArrayStore")
    await store.wait_for(state="attached", timeout=timeout)
    records = _parse_sides(await store.input_value(timeout=timeout))
    links = page.locator('#CasePartiesGrid [col-id="Details"] a[href]')
    details_links = []
    for link in await links.all():
        details_links.append({
            "href": await link.get_attribute("href", timeout=timeout),
            "label": await link.get_attribute("alt", timeout=timeout)
            or (await link.inner_text(timeout=timeout)).strip(),
        })
    return {"records": records, "details_links": details_links}


def _parse_representatives(value: str) -> list[dict[str, Any]]:
    """Decode representatives, preserving source values and status codes."""
    records = json.loads(value)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("CaseRepresentativeGridArrayStore must contain a list of objects.")
    fields = {
        "RoleName": "role",
        "FullName": "full_name",
        "ProceedingType": "proceeding_type",
        "ActivityStatusID": "activity_status_id",
        "CasePartyID": "case_party_id",
    }
    return [
        {
            **{target: record.get(source) for source, target in fields.items()},
            "source_fields": record,
        }
        for record in records
    ]


async def _extract_representatives(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Read representatives without changing the deleted-representative checkbox."""
    store = page.locator("#CaseRepresentativeGridArrayStore")
    await store.wait_for(state="attached", timeout=timeout)
    records = _parse_representatives(await store.input_value(timeout=timeout))
    links = page.locator('#CaseRepresentativeGrid [col-id="Details"] a[href]')
    details_links = []
    for link in await links.all():
        details_links.append({
            "href": await link.get_attribute("href", timeout=timeout),
            "label": await link.get_attribute("alt", timeout=timeout)
            or (await link.inner_text(timeout=timeout)).strip(),
        })
    return {"records": records, "details_links": details_links}


def _parse_decisions(value: str) -> list[dict[str, Any]]:
    """Read decision summaries; document identifiers are metadata only."""
    records = json.loads(value)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("DecisionListGridArrayStore must contain a list of objects.")
    fields = {
        "DecisionDisplayName": "description",
        "DecisionSignatureDate": "signed_at",
        "DecisionSignatureUserName": "signed_by",
        "DecisionID": "decision_id",
        "DocumentID": "document_id",
        "IsIDCPublished": "is_idc_published",
        "SummaryVersionDocumentID": "summary_document_id",
        "IsIDCPublishedForSummary": "is_summary_idc_published",
        "IsCanceledDecision": "is_canceled",
    }
    return [
        {
            **{target: record.get(source) for source, target in fields.items()},
            "source_fields": record,
        }
        for record in records
    ]


async def _extract_decision_summaries(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Snapshot row data before opening Details changes the page."""
    store = page.locator("#DecisionListGridArrayStore")
    await store.wait_for(state="attached", timeout=timeout)
    return _parse_decisions(await store.input_value(timeout=timeout))


async def _wait_for_decision_rows(grid: Locator, *, timeout: int) -> None:
    """Wait for the nonempty decision grid to finish its initial rendering."""
    await grid.locator('.ag-body-viewport').wait_for(state="visible", timeout=timeout)
    await grid.locator('a[href*=":btnDetails"]').first.wait_for(
        state="attached", timeout=timeout,
    )
    # The backing data contains a decision, so zero is an initialization value.
    await expect(grid.locator('[ref="lbCurrent"]')).to_have_text(
        re.compile(r"^\s*[1-9][\d,]*\s*$"), timeout=timeout,
    )
    await grid.locator('[ref="btNext"]').wait_for(state="attached", timeout=timeout)


async def _click_decision_details(
    page: Page, decision_id: int, *, timeout: int = ELEMENT_TIMEOUT,
    grid_selector: str = "#DecisionListGrid",
) -> None:
    """Locate a decision across grid pages and click only its Details link."""
    if type(decision_id) is not int:
        raise ValueError("A numeric DecisionID is required.")
    link = page.locator(
        f'{grid_selector} a[href*=":btnDetails"]'
        f"[href$=',\"{decision_id}\")']"
    )
    grid = page.locator(grid_selector)
    await grid.wait_for(state="visible", timeout=timeout)
    await _wait_for_decision_rows(grid, timeout=timeout)
    first = grid.locator('[ref="btFirst"]')
    if await first.count() and await first.get_attribute("aria-disabled") == "false":
        await first.locator("button").first.click(timeout=timeout)
        await expect(grid.locator('[ref="lbCurrent"]')).to_have_text("1", timeout=timeout)
    while True:
        await _wait_for_decision_rows(grid, timeout=timeout)
        # Scan the vertical viewport so virtualized rows can be located by ID.
        found = await grid.evaluate("""async (grid, id) => {
            const viewport = grid.querySelector('.ag-body-viewport');
            if (!viewport) throw new Error('Missing decision grid viewport');
            const frame = () => new Promise(resolve => requestAnimationFrame(
                () => requestAnimationFrame(resolve)));
            const end = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
            const step = Math.max(1, viewport.clientHeight / 2);
            for (let y = 0; ; y = Math.min(end, y + step)) {
                viewport.scrollTop = y;
                await frame();
                if ([...grid.querySelectorAll('a[href]')].some(a =>
                    a.getAttribute('href').includes(':btnDetails') &&
                    a.getAttribute('href').endsWith(',"' + id + '")')))
                    return true;
                if (y === end) return false;
            }
        }""", decision_id)
        if found:
            await link.click(timeout=timeout)
            return
        next_button = grid.locator('[ref="btNext"]')
        if not await next_button.count() or await next_button.get_attribute("aria-disabled") == "true":
            raise ValueError(f"Details link not found for decision {decision_id}.")
        current = grid.locator('[ref="lbCurrent"]')
        old_page = await current.inner_text(timeout=timeout)
        await next_button.locator("button").first.click(timeout=timeout)
        await expect(current).not_to_have_text(old_page, timeout=timeout)


async def _extract_decision_details(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Read the Details form using stable ID suffixes, regardless of _ctl prefix."""
    area = page.locator('.CentralDisplayArea').filter(
        has=page.locator('span[id$="_lblDocumentName"]')
    )
    await area.locator('span[id$="_lblDocumentName"]').wait_for(
        state="visible", timeout=timeout,
    )
    details = {}
    for key, suffix in {
        "decision_name": "lblHeader",
        "document_name": "lblDocumentName",
    }.items():
        details[key] = (await area.locator(
            f'span[id$="_{suffix}"]'
        ).inner_text(timeout=timeout)).strip()
    for key, suffix in {
        "given_by": "tbGivenBy",
        "signature_date": "tbDateOfSign",
        "description": "tbDecisionDescription",
        "confidentiality": "tbConfidential",
        "decision_type": "tbDecisionType",
    }.items():
        details[key] = await area.locator(
            f'input[id$="_{suffix}"]'
        ).input_value(timeout=timeout)
    for key, suffix in {
        "given_ex_parte": "cbOneSide",
        "release_to_other_side": "cbOpenSecondSide",
        "show_in_selected_decisions": "cbChosenDecision",
        "is_substantive": "rbCriticalDesicion",
        "is_technical": "rbTechnicalDesicion",
    }.items():
        details[key] = await area.locator(
            f'input[id$="_{suffix}"]'
        ).is_checked(timeout=timeout)
    # Related-document buttons are not evidence of a cancellation or appeal.
    # Do not follow them or infer relationships from their presence.
    return details


async def _extract_decisions(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    records = await _extract_decision_summaries(page, timeout=timeout)
    for record in records:
        print(f"Opening Details for decision {record['decision_id']}...", flush=True)
        await _click_decision_details(page, record["decision_id"], timeout=timeout)
        record["details"] = await _extract_decision_details(page, timeout=timeout)
        await _return_to_decisions_list(page, timeout=timeout)
    return {"records": records}


async def _return_to_decisions_list(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> None:
    """Click the right-hand Decisions folder and wait for the rows display."""
    print("Returning to the rows through the Decisions tab...", flush=True)
    tab = next(tab for tab in CASE_TABS if tab.folder_id == "18")
    await page.locator(tab.selector).click(timeout=timeout)
    # The folder can already be marked selected while its Details form is open.
    # Wait for the destination content instead of relying on that marker.
    await page.locator('span[id$="_lblDocumentName"]').wait_for(
        state="hidden", timeout=timeout,
    )
    await page.locator("#DecisionListGrid").wait_for(state="visible", timeout=timeout)
    await page.locator("#DecisionListGridArrayStore").wait_for(
        state="attached", timeout=timeout,
    )
    await page.locator('#DecisionListGrid a[href*=":btnDetails"]').first.wait_for(
        state="visible", timeout=timeout,
    )


async def _extract_related_cases(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Read related-case rows without navigating to the linked cases."""
    grid = page.locator(
        '.ag-root-wrapper:has([col-id="CaseDisplayIdentifier"]):visible'
    )
    await grid.wait_for(state="visible", timeout=timeout)
    rows = await _read_paginated_grid(grid, timeout=timeout)
    fields = {
        "CaseTypeShortName": "case_type",
        "CaseDisplayIdentifier": "case_number",
        "CaseName": "case_name",
        "CaseInterestName": "case_interest",
        "CourtName": "court",
        "CaseStatusName": "status",
        "CaseLinkTypeName": "relationship",
        "RelatedCaseID": "case_id",
    }
    return {"records": [
        {
            **{target: row.get(source) for source, target in fields.items()},
            "source_fields": row,
        }
        for row in rows
    ]}


JUDGMENTS_GRID = '.ag-root-wrapper:has([col-id="DecisionDisplayName"]):visible'


async def _extract_judgments(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Snapshot every judgment row, then visit its Details and return via folder 21."""
    grid = page.locator(JUDGMENTS_GRID)
    await grid.wait_for(state="visible", timeout=timeout)
    rows = await _read_paginated_grid(grid, timeout=timeout)
    records = []
    for row in rows:
        if not row.get("DetailsID"):
            raise ValueError("Judgment row is missing its Details identifier.")
        records.append({
            "decision_id": int(row["DetailsID"]),
            "description": row.get("DecisionDisplayName"),
            "signed_at": row.get("DecisionSignatureDate"),
            "signed_by": row.get("DecisionSignatureUserName"),
            "source_fields": row,
        })
    tab = next(tab for tab in CASE_TABS if tab.folder_id == "21")
    for record in records:
        print(f"Opening judgment Details for {record['decision_id']}...", flush=True)
        await _click_decision_details(
            page, record["decision_id"], timeout=timeout, grid_selector=JUDGMENTS_GRID,
        )
        record["details"] = await _extract_decision_details(page, timeout=timeout)
        await page.locator(tab.selector).click(timeout=timeout)
        await page.locator('span[id$="_lblDocumentName"]').wait_for(
            state="hidden", timeout=timeout,
        )
        await _wait_for_decision_rows(page.locator(JUDGMENTS_GRID), timeout=timeout)
    return {"records": records}


SITTING_FIELDS = {
    "MeetingDate": "meeting_date",
    "StartTime": "start_time",
    "FinishTime": "finish_time",
    "SittingTypeName": "hearing_type",
    "PleaMotionNumber": "motion_number",
    "SittingActivityStatusName": "hearing_status",
    "IsProtocolExist": "protocol_exists",
    "UserList": "judges",
}


async def _extract_discussion_dates(
    page: Page, *, timeout: int = ELEMENT_TIMEOUT,
) -> dict[str, Any]:
    """Click both hearing subtabs and collect their grids independently."""
    result = {}
    for key, panel_id in (
        ("all_hearings", "PresentAllSittings"),
        ("current_hearings", "PresentUpToDateSittings"),
    ):
        await page.locator(f'#tabs a[href="#{panel_id}"]').click(timeout=timeout)
        panel = page.locator(f"#{panel_id}")
        await panel.wait_for(state="visible", timeout=timeout)
        await expect(
            page.locator(f'#tabs [role="tab"][aria-controls="{panel_id}"]')
        ).to_have_attribute("aria-selected", "true", timeout=timeout)
        grid = panel.locator(f"#{panel_id}Grid")
        await grid.wait_for(state="visible", timeout=timeout)
        result[key] = {"records": await _read_sittings_grid(grid, timeout=timeout)}
    return result


async def _read_sittings_grid(
    grid: Locator, *, timeout: int = ELEMENT_TIMEOUT,
) -> list[dict[str, Any]]:
    rows = await _read_paginated_grid(grid, timeout=timeout)
    return [
        {
            **{target: row.get(source) for source, target in SITTING_FIELDS.items()},
            "source_fields": row,
        }
        for row in rows
    ]



def split_case_number(
    full_case_number: str,
) -> tuple[str, str]:
    """
    Convert:

        10195-09-26

    into:

        10195
        09-26
    """

    value = full_case_number.strip()

    parts = value.split("-", 1)

    if len(parts) != 2:
        raise ValueError(
            "Unexpected case number format: "
            f"{full_case_number}"
        )

    case_number = parts[0].strip()
    month_year = parts[1].strip()

    if not case_number:
        raise ValueError(
            f"Missing case number: {full_case_number}"
        )

    if not month_year:
        raise ValueError(
            f"Missing month/year: {full_case_number}"
        )

    return case_number, month_year


async def open_case_folder(
    context: BrowserContext,
    selected_case: case,
    *,
    disable_timeouts: bool = False,
) -> Page:
    """
    Navigate from the homepage to the date-search page and locate a case
    using selected_case.number.

    Example:

        10195-09-26

    becomes:

        Case number: 10195
        Month/year:  09-26
    """

    page = await context.new_page()

    try:
        print(
            "\nOpening case details for:",
            selected_case.number,
        )

        await open_court_page(page, disable_timeouts=disable_timeouts)
        print("URL after opening:", page.url)

        case_number, month_year = (
            split_case_number(
                selected_case.number
            )
        )

        print("Case number:", case_number)
        print("Month/year:", month_year)

        case_number_input = page.locator(
            "#header_"
            "CaseLocatorHeaderUC2_"
            "BamaCaseNumberTextBoxHT"
        )

        month_year_input = page.locator(
            "#header_"
            "CaseLocatorHeaderUC2_"
            "BamaMonthYearTextBoxHT"
        )

        search_button = page.locator(
            "#header_"
            "CaseLocatorHeaderUC2_"
            "SearchHeaderCaseButton"
        )

        await case_number_input.wait_for(
            state="visible",
            timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
        )

        await month_year_input.wait_for(
            state="visible",
            timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
        )

        await search_button.wait_for(
            state="visible",
            timeout=0 if disable_timeouts else ELEMENT_TIMEOUT,
        )

        await case_number_input.fill(
            case_number
        )

        await month_year_input.fill(
            month_year
        )

        print("Submitting case lookup...")

        async with page.expect_event(
            "domcontentloaded",
            timeout=0 if disable_timeouts else PAGE_TIMEOUT,
        ):
            await search_button.click()

        print("Case lookup completed.")
        print("URL:", page.url)
        print("Title:", await page.title())

        return page

    except BaseException:
        print("URL when lookup failed:", page.url)
        await page.close()
        raise
