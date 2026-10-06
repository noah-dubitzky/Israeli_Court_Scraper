import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Average_Consumption_Per_Case_Finder import load_cases
from Collect_Case_Test_Input import choose_date, collect_cases
from case import case


class InputCollectorTests(unittest.IsolatedAsyncioTestCase):
    def test_random_date_is_reproducible_and_within_range(self):
        for today in (date(2026, 10, 5), date(2024, 2, 29)):
            selected = choose_date(today, 42)
            self.assertEqual(selected, choose_date(today, 42))
            self.assertLess(selected, today)
            self.assertGreaterEqual(selected, date(today.year - 10, today.month,
                                                   min(today.day, 28)))

    async def test_retries_same_date_and_writes_consumption_compatible_records(self):
        page = MagicMock(close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=page))
        items = [case("type", "123-09-26", "name", "interest", "court", "status", "456")]
        with tempfile.TemporaryDirectory() as directory, patch(
            "Collect_Case_Test_Input.open_results_page", new=AsyncMock(
                side_effect=[RuntimeError("redirect"), MagicMock()])
        ) as search, patch(
            "Collect_Case_Test_Input.populate_cases", new=AsyncMock(return_value=items)
        ) as collect:
            output = Path(directory) / "Case_Test_Output.json"
            result = await collect_cases(context, date(2026, 9, 6), output)
            loaded = load_cases(output)
        self.assertEqual(result["total_cases"], 1)
        self.assertNotIn("details", result["cases"][0])
        self.assertEqual(loaded[0], items[0])
        self.assertEqual([call.args[1] for call in search.await_args_list],
                         ["06/09/2026", "06/09/2026"])
        self.assertNotIn("max_cases", collect.await_args.kwargs)
        page.close.assert_awaited_once()

    async def test_failed_collection_preserves_existing_input(self):
        page = MagicMock(close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=page))
        with tempfile.TemporaryDirectory() as directory, patch(
            "Collect_Case_Test_Input.open_results_page", new=AsyncMock(side_effect=RuntimeError("offline"))
        ):
            output = Path(directory) / "Case_Test_Output.json"
            output.write_text("previous input", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                await collect_cases(context, date(2026, 9, 6), output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous input")
        page.close.assert_awaited_once()
