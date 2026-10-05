"""Offline pipeline checks: python -m unittest tests.test_pipeline."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from case import case
from case_details import CASE_TABS
from court_search import populate_cases
from main import run_pipeline


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_continues_after_failure_and_closes_each_page(self):
        cases = [case("", f"{n}-09-26", "", "", "", "", str(n)) for n in range(3)]
        search = MagicMock(close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=search))
        pages = [MagicMock(close=AsyncMock()) for _ in cases]
        order = []

        async def open_case(context, item):
            n = int(item.ID)
            if n:
                pages[n - 1].close.assert_awaited_once()
            order.append(item.number)
            return pages[n]

        async def extract(item, page):
            item.details["tabs"] = {"general_details": {"body": "saved"}}
            if item.ID == "1":
                raise ValueError("sample extraction error")
            item.details["tabs"].update({tab.key: {} for tab in CASE_TABS})
            return item

        with tempfile.TemporaryDirectory() as directory, patch(
            "main.open_results_page", new=AsyncMock()
        ) as search_fn, patch("main.populate_cases", new=AsyncMock(return_value=cases)), patch(
            "main.open_case_folder", side_effect=open_case
        ), patch("main.GetCaseDetails", side_effect=extract):
            output = Path(directory) / "cases.json"
            result = await run_pipeline(context, "06/09/2026", 10071, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved, result)
        self.assertEqual(order, [item.number for item in cases])
        self.assertEqual([r["status"] for r in result["cases"]], ["completed", "failed", "completed"])
        self.assertIn("sample extraction error", result["cases"][1]["error"])
        self.assertEqual(result["cases"][1]["case"]["details"]["tabs"]["general_details"]["body"], "saved")
        search_fn.assert_awaited_once_with(search, "06/09/2026", case_type_id=10071)
        search.close.assert_awaited_once()
        for page in pages:
            page.close.assert_awaited_once()

    async def test_limit_preserves_pending_cases_and_marks_partial(self):
        cases = [case("", str(n), "", "", "", "", str(n)) for n in range(2)]
        context = MagicMock(new_page=AsyncMock(return_value=MagicMock(close=AsyncMock())))
        page = MagicMock(close=AsyncMock())
        with tempfile.TemporaryDirectory() as directory, patch("main.open_results_page", new=AsyncMock()), patch(
            "main.populate_cases", new=AsyncMock(return_value=cases)
        ), patch("main.open_case_folder", new=AsyncMock(return_value=page)) as lookup, patch(
            "main.GetCaseDetails", new=AsyncMock()
        ):
            result = await run_pipeline(context, "06/09/2026", None, Path(directory) / "cases.json", 1)
        self.assertEqual([r["status"] for r in result["cases"]], ["partial", "pending"])
        self.assertEqual(lookup.await_count, 1)

    async def test_search_collection_deduplicates_ids_and_uses_columns(self):
        row = {f"_column_{n}": value for n, value in enumerate(
            ["type", "00100-04-04", "name", "subject", "court", "closed"], 1
        )}
        row["RelatedCaseID"] = "123"
        with patch("court_search.read_grid_rows", new=AsyncMock(return_value=[row, row])):
            result = await populate_cases(MagicMock())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].number, "00100-04-04")
        self.assertEqual(result[0].ID, "123")


if __name__ == "__main__":
    unittest.main()
