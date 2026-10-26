import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scrape_daily import run_days


class DailyRunnerTests(unittest.TestCase):
    def run_with(self, free_mib=(1024, 1024), returncode=0, days=2):
        with tempfile.TemporaryDirectory() as directory, \
                patch("scrape_daily.shutil.disk_usage") as disk, \
                patch("scrape_daily.subprocess.run") as child:
            disk.side_effect = [type("Usage", (), {"free": value * 1024 ** 2})()
                                for value in free_mib]
            child.return_value = subprocess.CompletedProcess([], returncode)
            status = run_days(date(2026, 1, 1), Path(directory), 512, days)
            return status, child.call_args_list

    def test_runs_backward_across_year_with_type_and_checkpoint(self):
        status, calls = self.run_with()
        self.assertEqual(status, 0)
        for call, expected in zip(calls, ["01/01/2026", "31/12/2025"]):
            command = call.args[0]
            self.assertEqual(command[command.index("--date") + 1], expected)
            self.assertEqual(command[command.index("--case-type-id") + 1], "1")
            self.assertIn("--resume", command)
            self.assertEqual(call.kwargs["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(len(calls), 2)

    def test_low_disk_stops_before_next_child(self):
        status, calls = self.run_with([1024, 100])
        self.assertEqual(status, 2)
        self.assertEqual(len(calls), 1)

    def test_failure_does_not_advance_date(self):
        status, calls = self.run_with([1024], returncode=1)
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)

    def test_low_disk_stops_before_child(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("scrape_daily.shutil.disk_usage") as disk, \
                patch("scrape_daily.subprocess.run") as child:
            disk.return_value.free = 100
            self.assertEqual(run_days(date.today(), Path(directory), 512, 1), 2)
            child.assert_not_called()
