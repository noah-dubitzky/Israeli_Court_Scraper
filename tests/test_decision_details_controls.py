import unittest
from unittest.mock import AsyncMock, MagicMock

from case_details import _extract_decision_details


class DecisionDetailsTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, present):
        controls = {}
        for suffix in ("lblHeader", "lblDocumentName", "tbGivenBy", "tbDateOfSign",
                       "tbDecisionDescription", "tbConfidential", "tbDecisionType",
                       "cbOneSide", "cbOpenSecondSide", "cbChosenDecision",
                       "rbCriticalDesicion", "rbTechnicalDesicion"):
            controls[suffix] = MagicMock(
                wait_for=AsyncMock(), inner_text=AsyncMock(return_value="text"),
                input_value=AsyncMock(return_value="value"),
                count=AsyncMock(return_value=int(suffix in present)),
                is_checked=AsyncMock(return_value=suffix in present and present[suffix]),
            )
        area = MagicMock()
        area.locator.side_effect = lambda selector: controls[selector.split('_', 1)[1].split('"')[0]]
        page = MagicMock()
        page.locator.return_value.filter.return_value = area
        return await _extract_decision_details(page, timeout=100), controls

    async def test_absent_checkboxes_are_unknown_and_do_not_wait(self):
        details, controls = await self.extract({"rbCriticalDesicion": False,
                                                "rbTechnicalDesicion": True})
        for field, suffix in (("given_ex_parte", "cbOneSide"),
                              ("release_to_other_side", "cbOpenSecondSide"),
                              ("show_in_selected_decisions", "cbChosenDecision")):
            self.assertIsNone(details[field])
            controls[suffix].is_checked.assert_not_awaited()
        self.assertFalse(details["is_substantive"])
        self.assertTrue(details["is_technical"])

    async def test_present_checkboxes_preserve_checked_and_unchecked_values(self):
        details, _ = await self.extract({"cbOneSide": True, "cbOpenSecondSide": False,
                                        "cbChosenDecision": True,
                                        "rbCriticalDesicion": False,
                                        "rbTechnicalDesicion": True})
        self.assertTrue(details["given_ex_parte"])
        self.assertFalse(details["release_to_other_side"])
        self.assertTrue(details["show_in_selected_decisions"])
