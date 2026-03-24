#!/usr/bin/env python3
"""
PageIndex 检索脚本
使用生成的树结构进行推理检索
"""
import argparse
import json
import sys
from pathlib import Path

# 添加 pageindex 到路径
sys.path.insert(0, str(Path(__file__).parent))

import pageindex.utils as utils
from pageindex.utils import llm_completion, extract_json

CATALOG_VERSION = 1
DEFAULT_DOC_TOP_K = 10


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


def list_tree_paths(dir_path, pattern='*_structure.json'):
    """列出目录中的树结构文件。"""
    path = Path(dir_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到目录: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"不是目录: {path}")

    paths = sorted(path.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"目录中未找到匹配 {pattern} 的树结构文件: {path}")
    return paths


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


def build_doc_catalog_entry(tree_path, model):
    """为单个树结构文件构建目录索引条目。"""
    tree = load_tree_structure(tree_path)
    stat = tree_path.stat()
    doc_name = tree.get('doc_name') if isinstance(tree, dict) else None
    doc_name = normalize_text(doc_name) or tree_path.name
    doc_description = get_doc_description(tree, tree_path, model)

    return {
        'tree_path': str(tree_path),
        'doc_name': doc_name,
        'doc_description': doc_description,
        'mtime_ns': stat.st_mtime_ns,
        'size': stat.st_size,
    }


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


