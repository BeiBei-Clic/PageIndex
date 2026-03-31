from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from langchain.tools import tool

from . import utils
from .prompt import ANSWER_PROMPT, DOC_SELECTION_PROMPT, TREE_SEARCH_PROMPT
from .utils import extract_json, llm_acompletion, llm_completion

CATALOG_VERSION = 1
DEFAULT_DOC_TOP_K = 10
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_MODEL = "deepseek/deepseek-chat"
DEFAULT_MAX_CONTEXT = 10000


@dataclass(slots=True)
class CatalogEntry:
    tree_path: str
    doc_name: str
    doc_description: str
    mtime_ns: int
    size: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CatalogEntry":
        tree_path = str(payload["tree_path"])
        return cls(
            tree_path=tree_path,
            doc_name=_normalize_text(payload.get("doc_name")) or Path(tree_path).name,
            doc_description=_normalize_text(payload.get("doc_description")),
            mtime_ns=int(payload.get("mtime_ns", 0)),
            size=int(payload.get("size", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RelevantNode:
    node_id: str
    title: str
    page: str
    content: str
    doc_name: str | None = None
    tree_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DocumentSearchResult:
    path: str
    doc_name: str
    search_result: Any
    relevant_nodes: list[RelevantNode] = field(default_factory=list)
    ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PageIndexSearchResult:
    tree_dir: str
    catalog_path: str
    catalog_entries: list[CatalogEntry] = field(default_factory=list)
    catalog_updated_paths: list[str] = field(default_factory=list)
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


def _load_tree_structure(json_path: str | Path) -> dict[str, Any] | list[Any]:
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Tree structure file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        tree = json.load(handle)
    if isinstance(tree, list) and tree:
        return tree[0]
    return tree


def _normalize_text(text: Any) -> str:
    return " ".join(str(text).split()) if text else ""


def _get_doc_description(tree: Any, tree_path: str | Path, model: str) -> str:
    tree_data = tree if isinstance(tree, dict) else {}
    doc_description = _normalize_text(tree_data.get("doc_description", ""))
    if doc_description:
        return doc_description

    structure = tree_data.get("structure", tree)
    clean_structure = utils.create_clean_structure_for_description(structure)
    generated = _normalize_text(utils.generate_doc_description(clean_structure, model=model))
    if generated:
        return generated[:400]

    if isinstance(structure, dict):
        candidate_nodes = [structure]
    elif isinstance(structure, list):
        candidate_nodes = structure[:5]
    else:
        candidate_nodes = []

    snippets: list[str] = []
    for node in candidate_nodes:
        if not isinstance(node, dict):
            continue
        title = _normalize_text(node.get("title", ""))
        summary = _normalize_text(node.get("summary", ""))
        if title and summary:
            snippets.append(f"{title}: {summary}")
        elif title or summary:
            snippets.append(title or summary)

    if snippets:
        return _normalize_text("; ".join(snippets))[:400]
    return f"Tree structure for {Path(tree_path).stem}."


def _sync_doc_catalog(
    tree_dir: str | Path,
    catalog_path: str | Path,
    model: str,
    rebuild: bool = False,
) -> tuple[list[CatalogEntry], list[str]]:
    tree_dir = Path(tree_dir)
    catalog_path = Path(catalog_path)
    if not tree_dir.exists():
        raise FileNotFoundError(f"Directory not found: {tree_dir}")
    if not tree_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {tree_dir}")

    tree_paths = sorted(tree_dir.glob("*_structure.json"))
    if not tree_paths:
        raise FileNotFoundError(f"No *_structure.json files found in directory: {tree_dir}")

    cached_entries: dict[str, CatalogEntry] = {}
    if not rebuild and catalog_path.exists():
        with catalog_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        cached_payload_entries = payload.get("entries", [])
        if payload.get("version") == CATALOG_VERSION and isinstance(cached_payload_entries, list):
            cached_entries = {
                str(entry["tree_path"]): CatalogEntry.from_payload(entry)
                for entry in cached_payload_entries
                if isinstance(entry, dict) and entry.get("tree_path")
            }

    entries: list[CatalogEntry] = []
    updated_paths: list[str] = []
    changed = rebuild

    for tree_path in tree_paths:
        stat = tree_path.stat()
        cached = cached_entries.get(str(tree_path))
        if (
            cached
            and cached.mtime_ns == stat.st_mtime_ns
            and cached.size == stat.st_size
            and cached.doc_name
            and cached.doc_description
        ):
            entries.append(cached)
            continue

        tree = _load_tree_structure(tree_path)
        doc_name = tree.get("doc_name") if isinstance(tree, dict) else None
        entries.append(
            CatalogEntry(
                tree_path=str(tree_path),
                doc_name=_normalize_text(doc_name) or tree_path.name,
                doc_description=_get_doc_description(tree, tree_path, model),
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
            )
        )
        updated_paths.append(str(tree_path))
        changed = True

    if len(entries) != len(cached_entries):
        changed = True

    entries.sort(key=lambda item: item.tree_path)

    if changed:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with catalog_path.open("w", encoding="utf-8") as handle:
            json.dump(
                {"version": CATALOG_VERSION, "entries": [entry.to_dict() for entry in entries]},
                handle,
                indent=2,
                ensure_ascii=False,
            )

    return entries, updated_paths


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
    selected_entries: list[CatalogEntry],
    model: str,
    max_concurrency: int,
) -> list[DocumentSearchResult]:
    semaphore = asyncio.Semaphore(max_concurrency)

    async def search_entry(entry: CatalogEntry) -> DocumentSearchResult:
        tree_path = Path(entry.tree_path)
        tree = _load_tree_structure(tree_path)

        structure = tree.get("structure", tree) if isinstance(tree, dict) else tree
        doc_info: list[str] = []
        if isinstance(tree, dict):
            if tree.get("doc_name"):
                doc_info.append(f"Document name: {tree['doc_name']}")
            if tree.get("doc_description"):
                doc_info.append(f"Document description: {tree['doc_description']}")

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
                node.doc_name = entry.doc_name
                node.tree_path = str(tree_path)

        return DocumentSearchResult(
            path=str(tree_path),
            doc_name=entry.doc_name,
            search_result=search_result,
            relevant_nodes=relevant_nodes,
            ok=ok,
        )

    return await asyncio.gather(*(search_entry(entry) for entry in selected_entries))


def _normalize_raw_doc_list(doc_selection_result: Any) -> list[str]:
    if not isinstance(doc_selection_result, dict):
        return []

    raw_doc_list = doc_selection_result.get("doc_list", doc_selection_result.get("answer", []))
    if isinstance(raw_doc_list, str):
        return [raw_doc_list]
    if isinstance(raw_doc_list, list):
        return [str(doc_id) for doc_id in raw_doc_list]
    return []


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
    tree_dir: str,
    model: str = DEFAULT_MODEL,
    doc_top_k: int = DEFAULT_DOC_TOP_K,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    catalog_path: str | None = None,
    rebuild_catalog: bool = False,
    max_context: int = DEFAULT_MAX_CONTEXT,
) -> PageIndexSearchResult:
    if doc_top_k <= 0:
        raise ValueError("--doc_top_k must be greater than 0")
    if max_concurrency <= 0:
        raise ValueError("--max_concurrency must be greater than 0")

    tree_dir_path = Path(tree_dir)
    catalog_path_obj = Path(catalog_path) if catalog_path else tree_dir_path / ".pageindex_doc_catalog.json"

    catalog_entries, catalog_updated_paths = _sync_doc_catalog(
        tree_dir=tree_dir_path,
        catalog_path=catalog_path_obj,
        model=model,
        rebuild=rebuild_catalog,
    )

    documents: list[dict[str, str]] = []
    entry_map: dict[str, CatalogEntry] = {}
    for index, entry in enumerate(catalog_entries, start=1):
        doc_id = f"doc_{index:04d}"
        documents.append(
            {
                "doc_id": doc_id,
                "doc_name": entry.doc_name,
                "doc_description": entry.doc_description,
            }
        )
        entry_map[doc_id] = entry

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
    raw_doc_list = _normalize_raw_doc_list(doc_selection_result)

    selected_entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for doc_id in raw_doc_list:
        entry = entry_map.get(str(doc_id))
        if not entry or doc_id in seen:
            continue
        selected_entries.append(entry)
        seen.add(doc_id)
        if len(selected_entries) >= doc_top_k:
            break

    search_results: list[DocumentSearchResult] = []
    relevant_nodes: list[RelevantNode] = []
    total_node_hits = 0
    context = ""
    answer: str | None = None
    context_truncated = False

    if selected_entries:
        search_results = asyncio.run(
            _search_selected_documents(
                query=query,
                selected_entries=selected_entries,
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
        tree_dir=str(tree_dir_path),
        catalog_path=str(catalog_path_obj),
        catalog_entries=catalog_entries,
        catalog_updated_paths=catalog_updated_paths,
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
            lines.append(f"{index}. {entry.doc_name} ({entry.tree_path})")
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
def search_tree_dir(
    query: str,
    tree_dir: str,
    model: str = DEFAULT_MODEL,
    doc_top_k: int = DEFAULT_DOC_TOP_K,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    catalog_path: str | None = None,
    rebuild_catalog: bool = False,
    max_context: int = DEFAULT_MAX_CONTEXT,
) -> tuple[str, dict[str, Any]]:
    """Answer a question using PageIndex tree search over a directory of `*_structure.json` files.

    Args:
        query: Natural-language question to answer from the indexed documents.
        tree_dir: Directory containing one or more `*_structure.json` files.
        model: Model name used for document selection, tree search, and answer synthesis.
        doc_top_k: Maximum number of documents selected before tree search.
        max_concurrency: Maximum number of selected documents searched concurrently.
        catalog_path: Optional path to the cached document catalog JSON file.
        rebuild_catalog: Whether to rebuild the cached document catalog before searching.
        max_context: Maximum number of context characters assembled for the final answer prompt.

    Returns:
        A tuple of stable text content for the language model and a structured artifact with the full result.
    """
    result = run_tree_search(
        query=query,
        tree_dir=tree_dir,
        model=model,
        doc_top_k=doc_top_k,
        max_concurrency=max_concurrency,
        catalog_path=catalog_path,
        rebuild_catalog=rebuild_catalog,
        max_context=max_context,
    )
    return format_search_result(result), result.to_dict()


__all__ = [
    "CATALOG_VERSION",
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
    "search_tree_dir",
]
