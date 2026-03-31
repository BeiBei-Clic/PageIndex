#!/usr/bin/env python3
"""Minimal LangChain v1 agent for PageIndex QA."""
import argparse
import os
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from pageindex.search import DEFAULT_DOC_TOP_K, DEFAULT_MAX_CONCURRENCY
from search_pageindex import pageindex_qa

DEFAULT_TREE_DIR = "tests/results"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
PAGEINDEX_MODEL = "deepseek/deepseek-chat"

SYSTEM_PROMPT = """You are a concise document QA assistant.
Always call the `pageindex_qa` tool before answering questions about the indexed documents.
Base your final answer only on the tool result.
If the tool says it did not find enough information, say you do not know instead of guessing."""


def _extract_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        parts = []
        for item in payload:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return str(payload).strip()


def _print_verbose_stream(agent: Any, agent_input: dict) -> None:
    seen_messages: set[str] = set()

    for chunk in agent.stream(agent_input, stream_mode="updates"):
        if not isinstance(chunk, dict):
            continue
        for step_name, payload in chunk.items():
            if not isinstance(payload, dict):
                continue
            messages = payload.get("messages") or []
            for message in messages:
                message_id = getattr(message, "id", None) or f"{step_name}:{type(message).__name__}:{len(seen_messages)}"
                if message_id in seen_messages:
                    continue
                seen_messages.add(message_id)

                tool_calls = getattr(message, "tool_calls", None) or []
                if tool_calls:
                    for call in tool_calls:
                        print(f"[tool call] {call.get('name')}({call.get('args')})")
                    continue

                message_type = type(message).__name__
                content = _extract_text(getattr(message, "content", ""))
                if not content:
                    continue

                if message_type == "ToolMessage":
                    preview = content if len(content) <= 1200 else content[:1200] + "..."
                    tool_name = getattr(message, "name", "pageindex_qa")
                    print(f"[tool result] {tool_name}\n{preview}\n")
                    continue

                if message_type == "AIMessage":
                    print(f"[{step_name}] {content}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal LangChain v1 PageIndex agent")
    parser.add_argument("--query", type=str, required=True, help="Question for the agent")
    parser.add_argument("--tree-dir", type=str, default=DEFAULT_TREE_DIR, help="Directory containing *_structure.json files")
    parser.add_argument("--doc-top-k", type=int, default=DEFAULT_DOC_TOP_K, help="Maximum number of documents selected for tree search")
    parser.add_argument("--max-concurrency", type=int, default=DEFAULT_MAX_CONCURRENCY, help="Maximum number of documents searched concurrently")
    parser.add_argument("--catalog-path", type=str, default=None, help="Optional catalog path passed to PageIndex")
    parser.add_argument("--rebuild-catalog", action="store_true", help="Force rebuilding the PageIndex catalog")
    parser.add_argument("--max-context", type=int, default=10000, help="Maximum context length passed to PageIndex")
    parser.add_argument("--verbose", action="store_true", help="Print streaming tool activity")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set in the environment.")

    agent = create_agent(
        model=init_chat_model(
            model="deepseek-chat",
            model_provider="openai",
            base_url=DEEPSEEK_BASE_URL,
            api_key=api_key,
            temperature=0,
        ),
        tools=[pageindex_qa],
        system_prompt=SYSTEM_PROMPT,
    )

    catalog_instruction = (
        f"Set catalog_path to '{args.catalog_path}'."
        if args.catalog_path
        else "Leave catalog_path unset so the tool can use its default catalog path."
    )
    rebuild_flag = "true" if args.rebuild_catalog else "false"
    agent_input = {
        "messages": [{
            "role": "user",
            "content": (
                "Use the `pageindex_qa` tool to answer the following question.\n"
                f"When you call the tool, use tree_dir='{args.tree_dir}', model='{PAGEINDEX_MODEL}', "
                f"doc_top_k={args.doc_top_k}, max_concurrency={args.max_concurrency}, "
                f"max_context={args.max_context}, rebuild_catalog={rebuild_flag}. "
                f"{catalog_instruction}\n"
                f"Question: {args.query}"
            ),
        }],
    }

    if args.verbose:
        _print_verbose_stream(agent, agent_input)
        return

    result = agent.invoke(agent_input)
    if isinstance(result, dict):
        messages = result.get("messages") or []
        if messages:
            print(_extract_text(getattr(messages[-1], "content", messages[-1])))
            return
    print(_extract_text(result))


if __name__ == "__main__":
    main()
