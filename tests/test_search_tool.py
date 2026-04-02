import contextlib
import inspect
import io
import sys
import types
import unittest
from argparse import Namespace
from unittest.mock import AsyncMock, Mock, patch

langchain_module = types.ModuleType("langchain")
langchain_module.__path__ = []

tools_module = types.ModuleType("langchain.tools")
agents_module = types.ModuleType("langchain.agents")
chat_models_module = types.ModuleType("langchain.chat_models")


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
agents_module.create_agent = lambda *args, **kwargs: None
chat_models_module.init_chat_model = lambda *args, **kwargs: None

sys.modules["langchain"] = langchain_module
sys.modules["langchain.tools"] = tools_module
sys.modules["langchain.agents"] = agents_module
sys.modules["langchain.chat_models"] = chat_models_module

import agent_pageindex
import list_pageindex_docs
import pageindex.postgres_store as store_impl
import pageindex.search as search_impl
import run_pageindex


def _call_tool_impl(tool_obj, payload):
    if hasattr(tool_obj, "func") and callable(tool_obj.func):
        return tool_obj.func(**payload)
    return tool_obj(**payload)


class RunTreeSearchTests(unittest.TestCase):
    def test_run_tree_search_selects_documents_and_truncates_context(self) -> None:
        catalog_entries = [
            store_impl.CatalogDocument(
                document_id="doc-alpha",
                source_path="db://trees/alpha",
                source_type="pdf",
                doc_name="Alpha Doc",
                doc_description="Alpha description",
                updated_at="2026-04-01T00:00:00+00:00",
            ),
            store_impl.CatalogDocument(
                document_id="doc-beta",
                source_path="db://trees/beta",
                source_type="pdf",
                doc_name="Beta Doc",
                doc_description="Beta description",
                updated_at="2026-04-01T00:00:01+00:00",
            ),
        ]
        search_results = [
            search_impl.DocumentSearchResult(
                document_id="doc-beta",
                source_path="db://trees/beta",
                doc_name="Beta Doc",
                search_result={"node_list": ["beta-1"]},
                relevant_nodes=[
                    search_impl.RelevantNode(
                        node_id="beta-1",
                        title="Beta section",
                        page="1-2",
                        content="B" * 60,
                        document_id="doc-beta",
                        doc_name="Beta Doc",
                        source_path="db://trees/beta",
                    )
                ],
                ok=True,
            ),
            search_impl.DocumentSearchResult(
                document_id="doc-alpha",
                source_path="db://trees/alpha",
                doc_name="Alpha Doc",
                search_result={"node_list": ["alpha-1"]},
                relevant_nodes=[
                    search_impl.RelevantNode(
                        node_id="alpha-1",
                        title="Alpha section",
                        page="3-4",
                        content="A" * 60,
                        document_id="doc-alpha",
                        doc_name="Alpha Doc",
                        source_path="db://trees/alpha",
                    )
                ],
                ok=True,
            ),
        ]

        with (
            patch.object(search_impl, "list_catalog_documents", return_value=catalog_entries),
            patch.object(search_impl, "get_documents_by_ids", return_value=[]),
            patch.object(search_impl, "_search_selected_documents", new=AsyncMock(return_value=search_results)),
            patch.object(search_impl, "llm_completion", side_effect=["{}", "Synthesized answer"]),
            patch.object(search_impl, "extract_json", return_value={"doc_list": ["doc-beta", "doc-beta", "missing", "doc-alpha"]}),
        ):
            result = search_impl.run_tree_search(
                query="What changed?",
                doc_top_k=2,
                max_concurrency=2,
                max_context=45,
            )

        self.assertEqual([entry.doc_name for entry in result.selected_entries], ["Beta Doc", "Alpha Doc"])
        self.assertEqual(result.raw_doc_list, ["doc-beta", "doc-beta", "missing", "doc-alpha"])
        self.assertEqual(result.total_node_hits, 2)
        self.assertEqual(len(result.relevant_nodes), 2)
        self.assertTrue(result.context_truncated)
        self.assertTrue(result.context.endswith("..."))
        self.assertEqual(result.answer, "Synthesized answer")
        self.assertEqual(result.catalog_backend, "postgres")
        self.assertIn("Beta Doc", search_impl.format_search_result(result))

    def test_run_tree_search_returns_empty_result_without_llm_when_catalog_is_empty(self) -> None:
        with (
            patch.object(search_impl, "list_catalog_documents", return_value=[]),
            patch.object(search_impl, "llm_completion") as llm_completion_mock,
        ):
            result = search_impl.run_tree_search(query="Anything?")

        self.assertEqual(result.catalog_entries, [])
        self.assertEqual(result.selected_entries, [])
        self.assertEqual(result.answer, None)
        llm_completion_mock.assert_not_called()

    def test_run_tree_search_handles_empty_selection(self) -> None:
        catalog_entries = [
            store_impl.CatalogDocument(
                document_id="doc-alpha",
                source_path="db://trees/alpha",
                source_type="pdf",
                doc_name="Alpha Doc",
                doc_description="Alpha description",
                updated_at="2026-04-01T00:00:00+00:00",
            )
        ]

        with (
            patch.object(search_impl, "list_catalog_documents", return_value=catalog_entries),
            patch.object(search_impl, "llm_completion", return_value="{}"),
            patch.object(search_impl, "extract_json", return_value={"doc_list": ["unknown_doc"]}),
        ):
            result = search_impl.run_tree_search(
                query="Missing doc?",
                doc_top_k=1,
            )

        self.assertEqual(result.selected_entries, [])
        self.assertEqual(result.search_results, [])
        self.assertEqual(result.answer, None)
        self.assertEqual(result.total_node_hits, 0)
        self.assertIn("No relevant documents were selected", search_impl.format_search_result(result))


