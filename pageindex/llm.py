"""LLM 提供商配置与工厂函数。"""

from langchain.chat_models import init_chat_model

PROVIDERS = {
    "deepseek": {
        "model_provider": "deepseek",
        "default_model": "deepseek-v4-flash",
    },
    "ai": {
        "model_provider": "openai",
        "base_url": "https://api.psydo.top/v1",
        "default_model": "gpt-5.5",
    },
}


def create_llm(provider="deepseek", model=None, temperature=0):
    cfg = PROVIDERS[provider]
    kwargs = {
        "model": model or cfg["default_model"],
        "model_provider": cfg["model_provider"],
        "temperature": temperature,
    }
    if "base_url" in cfg:
        kwargs["base_url"] = cfg["base_url"]
    return init_chat_model(**kwargs)
