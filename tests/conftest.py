import json

import pytest

from src.tools import Tools


@pytest.fixture(autouse=True)
def isolate_model_configuration(monkeypatch, tmp_path):
    # Tests must never read the developer's credentials or call a paid service.
    monkeypatch.setattr("src.model.ENV_FILE", tmp_path / ".env")
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)


def tool_call(call_id, name, **arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def response(*calls, content=None):
    return {
        "role": "assistant",
        "content": content,
        **({"tool_calls": list(calls)} if calls else {}),
    }


class FakeModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def tools(tmp_path):
    return Tools(tmp_path)
