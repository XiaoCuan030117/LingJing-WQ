from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from src.model import ModelError, OpenAIModel
from tests.conftest import FakeModel, response, tool_call

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def launch(monkeypatch, tmp_path):
    def create(*responses):
        model = FakeModel(*responses)
        model.client = SimpleNamespace(close=Mock())
        monkeypatch.setattr(OpenAIModel, "from_env", lambda: model)
        app = AppTest.from_file(str(APP), default_timeout=10).run()
        app.text_input(key="workspace").set_value(str(tmp_path)).run()
        assert not app.exception
        return app, model

    return create


def click(app, prefix):
    button = next(button for button in app.button if (button.key or "").startswith(prefix))
    button.click().run()
    assert not app.exception


def test_file_summary_and_followup_context(launch, tmp_path):
    (tmp_path / "notes.txt").write_text("Project has seven milestones.", encoding="utf-8")
    app, model = launch(
        response(tool_call("read", "read_file", path="notes.txt")),
        response(content="项目有七个里程碑。"),
        response(content="七个。"),
    )
    app.chat_input[0].set_value("总结 notes.txt").run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert app.expander[0].label == "read_file · 成功"
    assert not app.chat_input[0].disabled
    app.chat_input[0].set_value("刚才说有几个？").run()
    assert len(app.chat_message) == 4
    assert any(m.get("content") == "项目有七个里程碑。" for m in model.requests[-1])
    assert any(m["role"] == "tool" for m in model.requests[-1])
    app.run()
    assert len(model.requests) == 3


def test_approval_queue_reruns_and_exactly_once(launch, tmp_path):
    app, model = launch(
        response(
            tool_call("a", "write_file", path="a.txt", content="first"),
            tool_call("b", "write_file", path="b.txt", content="second"),
        ),
        response(content="第一个文件写入成功，第二个未获授权。"),
    )
    app.chat_input[0].set_value("创建两个文件").run()
    agent = app.session_state.agent
    first_token = agent.waiting.token
    assert agent.state == "waiting_approval"
    assert app.chat_input[0].disabled
    assert app.text_input(key="workspace").disabled
    assert app.button(key="reset").disabled
    assert any(code.value == "first" for code in app.code)
    assert not (tmp_path / "a.txt").exists()
    app.run()
    assert agent.waiting.token == first_token
    assert len(model.requests) == 1
    click(app, "allow_")
    assert (tmp_path / "a.txt").read_text() == "first"
    assert not (tmp_path / "b.txt").exists()
    assert agent.waiting.token != first_token
    assert len(model.requests) == 1
    (tmp_path / "a.txt").write_text("changed after execution")
    app.session_state.decision = (first_token, True)
    app.run()
    assert (tmp_path / "a.txt").read_text() == "changed after execution"
    click(app, "deny_")
    assert agent.state == "completed"
    assert not (tmp_path / "b.txt").exists()
    assert not app.chat_input[0].disabled
    app.run()
    assert len(model.requests) == 2
    assert len(agent.results) == 2


@pytest.mark.parametrize("allow", [False, True])
def test_shell_approval_has_real_side_effect_only_when_allowed(launch, tmp_path, allow):
    # The project's current target is PowerShell on Windows; retain POSIX support.
    import os

    command = "Set-Content marker.txt ok" if os.name == "nt" else "echo ok > marker.txt"
    app, model = launch(
        response(tool_call("shell", "run_shell", command=command)),
        response(content="已处理本次命令。"),
    )
    app.chat_input[0].set_value("运行命令").run()
    assert not (tmp_path / "marker.txt").exists()
    assert any(code.value == command for code in app.code)
    click(app, "allow_" if allow else "deny_")
    assert (tmp_path / "marker.txt").exists() == allow
    result = app.session_state.agent.results[0]
    assert result["ok"] == allow
    app.run()
    assert len(model.requests) == 2


def test_overwrite_preview_and_denial(launch, tmp_path):
    (tmp_path / "existing.txt").write_text("original")
    app, _ = launch(
        response(tool_call("write", "write_file", path="existing.txt", content="replacement")),
        response(content="未修改。"),
    )
    app.chat_input[0].set_value("更新文件").run()
    assert any("覆盖" in warning.value for warning in app.warning)
    assert any(code.value == "replacement" for code in app.code)
    click(app, "deny_")
    assert (tmp_path / "existing.txt").read_text() == "original"


def test_failure_reset_and_new_workspace(launch, tmp_path):
    app, model = launch(ModelError("测试网络失败"), response(content="重新开始成功。"))
    app.chat_input[0].set_value("第一次任务").run()
    assert not app.exception
    assert any("测试网络失败" in error.value for error in app.error)
    assert app.chat_input[0].disabled
    app.run()
    assert len(model.requests) == 1
    app.button(key="reset").click().run()
    model.client.close.assert_called_once()
    assert not app.chat_message
    assert not app.text_input(key="workspace").disabled
    app.chat_input[0].set_value("新任务").run()
    assert app.session_state.agent.state == "completed"
    assert not any(m.get("content") == "第一次任务" for m in model.requests[-1])


def test_invalid_directory_does_not_call_model(launch, tmp_path):
    app, model = launch()
    app.text_input(key="workspace").set_value(str(tmp_path / "missing")).run()
    app.chat_input[0].set_value("读取文件").run()
    assert not app.exception
    assert app.error
    assert app.session_state.agent is None
    assert not model.requests


def test_missing_configuration_is_visible(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=10).run()
    app.text_input(key="workspace").set_value(str(tmp_path)).run()
    app.chat_input[0].set_value("你好").run()
    assert not app.exception
    assert any("OPENAI_API_KEY" in error.value for error in app.error)
    assert app.session_state.agent is None


def test_sessions_do_not_share_history(launch):
    first, _ = launch(response(content="第一段对话。"))
    first.chat_input[0].set_value("记住这个任务").run()
    second = AppTest.from_file(str(APP), default_timeout=10).run()
    assert second.session_state.agent is None
    assert not second.chat_message
