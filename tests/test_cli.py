import shlex
import sys

from src.agent import Agent
from src.cli import main, run
from tests.conftest import FakeModel, response, tool_call


def test_cli_generate_and_execute_script(tools, tmp_path):
    filename = "hello.py"
    content = "print('hello agent')\n"
    executable = sys.executable.replace("'", "''")
    command = (
        f"& '{executable}' ./hello.py"
        if tools.is_powershell
        else f"{shlex.quote(sys.executable)} ./hello.py"
    )
    model = FakeModel(
        response(tool_call("write", "write_file", path=filename, content=content)),
        response(tool_call("run", "run_shell", command=command)),
        response(content="脚本运行成功，输出 hello agent。"),
    )
    output = []
    agent = Agent(model, tools)
    assert run(agent, "创建并运行脚本", read_input=lambda _: "y", output=output.append) == 0
    assert (tmp_path / filename).read_text() == content
    assert agent.results[1]["ok"], agent.results[1]
    assert agent.results[1]["data"]["stdout"].strip() == "hello agent"
    assert any("overwrite" in line for line in output)
    assert any("hello agent" in line for line in output)


def test_cli_eof_denies(tools, tmp_path):
    def eof(_):
        raise EOFError

    model = FakeModel(
        response(tool_call("write", "write_file", path="denied", content="x")),
        response(content="未写入。"),
    )
    assert run(Agent(model, tools), "写入", read_input=eof, output=lambda _: None) == 0
    assert not (tmp_path / "denied").exists()


def test_missing_config_exits_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert main(["--workspace", str(tmp_path), "总结文件"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err
