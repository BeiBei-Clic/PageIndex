#!/usr/bin/env python3
"""Apply PR #35094 fix to langchain-deepseek package.

Fixes DeepSeek thinking-mode tool calling by injecting reasoning_content
into outgoing assistant tool-call messages.

Usage:
    python scripts/patch_langchain_deepseek.py
"""
import sys
from pathlib import Path

# patch 文件中的路径是相对于 .venv 的
PATCH_FILE = Path(__file__).resolve().parent.parent / "docs" / "langchain-deepseek-thinking-fix.patch"
TARGET_FILE = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "langchain_deepseek" / "chat_models.py"

if not TARGET_FILE.exists():
    print(f"错误: 找不到目标文件 {TARGET_FILE}")
    print("请先运行 uv pip install langchain-deepseek==1.0.1")
    sys.exit(1)

if not PATCH_FILE.exists():
    print(f"错误: 找不到 patch 文件 {PATCH_FILE}")
    sys.exit(1)

# 读取 patch 并替换路径
patch_text = PATCH_FILE.read_text(encoding="utf-8")
# 将 patch 中的绝对路径替换为实际路径
patch_text = patch_text.replace(
    "/tmp/langchain_deepseek_original/langchain_deepseek/chat_models.py",
    "/a/chat_models.py",
).replace(
    TARGET_FILE.as_posix(),
    "/b/chat_models.py",
)

# 读取当前文件内容
original = TARGET_FILE.read_text(encoding="utf-8")

# 检查是否已经打过 patch
if "_is_thinking_enabled" in original:
    print("patch 已经应用过，无需重复操作。")
    sys.exit(0)

# 直接应用修改：在 _DictOrPydantic 后面插入 helper 函数
marker1 = "_DictOrPydantic: TypeAlias = dict[str, Any] | BaseModel"
insert1 = """


def _is_thinking_enabled_from_extra_body(extra_body: Any) -> bool:
    if not isinstance(extra_body, dict):
        return False
    thinking = extra_body.get("thinking")
    return isinstance(thinking, dict) and thinking.get("type") == "enabled\""""

if marker1 not in original:
    print("错误: 找不到插入点 1，文件版本可能不匹配。")
    sys.exit(1)

original = original.replace(marker1, marker1 + insert1, 1)

# 在 validate_environment 的 return self 后插入新方法
marker2 = "            self.async_client = self.root_async_client.chat.completions\n        return self\n\n    def _get_request_payload("
insert2 = """            self.async_client = self.root_async_client.chat.completions
        return self

    def _is_thinking_enabled(
        self,
        payload: dict,
        kwargs: dict[str, Any],
    ) -> bool:
        if getattr(self, "model_name", None) == "deepseek-reasoner":
            return True
        extra_body = (
            payload.get("extra_body")
            or kwargs.get("extra_body")
            or getattr(self, "extra_body", None)
        )
        return _is_thinking_enabled_from_extra_body(extra_body)

    def _get_original_messages(
        self,
        input_: LanguageModelInput,
    ) -> list[BaseMessage] | None:
        if isinstance(input_, list):
            return input_
        try:
            prompt_value = self._convert_input(input_)
            return prompt_value.to_messages()
        except (AttributeError, TypeError, ValueError):
            return None

    def _coerce_deepseek_message_content(self, msg: dict) -> None:
        if msg.get("role") == "tool" and isinstance(msg.get("content"), list):
            msg["content"] = json.dumps(msg["content"])
            return
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
            text_parts = [
                block.get("text", "")
                for block in msg["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            msg["content"] = "".join(text_parts)

    def _inject_reasoning_content_if_needed(
        self,
        *,
        msg: dict,
        msg_index: int,
        original_msgs: list[BaseMessage] | None,
        thinking_enabled: bool,
    ) -> None:
        if not thinking_enabled:
            return
        if msg.get("role") != "assistant":
            return
        if msg.get("tool_calls") is None:
            return
        if "reasoning_content" in msg:
            return
        rc = ""
        if original_msgs is not None and msg_index < len(original_msgs):
            ak = getattr(original_msgs[msg_index], "additional_kwargs", None)
            if isinstance(ak, dict):
                rc = ak.get("reasoning_content") or ""
        msg["reasoning_content"] = rc

    def _prepare_payload_messages(
        self,
        payload: dict,
        *,
        original_msgs: list[BaseMessage] | None,
        thinking_enabled: bool,
    ) -> None:
        for i, msg in enumerate(payload["messages"]):
            self._coerce_deepseek_message_content(msg)
            self._inject_reasoning_content_if_needed(
                msg=msg,
                msg_index=i,
                original_msgs=original_msgs,
                thinking_enabled=thinking_enabled,
            )

    def _get_request_payload("""

if marker2 not in original:
    print("错误: 找不到插入点 2，文件版本可能不匹配。")
    sys.exit(1)

original = original.replace(marker2, insert2, 1)

# 修改 _get_request_payload 方法体
marker3 = """        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload["messages"]:"""
insert3 = """        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        thinking_enabled = self._is_thinking_enabled(payload, kwargs)
        original_msgs = self._get_original_messages(input_)

        self._prepare_payload_messages(
            payload,
            original_msgs=original_msgs,
            thinking_enabled=thinking_enabled,
        )

        for message in payload["messages"]:"""

if marker3 not in original:
    print("错误: 找不到插入点 3，文件版本可能不匹配。")
    sys.exit(1)

original = original.replace(marker3, insert3, 1)

TARGET_FILE.write_text(original, encoding="utf-8")
print(f"patch 已成功应用到 {TARGET_FILE}")
