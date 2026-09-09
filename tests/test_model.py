import json
import os

import httpx
import pytest
from openai import OpenAI

from src.agent import Agent
from src.model import ModelError, OpenAIModel
from src.tools import tool_schemas


def client_with(handler):
    return OpenAI(
        api_key="test-key",
        base_url="https://test.invalid/v1",
        timeout=60,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_sdk_request_and_tool_response():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert body["model"] == "test-model"
        assert {tool["function"]["name"] for tool in body["tools"]} == {
            "read_file",
            "write_file",
            "run_shell",
            "ask_user",
        }
        return httpx.Response(
            200,
            json={
                "id": "completion-1",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"notes.txt"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    with client_with(handler) as client:
        result = OpenAIModel(client, "test-model").complete(
            [{"role": "user", "content": "总结文件"}], tool_schemas()
        )
    assert result["tool_calls"][0]["id"] == "call-1"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_api_error_safe_and_no_retries(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret-response-body"}})

    with client_with(handler) as client, pytest.raises(ModelError) as error:
        OpenAIModel(client, "test-model").complete([], tool_schemas())
    assert str(status) in str(error.value)
    assert "secret-response-body" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("error_class", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_errors(error_class):
    def handler(request):
        raise error_class("private details", request=request)

    with client_with(handler) as client, pytest.raises(ModelError) as error:
        OpenAIModel(client, "test-model").complete([], tool_schemas())
    assert "private details" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {
            "choices": [
                {"finish_reason": "length", "message": {"role": "assistant", "content": "partial"}}
            ]
        },
    ],
)
def test_incomplete_model_reply(body):
    with client_with(lambda _: httpx.Response(200, json=body)) as client:
        with pytest.raises(ModelError):
            OpenAIModel(client, "test-model").complete([], tool_schemas())


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "company-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://test.invalid/v1")
    model = OpenAIModel.from_env()
    try:
        assert model.model == "company-model"
        assert str(model.client.base_url) == "https://test.invalid/v1/"
        assert model.client.max_retries == 0
        assert model.client.timeout == 60
    finally:
        model.client.close()


def test_dotenv_loads_quotes_comments_and_bom_without_changing_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="file-key${LITERAL}" # comment\n'
        "OPENAI_MODEL='file-model'\n"
        "OPENAI_BASE_URL=https://test.invalid/v1\n",
        encoding="utf-8-sig",
    )
    elsewhere = tmp_path / "workspace"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("OPENAI_MODEL=wrong-workspace-model\n")
    monkeypatch.chdir(elsewhere)
    model = OpenAIModel.from_env()
    try:
        assert model.model == "file-model"
        assert model.client.api_key == "file-key${LITERAL}"
        assert str(model.client.base_url) == "https://test.invalid/v1/"
        assert "OPENAI_API_KEY" not in os.environ
    finally:
        model.client.close()


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=file-key\nOPENAI_MODEL=file-model\n"
        "OPENAI_BASE_URL=https://file.invalid/v1\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.invalid/v1")
    model = OpenAIModel.from_env()
    try:
        assert model.client.api_key == "environment-key"
        assert model.model == "environment-model"
        assert str(model.client.base_url) == "https://environment.invalid/v1/"
    finally:
        model.client.close()


def test_dotenv_edits_apply_to_new_clients(tmp_path):
    for name in ("first-model", "second-model"):
        (tmp_path / ".env").write_text(f"OPENAI_API_KEY=test-key\nOPENAI_MODEL={name}\n")
        model = OpenAIModel.from_env()
        try:
            assert model.model == name
        finally:
            model.client.close()


@pytest.mark.parametrize(
    "content", ["", "OPENAI_API_KEY\nOPENAI_MODEL=", "OPENAI_API_KEY=test-key"]
)
def test_incomplete_dotenv_reports_missing_configuration(tmp_path, content):
    (tmp_path / ".env").write_text(content)
    with pytest.raises(ModelError, match="OPENAI_API_KEY"):
        OpenAIModel.from_env()


def test_sdk_agent_file_summary_round_trip(tools, tmp_path):
    (tmp_path / "notes.txt").write_text("Three tools: read, write, shell.", encoding="utf-8")
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "read-1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"notes.txt"}'},
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            result = body["messages"][-1]
            assert result["role"] == "tool"
            assert result["tool_call_id"] == "read-1"
            assert (
                json.loads(result["content"])["data"]["content"]
                == "Three tools: read, write, shell."
            )
            message = {"role": "assistant", "content": "The project has three basic tools."}
            finish_reason = "stop"
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            },
        )

    with client_with(handler) as client:
        agent = Agent(OpenAIModel(client, "test-model"), tools)
        agent.start("Summarize notes.txt")
        assert agent.advance() == "completed"
        assert agent.answer == "The project has three basic tools."
    assert len(requests) == 2
