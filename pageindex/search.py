import asyncio
import json
from pathlib import Path

from . import utils
from .prompt import ANSWER_PROMPT, DOC_SELECTION_PROMPT, TREE_SEARCH_PROMPT
from .utils import extract_json, llm_acompletion, llm_completion

CATALOG_VERSION = 1
DEFAULT_DOC_TOP_K = 10
DEFAULT_MAX_CONCURRENCY = 10


def _load_tree_structure(json_path):
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到树结构文件: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    if isinstance(tree, list) and tree:
        return tree[0]
    return tree


def _normalize_text(text):
    return " ".join(str(text).split()) if text else ""


def _get_doc_description(tree, tree_path, model):
    tree_data = tree if isinstance(tree, dict) else {}
    doc_description = _normalize_text(tree_data.get('doc_description', ''))
    if doc_description:
        return doc_description

    structure = tree_data.get('structure', tree)
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
    snippets = []
    for node in candidate_nodes:
        if not isinstance(node, dict):
            continue
        title = _normalize_text(node.get('title', ''))
        summary = _normalize_text(node.get('summary', ''))
        if title and summary:
            snippets.append(f"{title}: {summary}")
        elif title or summary:
            snippets.append(title or summary)

    if snippets:
        return _normalize_text("；".join(snippets))[:400]
    return f"{Path(tree_path).stem} 的树结构文档。"


