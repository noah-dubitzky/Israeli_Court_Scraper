import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Average_Case_Per_Day_Counter import count_date, count_days, sample_days


class CounterTests(unittest.IsolatedAsyncioTestCase):
    def test_sample_is_unique_reproducible_and_within_ten_years(self):
        today = date(2026, 10, 5)
        days = sample_days(today, seed=42)
        self.assertEqual(len(set(days)), 100)
        self.assertEqual(days, sample_days(today, seed=42))
        self.assertTrue(all(date(2016, 10, 5) <= day < today for day in days))
        leap_days = sample_days(date(2024, 2, 29), seed=42)
        self.assertTrue(all(date(2014, 2, 28) <= day < date(2024, 2, 29)
                            for day in leap_days))

    async def test_zero_days_count_but_failed_days_do_not(self):
        page = MagicMock(close=AsyncMock(), url="https://www.court.gov.il/NGCS.Web.Site/SearchCase/CasesSearchView.aspx")
        context = MagicMock(new_page=AsyncMock(return_value=page))
        days = [date(2026, 1, n) for n in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory, patch(
            "Average_Case_Per_Day_Counter.search_cases_on_page", new=AsyncMock(
                side_effect=[MagicMock(), MagicMock(), RuntimeError("offline"),
                             RuntimeError("offline"), RuntimeError("offline")]
            )
        ), patch("Average_Case_Per_Day_Counter.populate_cases", new=AsyncMock(
            side_effect=[[object(), object(), object(), object()], []]
        )):
            output = Path(directory) / "counts.json"
            result = await count_days(context, days, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), result)
        self.assertEqual(result["total_cases"], 4)
        self.assertEqual(result["average_cases_per_day"], 2)
        self.assertEqual(result["successful_days"], 2)
        self.assertEqual(result["failed_days"], 1)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["days"][2]["count"])
        self.assertEqual(page.close.await_count, 1)
        context.new_page.assert_awaited_once()

    async def test_reuses_search_and_recovers_home_redirect_on_same_date(self):
        search_url = "https://www.court.gov.il/NGCS.Web.Site/SearchCase/CasesSearchView.aspx"
        home_url = "https://www.court.gov.il/NGCS.Web.Site/HomePage.aspx"
        page = MagicMock(url=search_url, close=AsyncMock())
        context = MagicMock(new_page=AsyncMock(return_value=page))

        async def search(*args, **kwargs):
            # The second date's first attempt gets redirected to home.
            if search_fn.await_count == 2:
                page.url = home_url
            return MagicMock()

        async def recover(*args, **kwargs):
            page.url = search_url

        with tempfile.TemporaryDirectory() as directory, patch(
            "Average_Case_Per_Day_Counter.search_cases_on_page", side_effect=search
        ) as search_fn, patch(
            "Average_Case_Per_Day_Counter.navigate_to_date_search", side_effect=recover
        ) as menu, patch(
            "Average_Case_Per_Day_Counter.open_court_page", new=AsyncMock()
        ) as open_home, patch(
            "Average_Case_Per_Day_Counter.populate_cases", new=AsyncMock(return_value=[])
        ) as collect:
            result = await count_days(context, [date(2026, 1, 1), date(2026, 1, 2)],
                                      Path(directory) / "counts.json", case_type_id=10071)
        self.assertTrue(result["complete"])
        self.assertEqual([call.args[1] for call in search_fn.await_args_list],
                         ["01/01/2026", "02/01/2026", "02/01/2026"])
        menu.assert_awaited_once_with(page)
        open_home.assert_not_awaited()
        self.assertEqual(collect.await_count, 2)
        context.new_page.assert_awaited_once()
        page.close.assert_awaited_once()

    async def test_initial_visit_opens_home_once(self):
        page = MagicMock(url="about:blank")

        async def open_home(*args):
            page.url = "https://www.court.gov.il/NGCS.Web.Site/SearchCase/CasesSearchView.aspx"

        with patch("Average_Case_Per_Day_Counter.open_court_page", side_effect=open_home) as home, patch(
            "Average_Case_Per_Day_Counter.search_cases_on_page", new=AsyncMock()
        ), patch("Average_Case_Per_Day_Counter.populate_cases", new=AsyncMock(return_value=[])):
            await count_date(page, "01/01/2026", None)
            await count_date(page, "02/01/2026", None)
        home.assert_awaited_once_with(page)


if __name__ == "__main__":
    unittest.main()
