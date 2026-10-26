import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from case import case
from case_details import open_case_folder
from court_search import search_cases_on_page


class StopAfterRecovery(Exception):
    pass


class InputRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_date_timeout_returns_home_and_retries_before_filtering(self):
        page = MagicMock()
        date_input = page.locator.return_value
        date_input.wait_for = AsyncMock(side_effect=[PlaywrightTimeoutError("hidden"), None])
        date_input.click = AsyncMock(side_effect=StopAfterRecovery)
        with patch("court_search.open_court_page", new_callable=AsyncMock) as home, \
                patch("court_search._select_case_type", new_callable=AsyncMock) as select:
            with self.assertRaises(StopAfterRecovery):
                await search_cases_on_page(page, "06/09/2026", 10071)
        home.assert_awaited_once_with(page)
        self.assertEqual(date_input.wait_for.await_count, 2)
        date_input.wait_for.assert_awaited_with(state="visible", timeout=10000)
        select.assert_awaited_once_with(page, 10071)

    async def test_either_case_input_timeout_recovers_and_retries_same_case(self):
        for missing in (0, 1):
            with self.subTest(missing=missing):
                page = MagicMock()
                controls = [MagicMock() for _ in range(3)]
                page.locator.side_effect = controls
                for control in controls:
                    control.wait_for = AsyncMock()
                controls[missing].wait_for.side_effect = [PlaywrightTimeoutError("hidden"), None]
                controls[0].fill = AsyncMock(side_effect=StopAfterRecovery)
                item = case("", "10195-09-26", "", "", "", "", "")
                with patch("case_details.open_court_page", new_callable=AsyncMock) as home:
                    with self.assertRaises(StopAfterRecovery):
                        await open_case_folder(MagicMock(), item, page=page)
                home.assert_awaited_once_with(page, disable_timeouts=False)
                controls[0].fill.assert_awaited_once_with("10195")
                self.assertEqual(controls[missing].wait_for.await_count, 2)


if __name__ == "__main__":
    unittest.main()
