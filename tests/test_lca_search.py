import json
import pathlib
import sqlite3
import tempfile
import unittest

from lca_search import (
    _create_schema,
    _fts_expression,
    _json_text,
    query_search_database,
)


class SearchProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tempdir.name) / "search.sqlite3"
        conn = sqlite3.connect(self.path)
        try:
            _create_schema(conn)
            conn.executemany(
                """INSERT INTO activities (
                    database, code, name, reference_product, location, unit,
                    type, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')""",
                [
                    ("test", "one", "Cotton yarn", "yarn", "GLO", "kg", "process"),
                    ("test", "two", "Wool yarn", "yarn", "CH", "kg", "process"),
                ],
            )
            conn.executemany(
                "INSERT INTO activities_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("test", "one", "Cotton yarn", "yarn", "", "", "", "fibre"),
                    ("test", "two", "Wool yarn", "yarn", "", "", "", "fibre"),
                ],
            )
            conn.execute(
                """INSERT INTO exchanges (
                    output_database, output_code, input_database, input_code,
                    type, amount, unit, extra_json
                ) VALUES ('test', 'one', 'test', 'two', 'technosphere', 2.5, 'kg', '{}')"""
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def query(self, sql, params=None, limit=100):
        return query_search_database(
            sql,
            params,
            limit=limit,
            path=self.path,
            require_fresh=False,
        )

    def test_json_is_deterministic_and_not_pickled(self):
        value = _json_text({"tuple": (1, 2), "set": {"b", "a"}})
        self.assertEqual(json.loads(value), {"set": ["a", "b"], "tuple": [1, 2]})
        with self.assertRaises(ValueError):
            _json_text({"bad": float("nan")})
        with self.assertRaises(TypeError):
            _json_text({"bad": b"pickle-like bytes"})

    def test_select_and_cte_are_allowed(self):
        result = self.query(
            "WITH matches AS (SELECT * FROM activities WHERE unit = ?) "
            "SELECT code, name FROM matches ORDER BY code",
            ("kg",),
        )
        self.assertEqual(result["rows"], [["one", "Cotton yarn"], ["two", "Wool yarn"]])
        self.assertFalse(result["truncated"])

    def test_limit_reports_truncation(self):
        result = self.query("SELECT code FROM activities ORDER BY code", limit=1)
        self.assertEqual(result["rows"], [["one"]])
        self.assertTrue(result["truncated"])

    def test_mutations_and_pragmas_are_denied(self):
        for sql in (
            "DELETE FROM activities",
            "UPDATE activities SET name = 'changed'",
            "PRAGMA table_info(activities)",
            "ATTACH DATABASE ':memory:' AS other",
        ):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                self.query(sql)

    def test_multiple_statements_are_denied(self):
        with self.assertRaises(ValueError):
            self.query("SELECT 1; SELECT 2")

    def test_fts5_queries_work_through_authorizer(self):
        result = self.query(
            "SELECT code, name, bm25(activities_fts) AS rank "
            "FROM activities_fts WHERE activities_fts MATCH ? ORDER BY rank",
            (_fts_expression("cotton"),),
        )
        self.assertEqual(result["rows"][0][:2], ["one", "Cotton yarn"])

    def test_exchange_view_has_typed_amount(self):
        result = self.query(
            "SELECT consumer_name, input_name, amount, unit FROM exchange_details"
        )
        self.assertEqual(result["rows"], [["Cotton yarn", "Wool yarn", 2.5, "kg"]])


if __name__ == "__main__":
    unittest.main()
