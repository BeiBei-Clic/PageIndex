# langchain-deepseek 思考模式修复

## 问题

`langchain-deepseek==1.0.1` 在使用 DeepSeek 思考模式（`deepseek-reasoner` 或 `extra_body.thinking.type=enabled`）进行 tool calling 时，会在后续请求中丢失 `reasoning_content` 字段，导致 DeepSeek API 返回 HTTP 400 错误：

```
Missing reasoning_content field in the assistant message …
```

该问题已在 [langchain-ai/langchain#35094](https://github.com/langchain-ai/langchain/pull/35094) 中修复，但截至本文撰写时尚未合并发版。

## 修复内容

在 `_get_request_payload` 构建请求时，对每条 assistant 消息检查是否包含 `tool_calls`。若思考模式已启用，则从原始 `AIMessage.additional_kwargs["reasoning_content"]` 中提取思考内容并注入回请求 payload。

新增以下方法：

| 方法 | 作用 |
|------|------|
| `_is_thinking_enabled_from_extra_body()` | 检测 `extra_body` 中是否启用了思考模式 |
| `_is_thinking_enabled()` | 综合判断当前是否处于思考模式（模型名或 extra_body） |
| `_get_original_messages()` | 从输入中提取原始消息列表 |
| `_coerce_deepseek_message_content()` | 将 tool/assistant 的列表内容转为字符串 |
| `_inject_reasoning_content_if_needed()` | 在带 `tool_calls` 的 assistant 消息中注入 `reasoning_content` |
| `_prepare_payload_messages()` | 统一调用上述处理 |

## 适用范围

- `langchain-deepseek==1.0.1`
- 仅影响思考模式 + tool calling 场景
- 不影响普通对话（非思考模式）的正常使用

## 应用方式

### 方式一：一键脚本（推荐）

安装完依赖后运行：

```bash
python scripts/patch_langchain_deepseek.py
```

脚本会自动检测 `.venv` 中的 `langchain_deepseek/chat_models.py` 并应用修改。重复运行会跳过。

### 方式二：手动 patch

```bash
# 确保已安装正确版本
uv pip install langchain-deepseek==1.0.1

# 找到文件位置
python -c "import langchain_deepseek; print(langchain_deepseek.__file__)"
# 输出类似: /path/to/.venv/Lib/site-packages/langchain_deepseek/__init__.py

# 应用 patch（需要根据实际路径调整 -p 参数）
cd .venv/Lib/site-packages
patch -p3 < docs/langchain-deepseek-thinking-fix.patch
```

## 验证

应用后运行以下命令确认修复成功：

```bash
python -c "
from langchain_deepseek import ChatDeepSeek
from langchain_deepseek.chat_models import _is_thinking_enabled_from_extra_body
from pydantic import SecretStr

assert _is_thinking_enabled_from_extra_body({'thinking': {'type': 'enabled'}}) == True
assert _is_thinking_enabled_from_extra_body({}) == False

model = ChatDeepSeek(model='deepseek-v4-flash', api_key=SecretStr('test'))
assert hasattr(model, '_is_thinking_enabled')
assert hasattr(model, '_prepare_payload_messages')

print('修复验证通过!')
"
```

## 清理

当 `langchain-deepseek` 官方发布包含此修复的新版本后，升级即可：

```bash
uv pip install --upgrade langchain-deepseek
```

升级后可删除 `scripts/patch_langchain_deepseek.py` 和 `docs/langchain-deepseek-thinking-fix.patch`。
