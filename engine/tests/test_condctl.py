"""Table tests for the route-condition grammar."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import condctl  # noqa: E402


def sub(mapping):
    return lambda text: mapping.get(text, text if "${" not in text else None)


class ParseTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(condctl.parse("${x} == true"), ("${x}", "==", True))
        self.assertEqual(condctl.parse("${x} != 3"), ("${x}", "!=", 3))
        self.assertEqual(condctl.parse("${x}"), ("${x}", "truthy", None))
        self.assertEqual(condctl.parse("${x} in [a, b, 'c d']"), ("${x}", "in", ["a", "b", "c d"]))
        self.assertEqual(condctl.parse('${x} == "quoted str"'), ("${x}", "==", "quoted str"))

    def test_rejects(self):
        for bad in ("", "${x} == ", "== y", "${x} == two words", "${x} in []",
                    "${x} == 'unterminated"):
            with self.assertRaises(condctl.CondError, msg=bad):
                condctl.parse(bad)


class EvalTest(unittest.TestCase):
    def test_equality_normalisation(self):
        cases = [
            ("${x} == true", {"${x}": True}, True),
            ("${x} == true", {"${x}": "true"}, True),
            ("${x} == true", {"${x}": "false"}, False),
            ("${x} == 3", {"${x}": 3}, True),
            ("${x} == 3", {"${x}": "3"}, True),
            ("${x} == 3", {"${x}": 3.0}, True),
            ("${x} == ask", {"${x}": "ask"}, True),
            ("${x} != ask", {"${x}": "refine"}, True),
            ("${x} == ask", {"${x}": None}, False),
        ]
        for cond, mapping, expected in cases:
            self.assertEqual(condctl.evaluate(cond, sub(mapping)), expected, cond)

    def test_truthy(self):
        for value, expected in [(True, True), ("yes", True), ("1", True), (1, True),
                                (False, False), ("", False), ("0", False), (0, False),
                                (None, False), ("null", False), ("false", False)]:
            self.assertEqual(condctl.evaluate("${x}", sub({"${x}": value})), expected, repr(value))

    def test_in(self):
        self.assertTrue(condctl.evaluate("${x} in [a, b]", sub({"${x}": "b"})))
        self.assertFalse(condctl.evaluate("${x} in [a, b]", sub({"${x}": "c"})))
        self.assertTrue(condctl.evaluate("${x} in [1, 2]", sub({"${x}": "2"})))


if __name__ == "__main__":
    unittest.main()
