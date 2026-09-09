"""Validated file tools and bounded shell execution, with explicit authorization."""

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

FILE_LIMIT = 100 * 1024
OUTPUT_LIMIT = 20 * 1024


class ToolError(ValueError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def failure(kind: str, message: str, **data) -> dict:
    return {"ok": False, "error": {"type": kind, "message": message}, **data}


@dataclass(frozen=True)
class PreparedCall:
    name: str
    arguments: str
    preview: str

    @property
    def requires_approval(self) -> bool:
        return self.name in {"write_file", "run_shell"}


def tool_schemas() -> list[dict]:
    definitions = [
        ("read_file", "Read a UTF-8 file inside the workspace (maximum 100 KiB).", ["path"]),
        (
            "write_file",
            "Write complete UTF-8 content inside the workspace. Requires user approval.",
            ["path", "content"],
        ),
        (
            "run_shell",
            "Run a noninteractive command in the configured shell. Requires user approval.",
            ["command"],
        ),
        (
            "ask_user",
            "Ask one clear question for missing required information. Wait for the user's answer.",
            ["question"],
        ),
    ]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {key: {"type": "string"} for key in keys},
                    "required": keys,
                    "additionalProperties": False,
                },
            },
        }
        for name, description, keys in definitions
    ]


class Tools:
    def __init__(self, workspace: Path, shell: str | None = None, timeout: float = 30):
        self.workspace = workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("工作目录必须是已存在的目录。")
        self.shell = shutil.which(shell or ("powershell.exe" if os.name == "nt" else "sh"))
        if not self.shell:
            raise ValueError("找不到 Shell；请通过 --shell 指定 PowerShell 或 sh 的路径。")
        self.is_powershell = Path(self.shell).stem.lower() in {"powershell", "pwsh"}
        if not self.is_powershell and Path(self.shell).name not in {"sh", "bash", "dash"}:
            raise ValueError("仅支持 PowerShell、pwsh、sh、bash 或 dash。")
        self.timeout = timeout

    def _path(self, value: str) -> Path:
        if not value.strip() or "\x00" in value:
            raise ToolError("invalid_arguments", "文件路径不能为空或包含 NUL。")
        path = (self.workspace / value).resolve()
        if not path.is_relative_to(self.workspace):
            raise ToolError("outside_workspace", "文件路径超出工作目录。")
        # Windows alternate data streams and device names are not ordinary files.
        relative = path.relative_to(self.workspace)
        if os.name == "nt" and any(
            ":" in part or Path(part).is_reserved() for part in relative.parts
        ):
            raise ToolError("invalid_path", "不支持 Windows 设备名称或备用数据流。")
        return path

    def prepare(self, name: str, arguments: str) -> PreparedCall:
        expected = {
            "read_file": {"path"},
            "write_file": {"path", "content"},
            "run_shell": {"command"},
            "ask_user": {"question"},
        }
        if name not in expected:
            raise ToolError("unknown_tool", f"未知工具：{name}")
        try:
            args = json.loads(arguments)
        except (TypeError, ValueError) as exc:
            raise ToolError("invalid_arguments", "工具参数必须是有效 JSON。") from exc
        if (
            not isinstance(args, dict)
            or set(args) != expected[name]
            or any(not isinstance(value, str) for value in args.values())
        ):
            raise ToolError("invalid_arguments", "参数名称或字符串类型不符合工具定义。")
        preview = dict(args)
        if name in {"read_file", "write_file"}:
            path = self._path(args["path"])
            preview["path"] = str(path)
            if name == "write_file":
                if len(args["content"].encode("utf-8")) > FILE_LIMIT:
                    raise ToolError("file_too_large", "写入内容超过 100 KiB。")
                preview["overwrite"] = path.exists()
        elif name == "run_shell":
            if not args["command"].strip() or "\x00" in args["command"]:
                raise ToolError("invalid_arguments", "命令不能为空或包含 NUL。")
            preview.update(workspace=str(self.workspace), shell=self.shell)
        elif not args["question"].strip():
            raise ToolError("invalid_arguments", "问题不能为空。")
        return PreparedCall(
            name, json.dumps(args), json.dumps(preview, ensure_ascii=False, indent=2)
        )

    def execute(self, call: PreparedCall, *, approved: bool = False) -> dict:
        if call.requires_approval and not approved:
            return failure("approval_required", "此操作需要用户逐次批准。")
        try:
            # Revalidate after a potentially long approval wait, including resolved target.
            current = self.prepare(call.name, call.arguments)
            if current != call:
                raise ToolError("target_changed", "审批期间目标发生变化，请重新发起调用。")
            args = json.loads(call.arguments)
            if call.name == "ask_user":
                return failure("user_input_required", "需要等待用户回答，由 Agent 恢复此调用。")
            if call.name == "run_shell":
                return self._run_shell(args["command"])
            path = self._path(args["path"])
            if call.name == "read_file":
                with path.open("rb") as stream:
                    raw = stream.read(FILE_LIMIT + 1)
                if len(raw) > FILE_LIMIT:
                    raise ToolError("file_too_large", "文件超过 100 KiB。")
                return {"ok": True, "data": {"path": str(path), "content": raw.decode("utf-8")}}
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = args["content"].encode("utf-8")
            path.write_bytes(raw)
            return {"ok": True, "data": {"path": str(path), "bytes_written": len(raw)}}
        except ToolError as exc:
            return failure(exc.kind, str(exc))
        except UnicodeError:
            return failure("encoding_error", "文件或写入内容不是有效 UTF-8 文本。")
        except (OSError, ValueError, RuntimeError) as exc:
            return failure(type(exc).__name__, str(exc))

    def _run_shell(self, command: str) -> dict:
        if self.is_powershell:
            script = (
                "$ErrorActionPreference = 'Stop'; "
                "$OutputEncoding = [Console]::OutputEncoding = "
                "[System.Text.UTF8Encoding]::new($false); $LASTEXITCODE = 0; & {\n"
                + command
                + "\n}; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
            )
            argv = [self.shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]
        else:
            argv = [self.shell, "-c", command]
        process = subprocess.Popen(
            argv,
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        buffers = [bytearray(), bytearray()]
        lock = threading.Lock()
        truncated = False

        def drain(stream, index):
            nonlocal truncated
            with stream:
                while chunk := stream.read(4096):
                    with lock:
                        remaining = OUTPUT_LIMIT - sum(map(len, buffers))
                        buffers[index].extend(chunk[:remaining])
                        truncated |= len(chunk) > remaining

        readers = [
            threading.Thread(target=drain, args=(stream, i), daemon=True)
            for i, stream in enumerate((process.stdout, process.stderr))
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait(timeout=5)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise
        finally:
            for reader in readers:
                reader.join(timeout=0.5)
        with lock:
            data = {
                "stdout": bytes(buffers[0]).decode("utf-8", errors="replace"),
                "stderr": bytes(buffers[1]).decode("utf-8", errors="replace"),
                "exit_code": process.returncode,
                "truncated": truncated,
                "output_incomplete": any(reader.is_alive() for reader in readers),
            }
        if timed_out:
            return failure("shell_timeout", "命令超时，已终止 Shell 进程。", data=data)
        if process.returncode:
            return failure("shell_exit", "命令返回非零退出码。", data=data)
        if data["output_incomplete"]:
            return failure("background_process", "输出管道未关闭；不支持后台命令。", data=data)
        return {"ok": True, "data": data}