def _sync_doc_catalog(tree_dir, catalog_path, model, rebuild=False):
    tree_dir = Path(tree_dir)
    catalog_path = Path(catalog_path)
    if not tree_dir.exists():
        raise FileNotFoundError(f"未找到目录: {tree_dir}")
    if not tree_dir.is_dir():
        raise NotADirectoryError(f"不是目录: {tree_dir}")

    tree_paths = sorted(tree_dir.glob('*_structure.json'))
    if not tree_paths:
        raise FileNotFoundError(f"目录中未找到匹配 *_structure.json 的树结构文件: {tree_dir}")

    cached_entries = {}
    if not rebuild and catalog_path.exists():
        try:
            with open(catalog_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            cached_payload_entries = payload.get('entries', [])
            if payload.get('version') == CATALOG_VERSION and isinstance(cached_payload_entries, list):
                cached_entries = {
                    entry['tree_path']: entry
                    for entry in cached_payload_entries
                    if isinstance(entry, dict) and entry.get('tree_path')
                }
        except (json.JSONDecodeError, OSError):
            cached_entries = {}

    entries = []
    updated_paths = []
    changed = rebuild

    for tree_path in tree_paths:
        stat = tree_path.stat()
        cached = cached_entries.get(str(tree_path))
        if (
            cached
            and cached.get('mtime_ns') == stat.st_mtime_ns
            and cached.get('size') == stat.st_size
            and cached.get('doc_name')
            and cached.get('doc_description')
        ):
            entries.append(cached)
            continue

        tree = _load_tree_structure(tree_path)
        doc_name = tree.get('doc_name') if isinstance(tree, dict) else None
        entries.append({
            'tree_path': str(tree_path),
            'doc_name': _normalize_text(doc_name) or tree_path.name,
            'doc_description': _get_doc_description(tree, tree_path, model),
            'mtime_ns': stat.st_mtime_ns,
            'size': stat.st_size,
        })
        updated_paths.append(str(tree_path))
        changed = True

    if len(entries) != len(cached_entries):
        changed = True

    entries.sort(key=lambda item: item['tree_path'])

    if changed:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump(
                {'version': CATALOG_VERSION, 'entries': entries},
                f,
                indent=2,
                ensure_ascii=False,
            )

    return entries, updated_paths


def _get_relevant_content(node_list, tree):
    node_map = {}
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
            continue
        if not isinstance(node, dict):
            continue

        node_id = node.get('node_id')
        if node_id:
            node_map[node_id] = node
        for key in ('structure', 'nodes'):
            children = node.get(key)
            if children:
                stack.append(children)

    relevant_nodes = []
    for node_id in node_list:
        node = node_map.get(str(node_id))
        if not node:
            continue
        content = node.get('text') or node.get('summary') or ''
        if not content:
            continue
        relevant_nodes.append({
            'node_id': str(node_id),
            'title': node.get('title', ''),
            'page': f"{node.get('start_index', '')}-{node.get('end_index', '')}",
            'content': content,
        })

    return relevant_nodes


async def _search_selected_documents(query, selected_entries, model, max_concurrency):
    semaphore = asyncio.Semaphore(max_concurrency)

    async def search_entry(entry):
        tree_path = Path(entry['tree_path'])
        tree = _load_tree_structure(tree_path)

        structure = tree.get('structure', tree) if isinstance(tree, dict) else tree
        doc_info = []
        if isinstance(tree, dict):
            if tree.get('doc_name'):
                doc_info.append(f"文档名: {tree['doc_name']}")
            if tree.get('doc_description'):
                doc_info.append(f"文档描述: {tree['doc_description']}")

        async with semaphore:
            search_result = extract_json(
                await llm_acompletion(
                    model,
                    TREE_SEARCH_PROMPT.format(
                        query=query,
                        doc_info_text="\n".join(doc_info),
                        tree_structure_json=json.dumps(
                            utils.remove_fields(structure, fields=['text']),
                            indent=2,
                            ensure_ascii=False,
                        ),
                    ),
                )
            )

        relevant_nodes = []
        node_list = search_result.get('node_list') if isinstance(search_result, dict) else None
        ok = isinstance(node_list, list)
        if ok:
            relevant_nodes = _get_relevant_content(node_list, tree)
            for node in relevant_nodes:
                node['doc_name'] = entry['doc_name']
                node['tree_path'] = str(tree_path)

        return {
            'path': str(tree_path),
            'doc_name': entry['doc_name'],
            'search_result': search_result,
            'relevant_nodes': relevant_nodes,
            'ok': ok,
        }

    return await asyncio.gather(*(search_entry(entry) for entry in selected_entries))


def search_tree_dir(
    tree_dir,
    query,
    model='deepseek/deepseek-chat',
    doc_top_k=DEFAULT_DOC_TOP_K,
    max_concurrency=DEFAULT_MAX_CONCURRENCY,
    catalog_path=None,
    rebuild_catalog=False,
    max_context=10000,
):
    if doc_top_k <= 0:
        raise ValueError("--doc_top_k 必须大于 0")
    if max_concurrency <= 0:
        raise ValueError("--max_concurrency 必须大于 0")

    tree_dir = Path(tree_dir)
    catalog_path = Path(catalog_path) if catalog_path else tree_dir / '.pageindex_doc_catalog.json'

    catalog_entries, catalog_updated_paths = _sync_doc_catalog(
        tree_dir=tree_dir,
        catalog_path=catalog_path,
        model=model,
        rebuild=rebuild_catalog,
    )

    documents = []
    entry_map = {}
    for idx, entry in enumerate(catalog_entries, 1):
        doc_id = f"doc_{idx:04d}"
        documents.append({
            'doc_id': doc_id,
            'doc_name': entry['doc_name'],
            'doc_description': entry['doc_description'],
        })
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
    raw_doc_list = doc_selection_result.get('doc_list', doc_selection_result.get('answer', []))
    if isinstance(raw_doc_list, str):
        raw_doc_list = [raw_doc_list]
    elif not isinstance(raw_doc_list, list):
        raw_doc_list = []

    selected_entries = []
    seen = set()
    for doc_id in raw_doc_list:
        doc_id = str(doc_id)
        entry = entry_map.get(doc_id)
        if not entry or doc_id in seen:
            continue
        selected_entries.append(entry)
        seen.add(doc_id)
        if len(selected_entries) >= doc_top_k:
            break

    search_results = []
    relevant_nodes = []
    total_node_hits = 0
    context = ""
    answer = None

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
            len(result['search_result'].get('node_list', []))
            for result in search_results
            if isinstance(result.get('search_result'), dict)
        )
        for result in search_results:
            relevant_nodes.extend(result['relevant_nodes'])
        if relevant_nodes:
            context_parts = []
            total_length = 0
            for node in relevant_nodes:
                doc_prefix = f"[文档: {node['doc_name']}] " if node.get('doc_name') else ""
                formatted_node = (
                    f"{doc_prefix}[{node['node_id']}] {node['title']} "
                    f"(页 {node['page']})\n{node['content']}"
                )
                if total_length + len(formatted_node) > max_context:
                    remaining = max_context - total_length
                    if remaining > 0:
                        context_parts.append(formatted_node[:remaining] + "...")
                    break
                context_parts.append(formatted_node)
                total_length += len(formatted_node)

            context = "\n\n---\n\n".join(context_parts)
            if context.strip():
                answer = llm_completion(
                    model,
                    ANSWER_PROMPT.format(query=query, context=context),
                )

    return {
        'tree_dir': str(tree_dir),
        'catalog_path': str(catalog_path),
        'catalog_entries': catalog_entries,
        'catalog_updated_paths': catalog_updated_paths,
        'doc_selection_result': doc_selection_result,
        'raw_doc_list': raw_doc_list,
        'selected_entries': selected_entries,
        'search_results': search_results,
        'total_node_hits': total_node_hits,
        'relevant_nodes': relevant_nodes,
        'context': context,
        'answer': answer,
    }
