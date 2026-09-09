import json
import shlex
import sys
import time

import pytest

from src.tools import FILE_LIMIT, OUTPUT_LIMIT, ToolError


def execute(tools, name, approved=False, **args):
    return tools.execute(tools.prepare(name, json.dumps(args)), approved=approved)


def test_read_write_overwrite_and_approval(tools, tmp_path):
    call = tools.prepare("write_file", json.dumps({"path": "sub/你好.txt", "content": "你好\n"}))
    assert not json.loads(call.preview)["overwrite"]
    assert tools.execute(call)["error"]["type"] == "approval_required"
    assert not (tmp_path / "sub").exists()
    assert tools.execute(call, approved=True)["ok"]
    assert execute(tools, "read_file", path="sub/你好.txt")["data"]["content"] == "你好\n"
    overwrite = tools.prepare("write_file", json.dumps({"path": "sub/你好.txt", "content": "new"}))
    assert json.loads(overwrite.preview)["overwrite"]
    assert tools.execute(overwrite, approved=True)["ok"]
    assert (tmp_path / "sub/你好.txt").read_text() == "new"


@pytest.mark.parametrize(
    "name,args",
    [
        ("delete_file", {"path": "x"}),
        ("read_file", {"path": 1}),
        ("read_file", {"path": "x", "extra": "y"}),
        ("read_file", {}),
        ("read_file", {"path": ""}),
        ("run_shell", {"command": " "}),
        ("write_file", {"path": "x", "content": "x" * (FILE_LIMIT + 1)}),
    ],
)
def test_invalid_arguments(tools, name, args):
    with pytest.raises(ToolError):
        tools.prepare(name, json.dumps(args))


@pytest.mark.parametrize("arguments", ["{", "[]", "null", '"string"'])
def test_invalid_json_shape(tools, arguments):
    with pytest.raises(ToolError):
        tools.prepare("read_file", arguments)


def test_paths_cannot_escape(tools, tmp_path):
    for path in ("../outside.txt", str(tmp_path.parent / "outside.txt")):
        with pytest.raises(ToolError, match="超出"):
            tools.prepare("read_file", json.dumps({"path": path}))


def test_symlink_escape(tools, tmp_path):
    link = tmp_path / "outside"
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this Windows installation")
    with pytest.raises(ToolError, match="超出"):
        tools.prepare("write_file", json.dumps({"path": "outside/x", "content": "x"}))


def test_target_change_requires_new_approval(tools, tmp_path):
    call = tools.prepare("write_file", json.dumps({"path": "x", "content": "new"}))
    (tmp_path / "x").write_text("created while waiting")
    assert tools.execute(call, approved=True)["error"]["type"] == "target_changed"
    assert (tmp_path / "x").read_text() == "created while waiting"


def test_read_failures_and_boundary(tools, tmp_path):
    assert execute(tools, "read_file", path="missing")["error"]["type"] == "FileNotFoundError"
    (tmp_path / "binary").write_bytes(b"\xff")
    assert execute(tools, "read_file", path="binary")["error"]["type"] == "encoding_error"
    (tmp_path / "large").write_bytes(b"x" * (FILE_LIMIT + 1))
    assert execute(tools, "read_file", path="large")["error"]["type"] == "file_too_large"
    assert execute(tools, "write_file", True, path="boundary", content="x" * FILE_LIMIT)["ok"]
    assert execute(tools, "read_file", path="boundary")["ok"]
    assert not execute(tools, "write_file", True, path=".", content="x")["ok"]


def test_shell_requires_approval_and_uses_workspace(tools, tmp_path):
    command = (
        "Set-Content -LiteralPath marker -Value ok" if tools.is_powershell else "echo ok > marker"
    )
    assert execute(tools, "run_shell", command=command)["error"]["type"] == "approval_required"
    assert not (tmp_path / "marker").exists()
    assert execute(tools, "run_shell", True, command=command)["ok"]
    assert (tmp_path / "marker").read_text().strip() == "ok"


def test_shell_output_and_exit_code(tools):
    command = (
        "[Console]::Out.Write('你好'); [Console]::Error.Write('problem'); exit 7"
        if tools.is_powershell
        else "printf '你好'; printf problem >&2; exit 7"
    )
    result = execute(tools, "run_shell", True, command=command)
    assert result["error"]["type"] == "shell_exit"
    assert result["data"]["exit_code"] == 7
    assert result["data"]["stdout"] == "你好"
    assert result["data"]["stderr"] == "problem"


def test_shell_timeout(tools):
    tools.timeout = 0.2
    start = time.monotonic()
    command = "Start-Sleep -Seconds 10" if tools.is_powershell else "sleep 10"
    result = execute(tools, "run_shell", True, command=command)
    assert result["error"]["type"] == "shell_timeout"
    assert time.monotonic() - start < 5
    assert result["data"]["exit_code"] is not None


def test_shell_output_is_bounded(tools):
    command = "[Console]::Write('x' * 30000)" if tools.is_powershell else "printf '%030000d' 0"
    result = execute(tools, "run_shell", True, command=command)
    assert result["ok"]
    assert result["data"]["truncated"]
    assert len(result["data"]["stdout"]) == OUTPUT_LIMIT


def test_native_program_exit_code_is_preserved(tools):
    executable = sys.executable.replace("'", "''")
    command = (
        f"& '{executable}' -c 'import sys; sys.exit(9)'"
        if tools.is_powershell
        else f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(9)'"
    )
    result = execute(tools, "run_shell", True, command=command)
    assert not result["ok"]
    assert result["data"]["exit_code"] == 9
