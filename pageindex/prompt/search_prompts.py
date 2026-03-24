TREE_SEARCH_PROMPT = """你是一个文档检索专家。给定一个问题和文档的树结构，你的任务是找到所有可能包含答案的节点。

问题: {query}

{doc_info_text}

文档树结构:
{tree_structure_json}

请以以下 JSON 格式回复:
{{
    "thinking": "<你的思考过程，解释哪些节点与问题相关>",
    "node_list": ["node_id_1", "node_id_2", ..., "node_id_n"]
}}

直接返回最终的 JSON 结构。不要输出其他内容。"""


DOC_SELECTION_PROMPT = """你是一个多文档检索助手。给定一个问题和一组文档描述，请挑选最可能包含答案的文档。

问题: {query}

文档列表:
{documents_json}

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


ANSWER_PROMPT = """基于以下上下文回答问题。如果上下文中没有相关信息，请明确说明。

问题: {query}

上下文:
{context}

请提供清晰、简洁的答案，仅基于提供的上下文。"""
