import unittest

from module import cache_size


class CacheSizeTests(unittest.TestCase):
    def test_default(self):
        self.assertEqual(cache_size(None), 64)

    def test_zero_is_preserved(self):
        self.assertEqual(cache_size(0), 0)

    def test_positive_is_preserved(self):
        self.assertEqual(cache_size(8), 8)


if __name__ == "__main__":
    unittest.main()