class ToolContractTests(unittest.TestCase):
    def test_search_pageindex_exposes_tool_metadata_and_returns_artifact(self) -> None:
        fake_result = search_impl.PageIndexSearchResult(
            selected_entries=[
                search_impl.CatalogEntry(
                    document_id="doc-demo",
                    source_path="db://trees/demo",
                    doc_name="Demo Doc",
                    doc_description="Demo description",
                    updated_at="2026-04-01T00:00:00+00:00",
                )
            ],
            relevant_nodes=[
                search_impl.RelevantNode(
                    node_id="node-1",
                    title="Demo section",
                    page="1-2",
                    content="content",
                    document_id="doc-demo",
                    doc_name="Demo Doc",
                    source_path="db://trees/demo",
                )
            ],
            answer="Direct answer",
        )

        with patch.object(search_impl, "run_tree_search", return_value=fake_result):
            content, artifact = _call_tool_impl(
                search_impl.search_pageindex,
                {"query": "Q"},
            )

        self.assertEqual(getattr(search_impl.search_pageindex, "name", ""), "search_pageindex")
        self.assertEqual(getattr(search_impl.search_pageindex, "response_format", None), "content_and_artifact")
        self.assertIn("query", getattr(search_impl.search_pageindex, "args", {}))
        self.assertNotIn("tree_dir", getattr(search_impl.search_pageindex, "args", {}))
        self.assertIn("Postgres-backed PageIndex search", getattr(search_impl.search_pageindex, "description", ""))
        self.assertIsInstance(content, str)
        self.assertIsInstance(artifact, dict)
        self.assertEqual(artifact["answer"], "Direct answer")
        self.assertEqual(artifact["selected_entries"][0]["doc_name"], "Demo Doc")

    def test_search_pageindex_propagates_runtime_errors(self) -> None:
        with patch.object(search_impl, "run_tree_search", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                _call_tool_impl(
                    search_impl.search_pageindex,
                    {"query": "Q"},
                )


class AgentIntegrationTests(unittest.TestCase):
    def test_main_builds_agent_with_search_pageindex(self) -> None:
        args = Namespace(
            query="What is this?",
            doc_top_k=3,
            max_concurrency=4,
            max_context=200,
            verbose=False,
        )
        mock_agent = Mock()
        mock_agent.invoke.return_value = {"messages": [types.SimpleNamespace(content="final answer")]}

        with (
            patch.object(agent_pageindex, "create_agent", Mock(return_value=mock_agent)) as create_agent_mock,
            patch.object(agent_pageindex, "init_chat_model", Mock(return_value="chat-model")),
            patch.object(agent_pageindex, "load_dotenv"),
            patch.object(agent_pageindex.os, "getenv", return_value="test-key"),
            patch("argparse.ArgumentParser.parse_args", return_value=args),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            agent_pageindex.main()

        self.assertIn("final answer", stdout.getvalue())
        self.assertEqual(create_agent_mock.call_args.kwargs["tools"], [agent_pageindex.search_pageindex])

    def test_print_verbose_stream_defaults_to_search_pageindex_name(self) -> None:
        class ToolMessage:
            def __init__(self, content: str) -> None:
                self.id = "tool-1"
                self.content = content

        class FakeAgent:
            def stream(self, agent_input, stream_mode="updates"):
                yield {"tools": {"messages": [ToolMessage("tool output")]}}

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            agent_pageindex._print_verbose_stream(FakeAgent(), {"messages": []})

        self.assertIn("[tool result] search_pageindex", buffer.getvalue())


class IngestCliTests(unittest.TestCase):
    def test_run_pageindex_pdf_ingest_prints_document_id(self) -> None:
        args = Namespace(
            pdf_path=["demo.pdf"],
            md_path=None,
            model=None,
            toc_check_pages=None,
            max_pages_per_node=None,
            max_tokens_per_node=None,
            if_add_node_id=None,
            if_add_node_summary=None,
            if_add_doc_description=None,
            if_add_node_text=None,
            if_thinning="no",
            thinning_threshold=5000,
            summary_token_threshold=200,
            max_workers=None,
        )
        fake_document = store_impl.StoredDocument(
            document_id="doc-demo",
            source_path="C:/docs/demo.pdf",
            source_type="pdf",
            doc_name="Demo Doc",
            doc_description="Demo description",
            tree_json={"doc_name": "Demo Doc", "doc_description": "Demo description", "structure": []},
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",
        )

        with (
            patch("argparse.ArgumentParser.parse_args", return_value=args),
            patch.object(run_pageindex.Path, "exists", return_value=True),
            patch.object(run_pageindex.Path, "is_file", return_value=True),
            patch.object(run_pageindex.Path, "is_dir", return_value=False),
            patch.object(run_pageindex, "page_index_main", return_value={"doc_name": "Demo Doc", "doc_description": "Demo description", "structure": []}),
            patch.object(run_pageindex, "upsert_pageindex_document", return_value=fake_document) as upsert_mock,
            patch.object(run_pageindex, "ConfigLoader", return_value=Mock(load=Mock(return_value="opt"))),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            run_pageindex.main()

        self.assertIn("document_id: doc-demo", stdout.getvalue())
        self.assertIn("source_path: C:/docs/demo.pdf", stdout.getvalue())
        self.assertEqual(upsert_mock.call_args.kwargs["source_type"], "pdf")


class ListDocsCliTests(unittest.TestCase):
    def test_list_pageindex_docs_prints_catalog(self) -> None:
        args = Namespace(doc_name=None, document_id=None)
        catalog_entries = [
            store_impl.CatalogDocument(
                document_id="doc-main",
                source_path="C:/docs/main.pdf",
                source_type="pdf",
                doc_name="main.pdf",
                doc_description="Main document",
                updated_at="2026-04-01T00:00:00+00:00",
            )
        ]

        with (
            patch("argparse.ArgumentParser.parse_args", return_value=args),
            patch.object(list_pageindex_docs, "list_catalog_documents", return_value=catalog_entries),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            list_pageindex_docs.main()

        output = stdout.getvalue()
        self.assertIn("Document count: 1", output)
        self.assertIn("main.pdf", output)
        self.assertIn("document_id: doc-main", output)

    def test_list_pageindex_docs_prints_all_nodes_for_doc_name(self) -> None:
        args = Namespace(doc_name="main.pdf", document_id=None)
        catalog_entries = [
            store_impl.CatalogDocument(
                document_id="doc-main",
                source_path="C:/docs/main.pdf",
                source_type="pdf",
                doc_name="main.pdf",
                doc_description="Main document",
                updated_at="2026-04-01T00:00:00+00:00",
            )
        ]
        stored_documents = [
            store_impl.StoredDocument(
                document_id="doc-main",
                source_path="C:/docs/main.pdf",
                source_type="pdf",
                doc_name="main.pdf",
                doc_description="Main document",
                tree_json={
                    "doc_name": "main.pdf",
                    "doc_description": "Main document",
                    "structure": [
                        {
                            "title": "Chapter 1",
                            "node_id": "0001",
                            "start_index": 1,
                            "end_index": 3,
                            "summary": "Intro",
                            "nodes": [
                                {
                                    "title": "Section 1.1",
                                    "node_id": "0002",
                                    "start_index": 2,
                                    "end_index": 2,
                                    "summary": "Details",
                                    "text": "Node text",
                                    "nodes": [],
                                }
                            ],
                        }
                    ],
                },
                created_at="2026-04-01T00:00:00+00:00",
                updated_at="2026-04-01T00:00:00+00:00",
            )
        ]

        with (
            patch("argparse.ArgumentParser.parse_args", return_value=args),
            patch.object(list_pageindex_docs, "list_catalog_documents", return_value=catalog_entries),
            patch.object(list_pageindex_docs, "get_documents_by_ids", return_value=stored_documents),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            list_pageindex_docs.main()

        output = stdout.getvalue()
        self.assertIn("doc_name: main.pdf", output)
        self.assertIn('"title": "Chapter 1"', output)
        self.assertIn('"title": "Section 1.1"', output)
        self.assertIn('"depth": 1', output)
        self.assertIn("Total nodes: 2", output)


if __name__ == "__main__":
    unittest.main()
