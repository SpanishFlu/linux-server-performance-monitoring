"""Unit tests for network-rate and alert logic."""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src"),
)

from monitor import AlertTracker, counter_rate


class TestCounterRate(unittest.TestCase):
    def test_rate_conversion(self):
        # Transfer 2 MiB over 2 seconds.
        self.assertEqual(
            counter_rate(2 * 1024 ** 2, 0, 2),
            1.0,
        )

    def test_counter_reset(self):
        self.assertEqual(counter_rate(100, 200, 1), 0)

    def test_zero_elapsed_rejected(self):
        with self.assertRaises(ValueError):
            counter_rate(100, 0, 0)


class TestAlertTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = AlertTracker({"cpu_percent": 85})

    def test_below_threshold(self):
        self.assertEqual(
            self.tracker.update({"cpu_percent": 50}),
            [],
        )

    def test_threshold_is_inclusive(self):
        events = self.tracker.update({"cpu_percent": 85})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "WARNING")

    def test_no_duplicate_alert(self):
        self.tracker.update({"cpu_percent": 90})
        self.assertEqual(
            self.tracker.update({"cpu_percent": 95}),
            [],
        )

    def test_recovery(self):
        self.tracker.update({"cpu_percent": 90})
        events = self.tracker.update({"cpu_percent": 40})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "INFO")
        self.assertIn("RECOVERY", events[0][1])

    def test_alert_after_recovery(self):
        self.tracker.update({"cpu_percent": 90})
        self.tracker.update({"cpu_percent": 40})
        events = self.tracker.update({"cpu_percent": 90})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "WARNING")


if __name__ == "__main__":
    unittest.main()
