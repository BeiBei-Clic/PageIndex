#!/usr/bin/env python3
"""
PageIndex 检索脚本
使用生成的树结构进行推理检索
"""
import argparse
from pathlib import Path

from pageindex.search import DEFAULT_DOC_TOP_K, DEFAULT_MAX_CONCURRENCY, search_tree_dir


def main():
    parser = argparse.ArgumentParser(description='PageIndex 目录检索脚本')
    parser.add_argument('--tree_dir', type=str, required=True, help='包含多个 PageIndex 树结构 JSON 文件的目录')
    parser.add_argument('--query', type=str, required=True, help='检索问题')
    parser.add_argument('--model', type=str, default='deepseek/deepseek-chat', help='使用的 LLM 模型')
    parser.add_argument('--doc_top_k', type=int, default=DEFAULT_DOC_TOP_K, help='目录检索时，进入树搜索的最大文档数')
    parser.add_argument('--max_concurrency', type=int, default=DEFAULT_MAX_CONCURRENCY, help='节点检索阶段的最大并发文档数')
    parser.add_argument('--catalog_path', type=str, default=None, help='目录检索时使用的文档描述 catalog 路径')
    parser.add_argument('--rebuild_catalog', action='store_true', help='强制重建目录检索使用的文档描述 catalog')
    parser.add_argument('--max_context', type=int, default=10000, help='最大上下文字符数')
    args = parser.parse_args()

    tree_dir = Path(args.tree_dir)
    catalog_path = Path(args.catalog_path) if args.catalog_path else tree_dir / '.pageindex_doc_catalog.json'

    print(f"🔍 检索问题: {args.query}")
    print(f"📁 加载树结构目录: {tree_dir}")
    print("⚙️ 正在执行文档筛选、节点检索与答案生成...")

    result = search_tree_dir(
        tree_dir=tree_dir,
        query=args.query,
        model=args.model,
        doc_top_k=args.doc_top_k,
        max_concurrency=args.max_concurrency,
        catalog_path=catalog_path,
        rebuild_catalog=args.rebuild_catalog,
        max_context=args.max_context,
    )

    for updated_path in result['catalog_updated_paths']:
        print(f"🧾 更新文档描述: {Path(updated_path).name}")

    print(f"✓ 文档 catalog 已准备完成，共 {len(result['catalog_entries'])} 个文件")
    print(f"📚 Catalog 路径: {result['catalog_path']}\n")

    print(f"📚 文档筛选结果 (从 {len(result['catalog_entries'])} 个文档中选择 {len(result['selected_entries'])} 个):")
    if 'thinking' in result['doc_selection_result']:
        print(f"思考过程: {result['doc_selection_result']['thinking'][:200]}...\n")

    if not result['selected_entries']:
        print("❌ 文档级筛选未命中任何相关文档。")
        if result['raw_doc_list']:
            print(f"模型返回的文档标识无效: {result['raw_doc_list']}")
        return

    for index, entry in enumerate(result['selected_entries'], 1):
        print(f"{index}. {entry['doc_name']} ({entry['tree_path']})")

    for item in result['search_results']:
        print(f"\n📄 检索文档: {item['doc_name']}")
        if not item['ok']:
            print(f"❌ 搜索失败，无法解析结果: {item['path']}")
            print(f"原始结果: {item['search_result']}")
            continue
        print(f"找到 {len(item['search_result'].get('node_list', []))} 个相关节点")
        if 'thinking' in item['search_result']:
            print(f"思考过程: {item['search_result']['thinking'][:200]}...")

    print(f"\n📊 目录检索结果 (共找到 {result['total_node_hits']} 个相关节点，提取 {len(result['relevant_nodes'])} 个有效上下文节点):")

    if not result['relevant_nodes']:
        print("❌ 未能从检索结果中提取任何节点内容。")
        print("请检查 JSON 是否使用了标准的 `structure` 根字段，以及节点是否包含 `text` 或 `summary`。")
        return

    for index, node in enumerate(result['relevant_nodes'], 1):
        doc_prefix = f"[{node['doc_name']}] " if node.get('doc_name') else ""
        print(f"{index}. {doc_prefix}[{node['node_id']}] 页 {node['page']}: {node['title']}")

    if not result['context'].strip():
        print("❌ 检索到了相关节点，但拼接后的上下文为空，已停止调用模型。")
        return

    print("\n" + "=" * 60)
    print("答案:")
    print("=" * 60)
    print(result['answer'] or "")
    print("=" * 60)


if __name__ == "__main__":
    main()
