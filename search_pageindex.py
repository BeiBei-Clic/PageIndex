#!/usr/bin/env python3
"""
PageIndex 检索脚本
使用生成的树结构进行推理检索
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# 添加 pageindex 到路径
sys.path.insert(0, str(Path(__file__).parent))

import pageindex.utils as utils
from pageindex.prompt import ANSWER_PROMPT
from pageindex.prompt import DOC_SELECTION_PROMPT
from pageindex.prompt import TREE_SEARCH_PROMPT
from pageindex.utils import extract_json, llm_acompletion, llm_completion

CATALOG_VERSION = 1
DEFAULT_DOC_TOP_K = 10
DEFAULT_MAX_CONCURRENCY = 10


def load_tree_structure(json_path):
    """加载 PageIndex 树结构"""
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到树结构文件: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    # 如果是列表，取第一个元素
    if isinstance(tree, list) and len(tree) > 0:
        return tree[0]
    return tree


def normalize_text(text):
    """清理文本中的多余空白。"""
    if not text:
        return ""
    return " ".join(str(text).split())


def build_fallback_doc_description(tree, tree_path):
    """当缺少文档描述时，使用标题和摘要构造一个回退描述。"""
    structure = get_structure_nodes(tree)
    snippets = []

    if isinstance(structure, list):
        for node in structure[:5]:
            if not isinstance(node, dict):
                continue
            title = normalize_text(node.get('title', ''))
            summary = normalize_text(node.get('summary', ''))
            if title and summary:
                snippets.append(f"{title}: {summary}")
            elif title:
                snippets.append(title)
            elif summary:
                snippets.append(summary)
    elif isinstance(structure, dict):
        title = normalize_text(structure.get('title', ''))
        summary = normalize_text(structure.get('summary', ''))
        if title and summary:
            snippets.append(f"{title}: {summary}")
        elif title:
            snippets.append(title)
        elif summary:
            snippets.append(summary)

    if snippets:
        return normalize_text("；".join(snippets))[:400]
    return f"{tree_path.stem} 的树结构文档。"


def get_doc_description(tree, tree_path, model):
    """获取文档描述，必要时基于树结构生成。"""
    if isinstance(tree, dict):
        doc_description = normalize_text(tree.get('doc_description', ''))
        if doc_description:
            return doc_description

    structure = get_structure_nodes(tree)
    clean_structure = utils.create_clean_structure_for_description(structure)
    generated = normalize_text(utils.generate_doc_description(clean_structure, model=model))
    if generated:
        return generated[:400]
    return build_fallback_doc_description(tree, tree_path)


def load_doc_catalog(catalog_path):
    """加载文档目录索引。"""
    if not catalog_path.exists():
        return {}

    try:
        with open(catalog_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"⚠️ 无法读取 catalog，准备重建: {catalog_path}")
        return {}

    entries = payload.get('entries', [])
    if payload.get('version') != CATALOG_VERSION or not isinstance(entries, list):
        print(f"⚠️ catalog 版本不兼容，准备重建: {catalog_path}")
        return {}

    return {
        entry['tree_path']: entry
        for entry in entries
        if isinstance(entry, dict) and entry.get('tree_path')
    }
def sync_doc_catalog(tree_dir, catalog_path, model, rebuild=False):
    """同步目录中的文档索引信息。"""
    tree_dir = Path(tree_dir)
    catalog_path = Path(catalog_path)
    if not tree_dir.exists():
        raise FileNotFoundError(f"未找到目录: {tree_dir}")
    if not tree_dir.is_dir():
        raise NotADirectoryError(f"不是目录: {tree_dir}")

    tree_paths = sorted(tree_dir.glob('*_structure.json'))
    if not tree_paths:
        raise FileNotFoundError(f"目录中未找到匹配 *_structure.json 的树结构文件: {tree_dir}")

    cached_entries = {} if rebuild else load_doc_catalog(catalog_path)
    entries = []
    changed = rebuild

    for tree_path in tree_paths:
        tree_path_str = str(tree_path)
        stat = tree_path.stat()
        cached = cached_entries.get(tree_path_str)

        if (
            cached
            and cached.get('mtime_ns') == stat.st_mtime_ns
            and cached.get('size') == stat.st_size
            and cached.get('doc_name')
            and cached.get('doc_description')
        ):
            entries.append(cached)
            continue

        print(f"🧾 更新文档描述: {tree_path.name}")
        tree = load_tree_structure(tree_path)
        doc_name = tree.get('doc_name') if isinstance(tree, dict) else None
        entries.append({
            'tree_path': str(tree_path),
            'doc_name': normalize_text(doc_name) or tree_path.name,
            'doc_description': get_doc_description(tree, tree_path, model),
            'mtime_ns': stat.st_mtime_ns,
            'size': stat.st_size,
        })
        changed = True

    if len(entries) != len(cached_entries):
        changed = True

    entries.sort(key=lambda item: item['tree_path'])

    if changed:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump({
                'version': CATALOG_VERSION,
                'entries': entries,
            }, f, indent=2, ensure_ascii=False)

    return entries


def get_structure_nodes(tree):
    """提取真正的树节点列表，兼容 PageIndex 标准输出格式。"""
    if isinstance(tree, dict) and 'structure' in tree:
        return tree['structure']
    return tree


async def tree_search_async(query, tree, model):
    """使用异步 LLM 调用在树结构中搜索相关节点。"""
    structure = get_structure_nodes(tree)

    # 移除 text 字段以减少提示词长度
    tree_without_text = utils.remove_fields(structure, fields=['text'])

    doc_info = []
    if isinstance(tree, dict):
        if tree.get('doc_name'):
            doc_info.append(f"文档名: {tree['doc_name']}")
        if tree.get('doc_description'):
            doc_info.append(f"文档描述: {tree['doc_description']}")
    doc_info_text = "\n".join(doc_info)

    search_prompt = TREE_SEARCH_PROMPT.format(
        query=query,
        doc_info_text=doc_info_text,
        tree_structure_json=json.dumps(tree_without_text, indent=2, ensure_ascii=False),
    )
    result = await llm_acompletion(model, search_prompt)
    return extract_json(result)


def select_relevant_documents(query, catalog_entries, model, doc_top_k):
    """使用文档描述先选择相关文档。"""
    documents = []
    entry_map = {}

    for idx, entry in enumerate(catalog_entries, 1):
        doc_id = f"doc_{idx:04d}"
        doc_item = {
            'doc_id': doc_id,
            'doc_name': entry['doc_name'],
            'doc_description': entry['doc_description'],
        }
        documents.append(doc_item)
        entry_map[doc_id] = entry

    selection_prompt = DOC_SELECTION_PROMPT.format(
        query=query,
        documents_json=json.dumps(documents, indent=2, ensure_ascii=False),
        doc_top_k=doc_top_k,
    )

    result = llm_completion(model, selection_prompt)
    parsed = extract_json(result)

    raw_doc_list = parsed.get('doc_list', parsed.get('answer', []))
    if isinstance(raw_doc_list, str):
        raw_doc_list = [raw_doc_list]
    if not isinstance(raw_doc_list, list):
        raw_doc_list = []

    selected_entries = []
    seen = set()
    for doc_id in raw_doc_list:
        doc_id = str(doc_id)
        if doc_id in seen or doc_id not in entry_map:
            continue
        selected_entries.append(entry_map[doc_id])
        seen.add(doc_id)
        if len(selected_entries) >= doc_top_k:
            break

    return parsed, selected_entries
def get_relevant_content(node_list, tree):
    """从相关节点中提取内容"""
    node_map = {}

    def traverse(node):
        if isinstance(node, dict):
            node_id = node.get('node_id')
            if node_id:
                node_map[node_id] = node
            for key in ('structure', 'nodes'):
                children = node.get(key)
                if children:
                    traverse(children)
        elif isinstance(node, list):
            for item in node:
                traverse(item)

    traverse(tree)
    relevant_nodes = []
    for node_id in node_list:
        if node_id in node_map:
            node = node_map[node_id]
            content = node.get('text') or node.get('summary') or ''
            if not content:
                continue
            relevant_nodes.append({
                'node_id': node_id,
                'title': node.get('title', ''),
                'page': f"{node.get('start_index', '')}-{node.get('end_index', '')}",
                'content': content
            })

    return relevant_nodes


async def search_single_tree_async(entry, query, model, semaphore):
    """对单个树结构异步执行检索并提取节点内容。"""
    tree_path = Path(entry['tree_path'])
    tree = load_tree_structure(tree_path)
    source_name = entry['doc_name']

    async with semaphore:
        search_result = await tree_search_async(query, tree, model)

    if 'node_list' not in search_result:
        return {
            'path': tree_path,
            'doc_name': source_name,
            'search_result': search_result,
            'relevant_nodes': [],
        }

    relevant_nodes = get_relevant_content(search_result['node_list'], tree)
    for node in relevant_nodes:
        node['doc_name'] = source_name
        node['tree_path'] = str(tree_path)

    return {
        'path': tree_path,
        'doc_name': source_name,
        'search_result': search_result,
        'relevant_nodes': relevant_nodes,
    }


async def search_tree_directory(query, selected_entries, model, max_concurrency):
    """对筛选出的多个树结构并发执行检索。"""
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [
        search_single_tree_async(entry, query, model, semaphore)
        for entry in selected_entries
    ]
    results = await asyncio.gather(*tasks)
    all_results = []

    for result in results:
        print(f"\n📄 检索文档: {result['doc_name']}")

        search_result = result['search_result']
        if 'node_list' not in search_result:
            print(f"❌ 搜索失败，无法解析结果: {result['path']}")
            print(f"原始结果: {search_result}")
            continue

        print(f"找到 {len(search_result['node_list'])} 个相关节点")
        if 'thinking' in search_result:
            print(f"思考过程: {search_result['thinking'][:200]}...")

        all_results.append(result)

    return all_results


def build_context(relevant_nodes, max_context):
    """按最大长度限制拼接上下文。"""
    context_parts = []
    total_length = 0

    for node in relevant_nodes:
        doc_prefix = f"[文档: {node['doc_name']}] " if node.get('doc_name') else ""
        formatted_node = f"{doc_prefix}[{node['node_id']}] {node['title']} (页 {node['page']})\n{node['content']}"
        if total_length + len(formatted_node) > max_context:
            remaining = max_context - total_length
            if remaining > 0:
                context_parts.append(formatted_node[:remaining] + "...")
            break
        context_parts.append(formatted_node)
        total_length += len(formatted_node)

    return "\n\n---\n\n".join(context_parts)


def main():
    parser = argparse.ArgumentParser(description='PageIndex 目录检索脚本')
    parser.add_argument('--tree_dir', type=str, required=True,
                      help='包含多个 PageIndex 树结构 JSON 文件的目录')
    parser.add_argument('--query', type=str, required=True,
                      help='检索问题')
    parser.add_argument('--model', type=str, default='deepseek/deepseek-chat',
                      help='使用的 LLM 模型')
    parser.add_argument('--doc_top_k', type=int, default=DEFAULT_DOC_TOP_K,
                      help='目录检索时，进入树搜索的最大文档数')
    parser.add_argument('--max_concurrency', type=int, default=DEFAULT_MAX_CONCURRENCY,
                      help='节点检索阶段的最大并发文档数')
    parser.add_argument('--catalog_path', type=str, default=None,
                      help='目录检索时使用的文档描述 catalog 路径')
    parser.add_argument('--rebuild_catalog', action='store_true',
                      help='强制重建目录检索使用的文档描述 catalog')
    parser.add_argument('--max_context', type=int, default=10000,
                      help='最大上下文字符数')

    args = parser.parse_args()
    if args.doc_top_k <= 0:
        raise ValueError("--doc_top_k 必须大于 0")
    if args.max_concurrency <= 0:
        raise ValueError("--max_concurrency 必须大于 0")

    print(f"🔍 检索问题: {args.query}")
    tree_dir = Path(args.tree_dir)
    catalog_path = Path(args.catalog_path) if args.catalog_path else tree_dir / '.pageindex_doc_catalog.json'

    print(f"📁 加载树结构目录: {tree_dir}")
    catalog_entries = sync_doc_catalog(
        tree_dir=tree_dir,
        catalog_path=catalog_path,
        model=args.model,
        rebuild=args.rebuild_catalog,
    )
    print(f"✓ 文档 catalog 已准备完成，共 {len(catalog_entries)} 个文件")
    print(f"📚 Catalog 路径: {catalog_path}\n")

    print("正在筛选相关文档...")
    doc_selection_result, selected_entries = select_relevant_documents(
        args.query,
        catalog_entries,
        args.model,
        args.doc_top_k,
    )

    raw_doc_list = doc_selection_result.get('doc_list', doc_selection_result.get('answer', []))
    if not isinstance(raw_doc_list, list):
        raw_doc_list = []

    print(f"\n📚 文档筛选结果 (从 {len(catalog_entries)} 个文档中选择 {len(selected_entries)} 个):")
    if 'thinking' in doc_selection_result:
        print(f"思考过程: {doc_selection_result['thinking'][:200]}...\n")

    if not selected_entries:
        print("❌ 文档级筛选未命中任何相关文档。")
        if raw_doc_list:
            print(f"模型返回的文档标识无效: {raw_doc_list}")
        return

    for i, entry in enumerate(selected_entries, 1):
        print(f"{i}. {entry['doc_name']} ({entry['tree_path']})")

    print(f"\n正在并发搜索入选文档中的相关节点 (max_concurrency={args.max_concurrency})...")
    search_results = asyncio.run(
        search_tree_directory(
            args.query,
            selected_entries,
            args.model,
            args.max_concurrency,
        )
    )
    relevant_nodes = []
    total_node_hits = 0

    for result in search_results:
        total_node_hits += len(result['search_result'].get('node_list', []))
        relevant_nodes.extend(result['relevant_nodes'])

    print(f"\n📊 目录检索结果 (共找到 {total_node_hits} 个相关节点，提取 {len(relevant_nodes)} 个有效上下文节点):")

    if not relevant_nodes:
        print("❌ 未能从检索结果中提取任何节点内容。")
        print("请检查 JSON 是否使用了标准的 `structure` 根字段，以及节点是否包含 `text` 或 `summary`。")
        return

    for i, node in enumerate(relevant_nodes, 1):
        doc_prefix = f"[{node['doc_name']}] " if node.get('doc_name') else ""
        print(f"{i}. {doc_prefix}[{node['node_id']}] 页 {node['page']}: {node['title']}")

    context = build_context(relevant_nodes, args.max_context)

    if not context.strip():
        print("❌ 检索到了相关节点，但拼接后的上下文为空，已停止调用模型。")
        return

    # 生成答案
    print(f"\n💡 正在生成答案...")
    answer = llm_completion(args.model, ANSWER_PROMPT.format(query=args.query, context=context))

    print("\n" + "="*60)
    print("答案:")
    print("="*60)
    print(answer)
    print("="*60)


if __name__ == "__main__":
    main()
