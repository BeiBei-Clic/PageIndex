#!/usr/bin/env python3
"""Reproducible coverage experiments for agent_pageindex.py.

These experiments keep agent_pageindex.py as the execution target, but stub out
network-bound dependencies so the control flow can be exercised locally and
reproducibly.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import runpy
import sys
import types
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pathtracer.reporter import CoverageReporter
from pathtracer.tracer import PathTracer

TARGET_FILE = "agent_pageindex.py"


def _make_tool(name: str = "search_pageindex"):
    def fake_tool(*args, **kwargs):
        return {"name": name, "args": kwargs}

    fake_tool.name = name
    return fake_tool


def _simple_namespace(class_name: str, **kwargs: Any):
    cls = type(class_name, (), {})
    obj = cls()
    for key, value in kwargs.items():
        setattr(obj, key, value)
    return obj


def _build_agent_for_scenario(scenario: str):
    if scenario == "normal_string":
        class FakeAgent:
            def invoke(self, agent_input):
                return {
                    "messages": [
                        types.SimpleNamespace(content="final answer from normal mode")
                    ]
                }

        return FakeAgent()

    if scenario == "normal_list":
        class FakeAgent:
            def invoke(self, agent_input):
                return {
                    "messages": [
                        types.SimpleNamespace(
                            content=[
                                "alpha fragment",
                                {"type": "text", "text": "beta fragment"},
                            ]
                        )
                    ]
                }

        return FakeAgent()

    if scenario == "verbose_mixed":
        class FakeAgent:
            def stream(self, agent_input, stream_mode="updates"):
                # Trigger the "chunk is not dict" guard.
                yield "not-a-dict"

                # Trigger the "payload is not dict" guard.
                yield {"bad-step": "bad-payload"}

                # Trigger message-loop cases: duplicate message, tool call,
                # empty content, ToolMessage, and AIMessage.
                tool_call_message = _simple_namespace(
                    "ToolCallMessage",
                    id="call-1",
                    tool_calls=[
                        {"name": "search_pageindex", "args": {"query": "test"}}
                    ],
                    content="ignored because tool_calls is present",
                )
                duplicate_message = _simple_namespace(
                    "ToolCallMessage",
                    id="call-1",
                    tool_calls=[],
                    content="duplicate",
                )
                empty_message = _simple_namespace(
                    "EmptyMessage",
                    id="empty-1",
                    tool_calls=[],
                    content=None,
                )
                tool_message = _simple_namespace(
                    "ToolMessage",
                    id="tool-1",
                    tool_calls=[],
                    name="search_pageindex",
                    content="tool output body",
                )
                ai_message = _simple_namespace(
                    "AIMessage",
                    id="ai-1",
                    tool_calls=[],
                    content="assistant stream output",
                )

                yield {
                    "stream-step": {
                        "messages": [
                            tool_call_message,
                            duplicate_message,
                            empty_message,
                            tool_message,
                            ai_message,
                        ]
                    }
                }

        return FakeAgent()

    raise ValueError(f"Unsupported scenario: {scenario}")


@contextlib.contextmanager
def _installed_fake_modules(scenario: str):
    saved_modules = {
        name: sys.modules.get(name)
        for name in (
            "langchain",
            "langchain.agents",
            "langchain.chat_models",
            "dotenv",
            "pageindex",
            "pageindex.search",
        )
    }

    fake_langchain = types.ModuleType("langchain")
    fake_langchain.__path__ = []

    fake_agents = types.ModuleType("langchain.agents")
    fake_chat_models = types.ModuleType("langchain.chat_models")
    fake_dotenv = types.ModuleType("dotenv")
    fake_pageindex = types.ModuleType("pageindex")
    fake_pageindex.__path__ = []
    fake_search = types.ModuleType("pageindex.search")

    fake_agents.create_agent = lambda *args, **kwargs: _build_agent_for_scenario(
        scenario
    )
    fake_chat_models.init_chat_model = lambda *args, **kwargs: "fake-chat-model"
    fake_dotenv.load_dotenv = lambda *args, **kwargs: None

    fake_search.DEFAULT_DOC_TOP_K = 3
    fake_search.DEFAULT_MAX_CONCURRENCY = 2
    fake_search.search_pageindex = _make_tool()

    sys.modules["langchain"] = fake_langchain
    sys.modules["langchain.agents"] = fake_agents
    sys.modules["langchain.chat_models"] = fake_chat_models
    sys.modules["dotenv"] = fake_dotenv
    sys.modules["pageindex"] = fake_pageindex
    sys.modules["pageindex.search"] = fake_search

    try:
        yield
    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def run_scenario(scenario: str, output_path: Path) -> dict[str, Any]:
    tracer = PathTracer().trace_file(TARGET_FILE)
    reporter = CoverageReporter()

    original_argv = sys.argv[:]
    original_api_key = os.environ.get("DEEPSEEK_API_KEY")

    try:
        with _installed_fake_modules(scenario):
            os.environ["DEEPSEEK_API_KEY"] = "fake-key"
            sys.argv = [TARGET_FILE, "--query", "test"]
            if scenario == "verbose_mixed":
                sys.argv.append("--verbose")
            elif scenario == "normal_string":
                sys.argv.extend(["--doc-top-k", "3"])
            elif scenario == "normal_list":
                sys.argv.extend(["--doc-top-k", "5"])

            with tracer, contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(TARGET_FILE, run_name="__main__")

        report = reporter.analyze(TARGET_FILE, tracer)
        report_json = reporter.format_report_json(report)
        output_path.write_text(report_json + "\n", encoding="utf-8")

        return json.loads(report_json)
    finally:
        sys.argv = original_argv
        if original_api_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = original_api_key
        # run_path executed as __main__, but imported modules are already restored
        # in _installed_fake_modules; keep the process namespace clean here too.
        if "__main__" in sys.modules and getattr(
            sys.modules["__main__"], "__file__", ""
        ).endswith(TARGET_FILE):
            sys.modules.pop("__main__", None)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate reproducible coverage JSON for agent_pageindex.py"
    )
    parser.add_argument(
        "--scenario",
        choices=["normal_string", "verbose_mixed", "normal_list"],
        required=True,
        help="Experiment scenario to execute.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to the JSON report file.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = run_scenario(args.scenario, output_path)
    branches = data["file_reports"][TARGET_FILE]["executed_branches"]
    branch_lines = [item["line_no"] for item in branches]
    print(
        json.dumps(
            {
                "scenario": args.scenario,
                "coverage_percentage": data["coverage_percentage"],
                "executed_branches": data["executed_branches"],
                "total_branches": data["total_branches"],
                "branch_lines": branch_lines,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
