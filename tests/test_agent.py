import json

import pytest

from src.agent import Agent
from src.model import ModelError
from tests.conftest import FakeModel, response, tool_call


def test_multistep_file_summary(tools, tmp_path):
    (tmp_path / "notes.txt").write_text("项目需要三个工具。", encoding="utf-8")
    model = FakeModel(
        response(tool_call("read-1", "read_file", path="notes.txt")),
        response(content="项目需要三个工具。"),
    )
    agent = Agent(model, tools)
    agent.start("总结 notes.txt")
    assert agent.advance() == "completed"
    message = model.requests[1][-1]
    assert message["tool_call_id"] == "read-1"
    assert json.loads(message["content"])["data"]["content"] == "项目需要三个工具。"
    assert agent.answer == "项目需要三个工具。"


def test_queue_pause_deny_resume_and_no_replay(tools, tmp_path):
    model = FakeModel(
        response(
            tool_call("write-1", "write_file", path="a", content="approved"),
            tool_call("write-2", "write_file", path="b", content="denied"),
            tool_call("read-1", "read_file", path="a"),
        ),
        response(content="a 已写入；b 被拒绝。"),
    )
    agent = Agent(model, tools)
    agent.start("创建文件")
    assert agent.advance() == "waiting_approval"
    token = agent.waiting.token
    assert not (tmp_path / "a").exists()
    assert agent.advance() == "waiting_approval"
    assert len(model.requests) == 1
    assert not agent.approve("wrong-token", True)
    assert agent.approve(token, True)
    (tmp_path / "a").write_text("changed after approval")
    assert not agent.approve(token, True)
    assert agent.advance() == "waiting_approval"
    assert not agent.approve(token, True)
    assert agent.approve(agent.waiting.token, False)
    assert agent.advance() == "completed"
    assert not (tmp_path / "b").exists()
    assert (tmp_path / "a").read_text() == "changed after approval"
    results = [json.loads(m["content"]) for m in model.requests[1] if m["role"] == "tool"]
    assert [r["tool_call_id"] for r in results] == ["write-1", "write-2", "read-1"]
    assert results[1]["error"]["type"] == "permission_denied"


def test_tool_failure_returned_for_model_correction(tools):
    malformed = tool_call("bad-json", "read_file", path="x")
    malformed["function"]["arguments"] = "{"
    model = FakeModel(
        response(tool_call("unknown", "delete_file"), malformed),
        response(tool_call("missing", "read_file", path="missing")),
        response(content="文件不存在，无法总结。"),
    )
    agent = Agent(model, tools)
    agent.start("总结")
    assert agent.advance() == "completed"
    assert [r["error"]["type"] for r in agent.results] == [
        "unknown_tool",
        "invalid_arguments",
        "FileNotFoundError",
    ]


@pytest.mark.parametrize(
    "limits,expected", [({"max_requests": 1}, "模型请求"), ({"max_tools": 1}, "工具调用")]
)
def test_loop_limits(tools, limits, expected):
    model = FakeModel(
        response(
            tool_call("1", "read_file", path="missing"),
            tool_call("2", "read_file", path="missing"),
        )
    )
    agent = Agent(model, tools, **limits)
    agent.start("测试上限")
    assert agent.advance() == "failed"
    assert expected in agent.error
    assert agent.request_count == 1
    assert agent.tool_count <= limits.get("max_tools", 20)


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {},
        response(),
        response(content=3),
        response({"id": "1", "type": "function", "function": {}}),
        response(tool_call("1", "read_file", path="a"), tool_call("1", "read_file", path="b")),
        ModelError("网络不可用"),
        RuntimeError("secret must not appear"),
    ],
)
def test_bad_model_response_stops_without_side_effects(tools, reply):
    agent = Agent(FakeModel(reply), tools)
    agent.start("测试错误")
    assert agent.advance() == "failed"
    assert agent.error
    assert "secret" not in agent.error
    assert agent.tool_count == 0


def test_duplicate_call_id_across_requests_fails(tools):
    call = tool_call("same", "read_file", path="missing")
    agent = Agent(FakeModel(response(call), response(call)), tools)
    agent.start("测试重复 ID")
    assert agent.advance() == "failed"
    assert agent.tool_count == 1


def test_empty_and_overlapping_tasks_rejected(tools):
    agent = Agent(FakeModel(), tools)
    with pytest.raises(ValueError):
        agent.start(" ")
    agent.start("task")
    with pytest.raises(ValueError):
        agent.start("replacement")


def test_followup_resets_limits_and_preserves_history(tools):
    model = FakeModel(response(content="first"), response(content="second"))
    agent = Agent(model, tools, max_requests=1)
    agent.start("one")
    agent.advance()
    old_run = agent.run_id
    agent.continue_task("two")
    assert agent.run_id != old_run
    assert agent.request_count == agent.tool_count == 0
    assert agent.advance() == "completed"
    assert agent.request_count == 1
    assert [m["content"] for m in model.requests[-1][1:]] == ["one", "first", "two"]


def test_followup_cannot_replace_waiting_or_failed_task(tools):
    agent = Agent(FakeModel(response(tool_call("w", "write_file", path="a", content="x"))), tools)
    agent.start("write")
    agent.advance()
    with pytest.raises(ValueError):
        agent.continue_task("replacement")
    assert agent.state == "waiting_approval"
    assert agent.waiting.call_id == "w"
    failed = Agent(FakeModel(ModelError("failed")), tools)
    failed.start("task")
    failed.advance()
    with pytest.raises(ValueError):
        failed.continue_task("retry")
