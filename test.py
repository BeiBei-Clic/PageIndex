"""测试 ai 提供商 (gpt-5.5) 连通性：普通文本调用 + 结构化输出"""

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage


class DocSelection(BaseModel):
    """Document selection result in JSON format."""
    thinking: str = Field(description="Brief reasoning for document selection")
    doc_list: list[str] = Field(description="List of selected document names, ordered by relevance")


llm = init_chat_model(
    model="gpt-5.5",
    model_provider="openai",
    base_url="https://api.psydo.top/v1",
    temperature=0,
)

# 1) 普通文本调用
print("=== 普通文本调用 ===")
resp = llm.invoke([HumanMessage(content="Say hello in one sentence.")])
print(resp.content)
print()

# 2) 结构化输出 json_mode
print("=== 结构化输出 json_mode ===")
structured = llm.with_structured_output(DocSelection, method="json_mode")
result = structured.invoke([
    SystemMessage(content=(
        'Return a JSON object with:\n'
        '- "thinking": brief reasoning\n'
        '- "doc_list": list of selected document names, ordered by relevance'
    )),
    HumanMessage(content=(
        "Given a question about Swiss criminal procedure (StPO), "
        "select relevant documents from: OR, ZGB, StPO, BGG."
    ))
])
print(result)
print(type(result))
