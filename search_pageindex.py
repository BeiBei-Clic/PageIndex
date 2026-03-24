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
    header = f"[{node['node_id']}] {node['title']} (页 {node['page']})"
    return f"{header}\n{node['content']}"


def main():
    parser = argparse.ArgumentParser(description='PageIndex 检索脚本')
    parser.add_argument('--tree_path', type=str, required=True,
                      help='PageIndex 树结构 JSON 文件路径')
    parser.add_argument('--query', type=str, required=True,
                      help='检索问题')
    parser.add_argument('--model', type=str, default='deepseek/deepseek-chat',
                      help='使用的 LLM 模型')
    parser.add_argument('--max_context', type=int, default=10000,
                      help='最大上下文字符数')

    args = parser.parse_args()

    # 加载树结构
    print(f"📄 加载树结构: {args.tree_path}")
    tree = load_tree_structure(args.tree_path)
    print("✓ 树结构加载完成\n")

    # 树搜索
    print(f"🔍 检索问题: {args.query}")
    print("正在搜索相关节点...")
    search_result = tree_search(args.query, tree, args.model)

    if 'node_list' not in search_result:
        print("❌ 搜索失败，无法解析结果")
        print(f"原始结果: {search_result}")
        return

    print(f"\n📊 检索结果 (找到 {len(search_result['node_list'])} 个相关节点):")
    if 'thinking' in search_result:
        print(f"思考过程: {search_result['thinking'][:200]}...\n")

    # 获取相关内容
    relevant_nodes = get_relevant_content(search_result['node_list'], tree)

    if not relevant_nodes:
        print("❌ 已找到相关 node_id，但未能从树结构中提取任何节点内容。")
        print("请检查 JSON 是否使用了标准的 `structure` 根字段，以及节点是否包含 `text` 或 `summary`。")
        return

    for i, node in enumerate(relevant_nodes, 1):
        print(f"{i}. [{node['node_id']}] 页 {node['page']}: {node['title']}")

    # 组合上下文
    context_parts = []
    total_length = 0
    for node in relevant_nodes:
        formatted_node = format_node_context(node)
        if total_length + len(formatted_node) > args.max_context:
            # 截断最后一个节点以适应最大长度
            remaining = args.max_context - total_length
            if remaining > 0:
                context_parts.append(formatted_node[:remaining] + "...")
            break
        context_parts.append(formatted_node)
        total_length += len(formatted_node)

    context = "\n\n---\n\n".join(context_parts)

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
