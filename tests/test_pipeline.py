"""Offline pipeline checks: python -m unittest tests.test_pipeline."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from case import case
from case_details import CaseLookupError
from court_search import populate_cases
from main import load_checkpoint, run_pipeline, save_checkpoint


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_skips_completed_and_retries_every_unfinished_status(self):
        statuses = ["completed", "pending", "in_progress", "failed", "partial"]
        entries = []
        for n, status in enumerate(statuses):
            item = case("", str(n), "", "", "", "", str(n))
            item.details = {"tabs": {"sides": {"body": "old"}}} if n == 0 else {"tabs": {"general_details": {}}}
            from dataclasses import asdict
            entries.append({"status": status, "error": "old error", "case": asdict(item)})
        run = {"started_at": "original", "search_date": "06/09/2026", "case_type_id": None,
               "finished_at": "old", "cases": entries}
        context = MagicMock(new_page=AsyncMock())
        page = MagicMock(close=AsyncMock())

        async def extract(item, page, *, tabs):
            item.details["tabs"]["sides"] = {"body": "new"}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cases.json"
            save_checkpoint(output, run)
            checkpoint = load_checkpoint(output)
            with patch("main.open_results_page", new=AsyncMock()) as search, patch(
                "main.open_case_folder", new=AsyncMock(return_value=page)
            ) as lookup, patch("main.GetCaseDetails", side_effect=extract):
                result = await run_pipeline(context, "06/09/2026", None, output, checkpoint=checkpoint)
            self.assertEqual([call.args[1].ID for call in lookup.await_args_list], ["1", "2", "3", "4"])
            search.assert_not_awaited()
            context.new_page.assert_not_awaited()
            self.assertEqual(result["cases"][0], entries[0])
            self.assertTrue(all(entry["status"] == "completed" for entry in result["cases"]))
            self.assertTrue(all(entry["error"] is None for entry in result["cases"][1:]))
            self.assertEqual(load_checkpoint(output), result)
        page.close.assert_awaited_once()

    def test_checkpoint_retries_temporary_permission_error(self):
        original_replace = Path.replace
        attempts = []

        def locked_once(source, target):
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError("temporarily locked")
            return original_replace(source, target)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cases.json"
            output.write_text('{"old": true}', encoding="utf-8")
            with patch.object(Path, "replace", new=locked_once), patch("main.sleep"):
                save_checkpoint(output, {"new": True})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"new": True})
            self.assertEqual(len(attempts), 2)

    def test_checkpoint_preserves_old_file_when_lock_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cases.json"
            output.write_text('{"old": true}', encoding="utf-8")
            with patch.object(Path, "replace", side_effect=PermissionError("locked")) as replace, patch("main.sleep"):
                with self.assertRaises(PermissionError):
                    save_checkpoint(output, {"new": True})
            self.assertEqual(replace.call_count, 6)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(json.loads(output.with_name("cases.json.tmp").read_text(encoding="utf-8")), {"new": True})

    async def test_reuses_page_and_continues_after_extraction_failure(self):
        cases = [case("", f"{n}-09-26", "", "", "", "", str(n)) for n in range(3)]
        search = MagicMock(close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=search))
        detail = MagicMock(close=AsyncMock())
        order = []

        async def open_case(context, item, *, page=None):
            n = int(item.ID)
            self.assertIs(page, detail if n else None)
            detail.close.assert_not_awaited()
            order.append(item.number)
            return detail

        async def extract(item, page, *, tabs):
            self.assertEqual([tab.key for tab in tabs], ["sides"])
            self.assertTrue(tabs[0].nested)
            item.details["tabs"] = {"sides": {"body": "saved"}}
            if item.ID == "1":
                raise ValueError("sample extraction error")
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
        self.assertEqual(result["cases"][1]["case"]["details"]["tabs"]["sides"]["body"], "saved")
        search_fn.assert_awaited_once_with(search, "06/09/2026", case_type_id=10071)
        search.close.assert_awaited_once()
        detail.close.assert_awaited_once()

    async def test_lookup_error_retries_same_case_in_new_page(self):
        cases = [case("", str(n), "", "", "", "", str(n)) for n in range(2)]
        search = MagicMock(close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=search))
        first = MagicMock(close=AsyncMock())
        replacement = MagicMock(close=AsyncMock())

        async def extract(item, page, *, tabs):
            item.details["tabs"] = {"sides": {}}

        with tempfile.TemporaryDirectory() as directory, patch(
            "main.open_results_page", new=AsyncMock()
        ), patch("main.populate_cases", new=AsyncMock(return_value=cases)), patch(
            "main.open_case_folder", new=AsyncMock(
                side_effect=[first, CaseLookupError("site error"), replacement]
            )
        ) as lookup, patch("main.GetCaseDetails", side_effect=extract):
            result = await run_pipeline(context, "06/09/2026", None, Path(directory) / "cases.json")
        self.assertEqual([entry["status"] for entry in result["cases"]], ["completed", "completed"])
        self.assertEqual(lookup.await_args_list[1].kwargs, {"page": first})
        self.assertEqual(lookup.await_args_list[2].args, (context, cases[1]))
        first.close.assert_awaited_once()
        replacement.close.assert_awaited_once()
        search.close.assert_awaited_once()

    async def test_processes_all_cases_and_marks_missing_sides_partial(self):
        cases = [case("", str(n), "", "", "", "", str(n)) for n in range(2)]
        context = MagicMock(new_page=AsyncMock(return_value=MagicMock(close=AsyncMock())))
        page = MagicMock(close=AsyncMock())
        with tempfile.TemporaryDirectory() as directory, patch("main.open_results_page", new=AsyncMock()), patch(
            "main.populate_cases", new=AsyncMock(return_value=cases)
        ), patch("main.open_case_folder", new=AsyncMock(return_value=page)) as lookup, patch(
            "main.GetCaseDetails", new=AsyncMock()
        ):
            result = await run_pipeline(context, "06/09/2026", None, Path(directory) / "cases.json")
        self.assertEqual([r["status"] for r in result["cases"]], ["partial", "partial"])
        self.assertEqual(lookup.await_count, 2)
        self.assertEqual(result["cases"][0]["missing_tabs"], ["sides"])

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
