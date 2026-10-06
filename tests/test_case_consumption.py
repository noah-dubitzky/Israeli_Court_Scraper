import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Average_Consumption_Per_Case_Finder import load_cases, measure_cases
from case import case
from case_details import CASE_TABS


class ConsumptionTests(unittest.IsolatedAsyncioTestCase):
    def test_load_pipeline_records_and_numbers_with_fresh_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps({"cases": [
                {"case": {"number": "123-09-26", "details": {"old": True}}},
                "123-09-26", "456-09-26",
            ]}), encoding="utf-8")
            items = load_cases(path)
        self.assertEqual([item.number for item in items], ["123-09-26", "456-09-26"])
        self.assertEqual(items[0].details, {})

    async def test_measures_actual_saved_bytes_and_continues_after_failure(self):
        items = [case("", f"{n}-09-26", "", "", "", "", "") for n in range(1, 4)]
        pages = [MagicMock(close=AsyncMock()) for _ in items]

        async def extract(item, page):
            item.details["tabs"] = {"general_details": {"body": "שלום"}}
            if item.number.startswith("2-"):
                raise RuntimeError("unavailable")
            if item.number.startswith("1-"):
                item.details["tabs"].update({tab.key: {} for tab in CASE_TABS})

        with tempfile.TemporaryDirectory() as directory, patch(
            "Average_Comsumption_Per_Case_Finder.open_case_folder", new=AsyncMock(side_effect=pages)
        ), patch("Average_Comsumption_Per_Case_Finder.GetCaseDetails", side_effect=extract), patch(
            "Average_Comsumption_Per_Case_Finder.perf_counter", side_effect=[0, 2, 3, 8, 10, 16]
        ):
            output = Path(directory)
            run = await measure_cases(MagicMock(), items, output)
            self.assertEqual(json.loads((output / "summary.json").read_text(encoding="utf-8")), run)
            for entry in run["cases"]:
                payload = (output / entry["file"]).read_bytes()
                self.assertEqual(entry["storage_bytes"], len(payload))
                self.assertIn("tabs", json.loads(payload)["details"])
        self.assertEqual([entry["status"] for entry in run["cases"]],
                         ["completed", "failed", "partial"])
        self.assertEqual(run["summary"]["average_extraction_seconds"], 4)
        self.assertEqual(run["summary"]["average_storage_bytes"],
                         (run["cases"][0]["storage_bytes"] + run["cases"][2]["storage_bytes"]) / 2)
        for page in pages:
            page.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
