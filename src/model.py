"""Small OpenAI-compatible Chat Completions adapter."""

import os
from pathlib import Path

from dotenv import dotenv_values
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class ModelError(RuntimeError):
    """Safe, actionable model error suitable for display without response bodies."""


class OpenAIModel:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls):
        # Read the repository file, never a tool workspace's .env. Do not mutate
        # os.environ: a new WebUI conversation must see edits made to the file.
        try:
            config = {
                **dotenv_values(ENV_FILE, encoding="utf-8-sig", interpolate=False),
                **os.environ,
            }
        except (OSError, UnicodeError) as exc:
            raise ModelError("无法读取项目 .env；请检查文件权限和 UTF-8 编码。") from exc
        key = (config.get("OPENAI_API_KEY") or "").strip()
        model = (config.get("OPENAI_MODEL") or "").strip()
        if not key or not model:
            raise ModelError("请在项目 .env 或环境变量中配置 OPENAI_API_KEY 和 OPENAI_MODEL。")
        base_url = (config.get("OPENAI_BASE_URL") or "").strip() or None
        return cls(OpenAI(api_key=key, base_url=base_url, timeout=60, max_retries=0), model)

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=tools
            )
        except APITimeoutError as exc:
            raise ModelError("模型请求超时；请检查网络或稍后重新发起任务。") from exc
        except APIConnectionError as exc:
            raise ModelError("模型连接失败；请检查网络与 OPENAI_BASE_URL。") from exc
        except APIStatusError as exc:
            raise ModelError(
                f"模型服务返回 HTTP {exc.status_code}；请检查密钥、模型、额度和工具调用兼容性。"
            ) from exc
        try:
            choice = response.choices[0]
            if choice.finish_reason not in {"stop", "tool_calls"}:
                raise ModelError("模型响应未正常完成；请缩小任务或检查模型支持。")
            message = choice.message
            result = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                result["tool_calls"] = [
                    call.model_dump(exclude_none=True) for call in message.tool_calls
                ]
            return result
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ModelError(
                "模型响应格式无效；请检查服务是否支持 Chat Completions 工具调用。"
            ) from exc
