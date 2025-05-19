import unittest
from unittest.mock import MagicMock

from helpers.db_helpers import not_enough_balance


class TestNotEnoughBalance(unittest.TestCase):

    def setUp(self):
        self.db_user = MagicMock()
        self.db_user.seconds_balance = 10

    def test_balance_insufficient(self):
        result = not_enough_balance(self.db_user, 15)
        self.assertTrue(result)

    def test_balance_sufficient(self):
        result = not_enough_balance(self.db_user, 5)
        self.assertFalse(result)

    def test_balance_exact_zero(self):
        result = not_enough_balance(self.db_user, 10)
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
