import inspect
import os
import sys
import types
import unittest
from unittest.mock import patch

langchain_module = types.ModuleType("langchain")
langchain_module.__path__ = []
tools_module = types.ModuleType("langchain.tools")


def _fake_tool(*, parse_docstring=False, response_format=None):
    def decorator(function):
        signature = inspect.signature(function)
        function.func = function
        function.name = function.__name__
        function.description = inspect.getdoc(function) or ""
        function.response_format = response_format
        function.args = {
            name: {
                "title": name,
                "default": None if parameter.default is inspect._empty else parameter.default,
            }
            for name, parameter in signature.parameters.items()
        }
        function.invoke = lambda payload: function(**payload)
        return function

    return decorator


tools_module.tool = _fake_tool

sys.modules["langchain"] = langchain_module
sys.modules["langchain.tools"] = tools_module

import pageindex.postgres_store as store_impl


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        sql = " ".join(query.split())
        self.state["queries"].append(sql)

        if sql.startswith("CREATE TABLE IF NOT EXISTS pageindex_documents"):
            self.state["table_created"] = True
            self.rows = []
            return

        if sql.startswith("INSERT INTO pageindex_documents"):
            document_id, source_path, source_type, doc_name, doc_description, tree_json = params
            self.state["clock"] += 1
            if source_path in self.state["rows_by_path"]:
                row = self.state["rows_by_path"][source_path]
                row["source_type"] = source_type
                row["doc_name"] = doc_name
                row["doc_description"] = doc_description
                row["tree_json"] = eval_json(tree_json)
                row["updated_at"] = f"ts-{self.state['clock']}"
            else:
                row = {
                    "document_id": document_id,
                    "source_path": source_path,
                    "source_type": source_type,
                    "doc_name": doc_name,
                    "doc_description": doc_description,
                    "tree_json": eval_json(tree_json),
                    "created_at": f"ts-{self.state['clock']}",
                    "updated_at": f"ts-{self.state['clock']}",
                }
                self.state["rows_by_path"][source_path] = row
            self.rows = [to_stored_row(row)]
            return

        if sql.startswith("SELECT document_id::text, source_path, source_type, doc_name, doc_description, updated_at FROM pageindex_documents"):
            rows = [self.state["rows_by_path"][path] for path in sorted(self.state["rows_by_path"])]
            self.rows = [to_catalog_row(row) for row in rows]
            return

        if sql.startswith("SELECT document_id::text, source_path, source_type, doc_name, doc_description, tree_json, created_at, updated_at FROM pageindex_documents"):
            wanted_ids = set(params[0])
            rows = [
                row
                for _, row in sorted(self.state["rows_by_path"].items())
                if row["document_id"] in wanted_ids
            ]
            self.rows = [to_stored_row(row) for row in rows]
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.state)


def eval_json(payload):
    import json

    return json.loads(payload)


def to_catalog_row(row):
    return (
        row["document_id"],
        row["source_path"],
        row["source_type"],
        row["doc_name"],
        row["doc_description"],
        row["updated_at"],
    )


def to_stored_row(row):
    return (
        row["document_id"],
        row["source_path"],
        row["source_type"],
        row["doc_name"],
        row["doc_description"],
        row["tree_json"],
        row["created_at"],
        row["updated_at"],
    )


class PostgresStoreTests(unittest.TestCase):
    def test_get_postgres_dsn_requires_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PAGEINDEX_POSTGRES_DSN"):
                store_impl.get_postgres_dsn()

    def test_upsert_document_creates_table_and_inserts_row(self) -> None:
        state = {"queries": [], "table_created": False, "rows_by_path": {}, "clock": 0}

        with patch.object(store_impl, "_connect", return_value=FakeConnection(state)):
            document = store_impl.upsert_pageindex_document(
                source_path="demo.pdf",
                source_type="pdf",
                result={"doc_name": "Demo Doc", "doc_description": "Demo description", "structure": []},
            )

        self.assertTrue(state["table_created"])
        self.assertEqual(document.doc_name, "Demo Doc")
        self.assertEqual(document.doc_description, "Demo description")
        self.assertEqual(document.source_type, "pdf")
        self.assertTrue(document.source_path.endswith("demo.pdf"))

    def test_upsert_document_preserves_document_id_for_same_source_path(self) -> None:
        state = {"queries": [], "table_created": False, "rows_by_path": {}, "clock": 0}

        with patch.object(store_impl, "_connect", return_value=FakeConnection(state)):
            first = store_impl.upsert_pageindex_document(
                source_path="demo.pdf",
                source_type="pdf",
                result={"doc_name": "First Name", "doc_description": "First description", "structure": []},
            )
            second = store_impl.upsert_pageindex_document(
                source_path="demo.pdf",
                source_type="pdf",
                result={"doc_name": "Second Name", "doc_description": "Second description", "structure": []},
            )

        self.assertEqual(first.document_id, second.document_id)
        self.assertNotEqual(first.updated_at, second.updated_at)
        self.assertEqual(second.doc_name, "Second Name")
        self.assertEqual(second.doc_description, "Second description")

    def test_list_and_get_documents_read_back_rows(self) -> None:
        state = {"queries": [], "table_created": False, "rows_by_path": {}, "clock": 0}

        with patch.object(store_impl, "_connect", return_value=FakeConnection(state)):
            first = store_impl.upsert_pageindex_document(
                source_path="alpha.pdf",
                source_type="pdf",
                result={"doc_name": "Alpha", "doc_description": "Alpha description", "structure": []},
            )
            second = store_impl.upsert_pageindex_document(
                source_path="beta.pdf",
                source_type="pdf",
                result={"doc_name": "Beta", "doc_description": "Beta description", "structure": []},
            )
            catalog_entries = store_impl.list_catalog_documents()
            documents = store_impl.get_documents_by_ids([second.document_id, first.document_id])

        self.assertEqual([entry.doc_name for entry in catalog_entries], ["Alpha", "Beta"])
        self.assertEqual({document.document_id for document in documents}, {first.document_id, second.document_id})

    def test_upsert_document_removes_nul_chars_from_tree_json_and_description(self) -> None:
        state = {"queries": [], "table_created": False, "rows_by_path": {}, "clock": 0}

        with patch.object(store_impl, "_connect", return_value=FakeConnection(state)):
            document = store_impl.upsert_pageindex_document(
                source_path="nul-demo.pdf",
                source_type="pdf",
                result={
                    "doc_name": "Demo\x00 Doc",
                    "doc_description": "Desc\x00ription",
                    "structure": [
                        {
                            "title": "Node\x00 Title",
                            "text": "Text\x00Value",
                            "nodes": [],
                        }
                    ],
                },
            )

        self.assertEqual(document.doc_name, "Demo Doc")
        self.assertEqual(document.doc_description, "Description")
        self.assertEqual(document.tree_json["structure"][0]["title"], "Node Title")
        self.assertEqual(document.tree_json["structure"][0]["text"], "TextValue")


if __name__ == "__main__":
    unittest.main()
