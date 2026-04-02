from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from langchain.tools import tool

from . import utils
from .postgres_store import StoredDocument, get_documents_by_ids, list_catalog_documents
from .prompt import ANSWER_PROMPT, DOC_SELECTION_PROMPT, TREE_SEARCH_PROMPT
from .utils import extract_json, llm_acompletion, llm_completion

DEFAULT_DOC_TOP_K = 10
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_MODEL = "deepseek/deepseek-chat"
DEFAULT_MAX_CONTEXT = 10000
CATALOG_BACKEND = "postgres"


@dataclass(slots=True)
class CatalogEntry:
    document_id: str
    source_path: str
    doc_name: str
    doc_description: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RelevantNode:
    node_id: str
    title: str
    page: str
    content: str
    document_id: str | None = None
    doc_name: str | None = None
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DocumentSearchResult:
    document_id: str
    source_path: str
    doc_name: str
    search_result: Any
    relevant_nodes: list[RelevantNode] = field(default_factory=list)
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PageIndexSearchResult:
    catalog_backend: str = CATALOG_BACKEND
    catalog_entries: list[CatalogEntry] = field(default_factory=list)
    doc_selection_result: Any = field(default_factory=dict)
    raw_doc_list: list[str] = field(default_factory=list)
    selected_entries: list[CatalogEntry] = field(default_factory=list)
    search_results: list[DocumentSearchResult] = field(default_factory=list)
    total_node_hits: int = 0
    relevant_nodes: list[RelevantNode] = field(default_factory=list)
    context: str = ""
    answer: str | None = None
    context_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_relevant_content(node_list: list[Any], tree: Any) -> list[RelevantNode]:
    node_map: dict[str, dict[str, Any]] = {}
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
            continue
        if not isinstance(node, dict):
            continue

        node_id = node.get("node_id")
        if node_id:
            node_map[str(node_id)] = node
        for key in ("structure", "nodes"):
            children = node.get(key)
            if children:
                stack.append(children)

    relevant_nodes: list[RelevantNode] = []
    for node_id in node_list:
        node = node_map.get(str(node_id))
        if not node:
            continue
        content = node.get("text") or node.get("summary") or ""
        if not content:
            continue
        relevant_nodes.append(
            RelevantNode(
                node_id=str(node_id),
                title=str(node.get("title", "")),
                page=f"{node.get('start_index', '')}-{node.get('end_index', '')}",
                content=str(content),
            )
        )

    return relevant_nodes


async def _search_selected_documents(
    query: str,
    selected_documents: list[StoredDocument],
    model: str,
    max_concurrency: int,
) -> list[DocumentSearchResult]:
    semaphore = asyncio.Semaphore(max_concurrency)

    async def search_document(document: StoredDocument) -> DocumentSearchResult:
        tree = document.tree_json
        structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
        doc_info = [
            f"Document name: {document.doc_name}",
            f"Document description: {document.doc_description}",
            f"Source path: {document.source_path}",
        ]

        async with semaphore:
            search_result = extract_json(
                await llm_acompletion(
                    model,
                    TREE_SEARCH_PROMPT.format(
                        query=query,
                        doc_info_text="\n".join(doc_info),
                        tree_structure_json=json.dumps(
                            utils.remove_fields(structure, fields=["text"]),
                            indent=2,
                            ensure_ascii=False,
                        ),
                    ),
                )
            )

        relevant_nodes: list[RelevantNode] = []
        node_list = search_result.get("node_list") if isinstance(search_result, dict) else None
        ok = isinstance(node_list, list)
        if ok:
            relevant_nodes = _get_relevant_content(node_list, tree)
            for node in relevant_nodes:
                node.document_id = document.document_id
                node.doc_name = document.doc_name
                node.source_path = document.source_path

        return DocumentSearchResult(
            document_id=document.document_id,
            source_path=document.source_path,
            doc_name=document.doc_name,
            search_result=search_result,
            relevant_nodes=relevant_nodes,
            ok=ok,
        )

    return await asyncio.gather(*(search_document(document) for document in selected_documents))
def _build_context(relevant_nodes: list[RelevantNode], max_context: int) -> tuple[str, bool]:
    if max_context < 0:
        raise ValueError("--max_context must be greater than or equal to 0")
    if not relevant_nodes or max_context == 0:
        return "", bool(relevant_nodes) and max_context == 0

    context_parts: list[str] = []
    total_length = 0
    truncated = False
    for node in relevant_nodes:
        doc_prefix = f"[Document: {node.doc_name}] " if node.doc_name else ""
        formatted_node = f"{doc_prefix}[{node.node_id}] {node.title} (page {node.page})\n{node.content}"
        if total_length + len(formatted_node) > max_context:
            remaining = max_context - total_length
            if remaining > 0:
                context_parts.append(formatted_node[:remaining] + "...")
            truncated = True
            break
        context_parts.append(formatted_node)
        total_length += len(formatted_node)

    return "\n\n---\n\n".join(context_parts), truncated


