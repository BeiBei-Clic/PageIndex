"""测试两个 LLM 提供商 (deepseek, ai) 连通性：普通文本调用 + 结构化输出"""

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from pageindex.llm import create_llm, PROVIDERS


class DocSelection(BaseModel):
    """Document selection result in JSON format."""
    thinking: str = Field(description="Brief reasoning for document selection")
    doc_list: list[str] = Field(description="List of selected document names, ordered by relevance")


for provider_name in PROVIDERS:
    print(f"\n{'='*40}")
    print(f"  提供商: {provider_name}")
    print(f"{'='*40}")

    llm = create_llm(provider=provider_name)

    # 1) 普通文本调用
    print("\n--- 普通文本调用 ---")
    resp = llm.invoke([HumanMessage(content="Say hello in one sentence.")])
    print(resp.content)

    # 2) 结构化输出 json_mode
    print("\n--- 结构化输出 json_mode ---")
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

    print(f"\n✓ {provider_name} 提供商连接正常")