def save_doc_catalog(catalog_path, entries):
    """保存文档目录索引。"""
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'version': CATALOG_VERSION,
        'entries': entries,
    }
    with open(catalog_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def sync_doc_catalog(tree_dir, catalog_path, model, rebuild=False):
    """同步目录中的文档索引信息。"""
    tree_paths = list_tree_paths(tree_dir)
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
        entries.append(build_doc_catalog_entry(tree_path, model))
        changed = True

    if len(entries) != len(cached_entries):
        changed = True

    entries.sort(key=lambda item: item['tree_path'])

    if changed:
        save_doc_catalog(catalog_path, entries)

    return entries


def get_structure_nodes(tree):
    """提取真正的树节点列表，兼容 PageIndex 标准输出格式。"""
    if isinstance(tree, dict) and 'structure' in tree:
        return tree['structure']
    return tree


def tree_search(query, tree, model):
    """使用 LLM 在树结构中搜索相关节点"""
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

    search_prompt = f"""你是一个文档检索专家。给定一个问题和文档的树结构，你的任务是找到所有可能包含答案的节点。

问题: {query}

{doc_info_text}

文档树结构:
{json.dumps(tree_without_text, indent=2, ensure_ascii=False)}

请以以下 JSON 格式回复:
{{
    "thinking": "<你的思考过程，解释哪些节点与问题相关>",
    "node_list": ["node_id_1", "node_id_2", ..., "node_id_n"]
}}

直接返回最终的 JSON 结构。不要输出其他内容。"""

    result = llm_completion(model, search_prompt)
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

    selection_prompt = f"""你是一个多文档检索助手。给定一个问题和一组文档描述，请挑选最可能包含答案的文档。

问题: {query}

文档列表:
{json.dumps(documents, indent=2, ensure_ascii=False)}

请返回 JSON，格式如下:
{{
    "thinking": "<你的筛选思路>",
    "doc_list": ["doc_0001", "doc_0002"]
}}

要求:
1. `doc_list` 按相关性从高到低排序。
2. 最多返回 {doc_top_k} 个文档。
3. 如果没有相关文档，返回空列表。
4. 只返回最终 JSON，不要输出其他内容。"""

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


def create_node_mapping(tree):
    """创建从 node_id 到节点的映射"""
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
    return node_map


def get_relevant_content(node_list, tree):
    """从相关节点中提取内容"""
    # 创建节点映射
    node_map = create_node_mapping(tree)

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


def search_single_tree(query, tree, model):
    """对单个树结构执行检索并提取节点内容。"""
    search_result = tree_search(query, tree, model)
    if 'node_list' not in search_result:
        return search_result, []

    relevant_nodes = get_relevant_content(search_result['node_list'], tree)
    return search_result, relevant_nodes


def search_tree_directory(query, selected_entries, model):
    """对筛选出的多个树结构逐个执行检索。"""
    all_results = []

    for entry in selected_entries:
        tree_path = Path(entry['tree_path'])
        tree = load_tree_structure(tree_path)
        source_name = entry['doc_name']

        print(f"\n📄 检索文档: {source_name}")
        search_result, relevant_nodes = search_single_tree(query, tree, model)

        if 'node_list' not in search_result:
            print(f"❌ 搜索失败，无法解析结果: {tree_path}")
            print(f"原始结果: {search_result}")
            continue

        print(f"找到 {len(search_result['node_list'])} 个相关节点")
        if 'thinking' in search_result:
            print(f"思考过程: {search_result['thinking'][:200]}...")

        for node in relevant_nodes:
            node['doc_name'] = source_name
            node['tree_path'] = str(tree_path)

        all_results.append({
            'path': tree_path,
            'tree': tree,
            'search_result': search_result,
            'relevant_nodes': relevant_nodes,
        })

    return all_results


def generate_answer(query, context, model):
    """基于检索到的内容生成答案"""
    answer_prompt = f"""基于以下上下文回答问题。如果上下文中没有相关信息，请明确说明。

问题: {query}

上下文:
{context}

请提供清晰、简洁的答案，仅基于提供的上下文。"""

    return llm_completion(model, answer_prompt)


def format_node_context(node):
    """将节点格式化为适合问答的上下文块。"""
    doc_prefix = ""
    if node.get('doc_name'):
        doc_prefix = f"[文档: {node['doc_name']}] "
    header = f"{doc_prefix}[{node['node_id']}] {node['title']} (页 {node['page']})"
    return f"{header}\n{node['content']}"


def build_context(relevant_nodes, max_context):
    """按最大长度限制拼接上下文。"""
    context_parts = []
    total_length = 0

    for node in relevant_nodes:
        formatted_node = format_node_context(node)
        if total_length + len(formatted_node) > max_context:
            remaining = max_context - total_length
            if remaining > 0:
                context_parts.append(formatted_node[:remaining] + "...")
            break
        context_parts.append(formatted_node)
        total_length += len(formatted_node)

    return "\n\n---\n\n".join(context_parts)


def main():
    parser = argparse.ArgumentParser(description='PageIndex 检索脚本')
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--tree_path', type=str,
                      help='PageIndex 树结构 JSON 文件路径')
    source_group.add_argument('--tree_dir', type=str,
                      help='包含多个 PageIndex 树结构 JSON 文件的目录')
    parser.add_argument('--query', type=str, required=True,
                      help='检索问题')
    parser.add_argument('--model', type=str, default='deepseek/deepseek-chat',
                      help='使用的 LLM 模型')
    parser.add_argument('--doc_top_k', type=int, default=DEFAULT_DOC_TOP_K,
                      help='目录检索时，进入树搜索的最大文档数')
    parser.add_argument('--catalog_path', type=str, default=None,
                      help='目录检索时使用的文档描述 catalog 路径')
    parser.add_argument('--rebuild_catalog', action='store_true',
                      help='强制重建目录检索使用的文档描述 catalog')
    parser.add_argument('--max_context', type=int, default=10000,
                      help='最大上下文字符数')

    args = parser.parse_args()
    if args.doc_top_k <= 0:
        raise ValueError("--doc_top_k 必须大于 0")

    print(f"🔍 检索问题: {args.query}")

    if args.tree_path:
        print(f"📄 加载树结构: {args.tree_path}")
        tree = load_tree_structure(args.tree_path)
        print("✓ 树结构加载完成\n")

        print("正在搜索相关节点...")
        search_result, relevant_nodes = search_single_tree(args.query, tree, args.model)

        if 'node_list' not in search_result:
            print("❌ 搜索失败，无法解析结果")
            print(f"原始结果: {search_result}")
            return

        print(f"\n📊 检索结果 (找到 {len(search_result['node_list'])} 个相关节点):")
        if 'thinking' in search_result:
            print(f"思考过程: {search_result['thinking'][:200]}...\n")
    else:
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

        print("\n正在搜索入选文档中的相关节点...")
        search_results = search_tree_directory(args.query, selected_entries, args.model)
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
    answer = generate_answer(args.query, context, args.model)

    print("\n" + "="*60)
    print("答案:")
    print("="*60)
    print(answer)
    print("="*60)


if __name__ == "__main__":
    main()
