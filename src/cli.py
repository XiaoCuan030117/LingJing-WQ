"""Run with python -m src.cli --workspace PATH \"task\"."""

import argparse
import json
import sys
from pathlib import Path

from .agent import Agent
from .model import ModelError, OpenAIModel
from .tools import Tools


def run(agent: Agent, task: str, read_input=input, output=print) -> int:
    agent.start(task)
    shown = 0
    while True:
        state = agent.advance()
        for result in agent.results[shown:]:
            output("工具结果：" + json.dumps(result, ensure_ascii=False))
        shown = len(agent.results)
        if state == "waiting_approval":
            waiting = agent.waiting
            output(f"需要批准：{waiting.call.name}\n{waiting.call.preview}")
            try:
                allowed = (
                    read_input("仅输入 y 允许本次操作，其他输入均拒绝 [y/N]：").strip().lower()
                    == "y"
                )
            except EOFError:
                allowed = False
            agent.approve(waiting.token, allowed)
        elif state == "completed":
            output(agent.answer)
            return 0
        else:
            output("任务失败：" + agent.error)
            return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="最小 Coding Agent：读写文件和运行 Shell")
    parser.add_argument("task", help="自然语言任务")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="已存在的工作目录")
    parser.add_argument("--shell", help="固定 Shell 可执行文件（Windows 默认 powershell.exe）")
    args = parser.parse_args(argv)
    if not args.task.strip():
        parser.error("任务不能为空")
    try:
        tools = Tools(args.workspace, args.shell)
        model = OpenAIModel.from_env()
        try:
            return run(Agent(model, tools), args.task)
        finally:
            model.client.close()
    except (ModelError, OSError, ValueError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n任务已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
