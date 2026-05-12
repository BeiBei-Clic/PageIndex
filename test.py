"""DeepSeek 结构化输出经验总结

deepseek-v4-flash 不支持 tool_choice 和 json_schema，因此：

1. with_structured_output(schema)                — 默认 function_calling，因 tool_choice 报 400
2. with_structured_output(schema, method="json_schema") — DeepSeek API 不支持该 type，报 422
3. with_structured_output(schema, method="json_mode")   — ✅ 唯一可行方案

json_mode 方案要点：
- API 层通过 response_format: {type: "json_object"} 强制返回合法 JSON
- 必须在 prompt 中包含 "json" 一词，否则 DeepSeek API 报 400
- 必须在 SystemMessage 中描述期望的 JSON 字段名，否则模型自由发挥字段名导致 Pydantic 解析失败
- LangChain 自动将 JSON 解析为 Pydantic 对象

相关 GitHub Issues:
- https://github.com/langchain-ai/langchain/issues/29282
- https://github.com/langchain-ai/langchain/issues/31403
"""

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage


class DocSelection(BaseModel):
    """Document selection result in JSON format."""
    thinking: str = Field(description="Brief reasoning for document selection")
    doc_list: list[str] = Field(description="List of selected document IDs, ordered by relevance")


llm = init_chat_model("deepseek:deepseek-v4-flash", temperature=0)
structured = llm.with_structured_output(DocSelection, method="json_mode")

result = structured.invoke([
    SystemMessage(content=(
        'Return a JSON object with:\n'
        '- "thinking": brief reasoning\n'
        '- "doc_list": list of selected document IDs, ordered by relevance'
    )),
    HumanMessage(content=(
        "Given a question about Swiss criminal procedure (StPO), "
        "select relevant documents from: OR, ZGB, StPO, BGG."
    ))
])
print(result)
print(type(result))
