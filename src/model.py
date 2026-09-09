"""Small OpenAI-compatible Chat Completions adapter."""

import os

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


class ModelError(RuntimeError):
    """Safe, actionable model error suitable for display without response bodies."""


class OpenAIModel:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        model = os.environ.get("OPENAI_MODEL", "").strip()
        if not key or not model:
            raise ModelError("请配置 OPENAI_API_KEY 和 OPENAI_MODEL 环境变量。")
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
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