def run_tree_search(
    query: str,
    model: str = DEFAULT_MODEL,
    doc_top_k: int = DEFAULT_DOC_TOP_K,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    max_context: int = DEFAULT_MAX_CONTEXT,
) -> PageIndexSearchResult:
    if doc_top_k <= 0:
        raise ValueError("--doc_top_k must be greater than 0")
    if max_concurrency <= 0:
        raise ValueError("--max_concurrency must be greater than 0")

    catalog_entries = [
        CatalogEntry(
            document_id=record.document_id,
            source_path=record.source_path,
            doc_name=record.doc_name,
            doc_description=record.doc_description,
            updated_at=record.updated_at,
        )
        for record in list_catalog_documents()
    ]
    if not catalog_entries:
        return PageIndexSearchResult(catalog_entries=[])

    documents: list[dict[str, str]] = []
    entry_map: dict[str, CatalogEntry] = {}
    for entry in catalog_entries:
        documents.append(
            {
                "doc_id": entry.document_id,
                "doc_name": entry.doc_name,
                "doc_description": entry.doc_description,
                "source_path": entry.source_path,
            }
        )
        entry_map[entry.document_id] = entry

    doc_selection_result = extract_json(
        llm_completion(
            model,
            DOC_SELECTION_PROMPT.format(
                query=query,
                documents_json=json.dumps(documents, indent=2, ensure_ascii=False),
                doc_top_k=doc_top_k,
            ),
        )
    )
    raw_doc_list_value = doc_selection_result.get("doc_list", doc_selection_result.get("answer", [])) if isinstance(doc_selection_result, dict) else []
    if isinstance(raw_doc_list_value, str):
        raw_doc_list = [raw_doc_list_value]
    elif isinstance(raw_doc_list_value, list):
        raw_doc_list = [str(doc_id) for doc_id in raw_doc_list_value]
    else:
        raw_doc_list = []

    selected_entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for document_id in raw_doc_list:
        entry = entry_map.get(str(document_id))
        if not entry or document_id in seen:
            continue
        selected_entries.append(entry)
        seen.add(document_id)
        if len(selected_entries) >= doc_top_k:
            break

    search_results: list[DocumentSearchResult] = []
    relevant_nodes: list[RelevantNode] = []
    total_node_hits = 0
    context = ""
    answer: str | None = None
    context_truncated = False

    if selected_entries:
        loaded_documents = get_documents_by_ids([entry.document_id for entry in selected_entries])
        loaded_documents_by_id = {document.document_id: document for document in loaded_documents}
        search_results = asyncio.run(
            _search_selected_documents(
                query=query,
                selected_documents=[
                    loaded_documents_by_id[entry.document_id]
                    for entry in selected_entries
                    if entry.document_id in loaded_documents_by_id
                ],
                model=model,
                max_concurrency=max_concurrency,
            )
        )
        total_node_hits = sum(
            len(result.search_result.get("node_list", []))
            for result in search_results
            if isinstance(result.search_result, dict)
        )
        for result in search_results:
            relevant_nodes.extend(result.relevant_nodes)
        if relevant_nodes:
            context, context_truncated = _build_context(relevant_nodes, max_context=max_context)
            if context.strip():
                answer = llm_completion(
                    model,
                    ANSWER_PROMPT.format(query=query, context=context),
                )

    return PageIndexSearchResult(
        catalog_entries=catalog_entries,
        doc_selection_result=doc_selection_result,
        raw_doc_list=raw_doc_list,
        selected_entries=selected_entries,
        search_results=search_results,
        total_node_hits=total_node_hits,
        relevant_nodes=relevant_nodes,
        context=context,
        answer=answer,
        context_truncated=context_truncated,
    )


def format_search_result(result: PageIndexSearchResult) -> str:
    answer = (result.answer or "").strip()
    if answer:
        answer_text = answer
    elif not result.selected_entries:
        answer_text = "No relevant documents were selected for this question."
        if result.raw_doc_list:
            answer_text += f" The model returned invalid document ids: {result.raw_doc_list}."
    elif not result.relevant_nodes:
        answer_text = "Relevant documents were selected, but no usable context nodes were extracted."
    elif not result.context.strip():
        answer_text = "Relevant nodes were found, but the assembled context was empty."
    else:
        answer_text = "PageIndex completed retrieval, but the final answer was empty."

    lines = ["Answer:", answer_text, "", "Selected documents:"]
    if result.selected_entries:
        for index, entry in enumerate(result.selected_entries, start=1):
            lines.append(f"{index}. [{entry.document_id}] {entry.doc_name} ({entry.source_path})")
    else:
        lines.append("None")

    lines.extend(["", "Relevant nodes:"])
    if result.relevant_nodes:
        for index, node in enumerate(result.relevant_nodes, start=1):
            doc_name = node.doc_name or "Unknown document"
            lines.append(f"{index}. [{doc_name}] [{node.node_id}] page {node.page}: {node.title}")
    else:
        lines.append("None")

    if result.context_truncated:
        lines.extend(["", f"Context was truncated to {len(result.context)} characters."])

    return "\n".join(lines)


@tool(parse_docstring=True, response_format="content_and_artifact")
def search_pageindex(
    query: str,
    model: str = DEFAULT_MODEL,
    doc_top_k: int = DEFAULT_DOC_TOP_K,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    max_context: int = DEFAULT_MAX_CONTEXT,
) -> tuple[str, dict[str, Any]]:
    """Answer a question using Postgres-backed PageIndex search.

    Args:
        query: Natural-language question to answer from the indexed documents.
        model: Model name used for document selection, tree search, and answer synthesis.
        doc_top_k: Maximum number of documents selected before tree search.
        max_concurrency: Maximum number of selected documents searched concurrently.
        max_context: Maximum number of context characters assembled for the final answer prompt.

    Returns:
        A tuple of stable text content for the language model and a structured artifact with the full result.
    """
    result = run_tree_search(
        query=query,
        model=model,
        doc_top_k=doc_top_k,
        max_concurrency=max_concurrency,
        max_context=max_context,
    )
    return format_search_result(result), result.to_dict()


__all__ = [
    "CATALOG_BACKEND",
    "DEFAULT_DOC_TOP_K",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_CONTEXT",
    "DEFAULT_MODEL",
    "CatalogEntry",
    "DocumentSearchResult",
    "PageIndexSearchResult",
    "RelevantNode",
    "format_search_result",
    "run_tree_search",
    "search_pageindex",
]
