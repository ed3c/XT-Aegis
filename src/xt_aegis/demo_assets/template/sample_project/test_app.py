from __future__ import annotations

import unittest

from app import calculate_tax


class CalculateTaxTest(unittest.TestCase):
    def test_regular_amount(self) -> None:
        self.assertEqual(calculate_tax(100.0), 5.0)

    def test_zero(self) -> None:
        self.assertEqual(calculate_tax(0.0), 0.0)

    def test_negative_amount(self) -> None:
        with self.assertRaisesRegex(ValueError, "Amount cannot be negative"):
            calculate_tax(-10.0)


if __name__ == "__main__":
    unittest.main()
