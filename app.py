"""Local Streamlit chat UI. Start with: streamlit run app.py."""

import json
from pathlib import Path

import streamlit as st

from src.agent import Agent
from src.model import ModelError, OpenAIModel
from src.tools import Tools


def busy(agent):
    return agent is not None and agent.state in {"running", "waiting_approval"}


def submit_task():
    agent = st.session_state.get("agent")
    task = st.session_state.get("task", "")
    if busy(agent) or not task.strip() or (agent and agent.state == "failed"):
        return
    try:
        if agent is None:
            tools = Tools(Path(st.session_state.workspace))
            agent = Agent(OpenAIModel.from_env(), tools)
            agent.start(task)
            st.session_state.agent = agent
        else:
            agent.continue_task(task)
        st.session_state.startup_error = ""
    except (ModelError, OSError, ValueError) as exc:
        st.session_state.startup_error = str(exc)


def queue_approval(token, allowed):
    # Callbacks only enqueue a decision. Execution happens once in the main run.
    agent = st.session_state.get("agent")
    if agent and agent.waiting and token == agent.waiting.token:
        st.session_state.decision = (token, allowed)


def reset_chat():
    agent = st.session_state.get("agent")
    if busy(agent):
        return
    if agent:
        agent.model.client.close()
    st.session_state.agent = None
    st.session_state.startup_error = ""
    st.session_state.pop("decision", None)


def show_history(agent):
    names = {}
    for message in agent.messages:
        role = message["role"]
        for call in message.get("tool_calls", []):
            names[call["id"]] = call["function"]["name"]
        if role in {"user", "assistant"} and message.get("content"):
            with st.chat_message(role):
                st.markdown(message["content"])
        elif role == "tool":
            result = json.loads(message["content"])
            label = "成功" if result["ok"] else "未完成"
            name = names.get(message["tool_call_id"], "工具")
            with st.expander(f"{name} · {label}"):
                if not result["ok"]:
                    st.warning(result["error"]["message"])
                st.json(result)


def main():
    st.set_page_config(page_title="Coding Agent", page_icon="💬")
    st.title("Coding Agent")
    st.caption("读取文件、编写脚本、运行命令。写入和执行前，由你逐次确认。")
    st.session_state.setdefault("agent", None)
    st.session_state.setdefault("startup_error", "")
    agent = st.session_state.agent

    # Pop before executing so a rerun cannot replay the same approval event.
    decision = st.session_state.pop("decision", None)
    if decision and agent:
        with st.spinner("正在处理本次决定…"):
            agent.approve(*decision)
    if agent and agent.state == "running":
        with st.spinner("正在处理任务…"):
            agent.advance()

    with st.sidebar:
        st.header("工作目录")
        st.text_input(
            "已存在的本地目录", value=str(Path.cwd()), key="workspace", disabled=agent is not None
        )
        st.caption("开始对话后目录固定；新建对话可更换。")
        st.button("新建对话", key="reset", on_click=reset_chat, disabled=busy(agent))
        st.caption("本机单用户使用。批准的命令拥有当前用户权限。")

    if st.session_state.startup_error:
        st.error(st.session_state.startup_error)
    if agent:
        show_history(agent)
        if agent.state == "waiting_approval":
            waiting = agent.waiting
            preview = json.loads(waiting.call.preview)
            st.info("等待你的决定；批准前不会执行此操作。")
            st.subheader(f"确认操作：{waiting.call.name}")
            if waiting.call.name == "write_file":
                st.text(f"目标：{preview['path']}")
                st.warning("将覆盖已有文件" if preview["overwrite"] else "将创建新文件")
                st.code(preview["content"], language="text")
            else:
                st.text(f"目录：{preview['workspace']}\nShell：{preview['shell']}")
                st.code(
                    preview["command"],
                    language="powershell" if agent.tools.is_powershell else "bash",
                )
            allow, deny = st.columns(2)
            allow.button(
                "允许本次",
                key=f"allow_{waiting.token}",
                type="primary",
                on_click=queue_approval,
                args=(waiting.token, True),
            )
            deny.button(
                "拒绝本次",
                key=f"deny_{waiting.token}",
                on_click=queue_approval,
                args=(waiting.token, False),
            )
        elif agent.state == "failed":
            st.error(agent.error)
            st.info("本轮已停止。点击“新建对话”后可以重新尝试。")
        elif agent.state == "completed":
            st.caption("本轮已完成，可以继续对话。")
    else:
        st.info("选择工作目录，然后输入任务，例如：读取 notes.txt 并总结。")
    st.chat_input(
        "输入任务或继续提问",
        key="task",
        on_submit=submit_task,
        disabled=busy(agent) or bool(agent and agent.state == "failed"),
    )


if __name__ == "__main__":
    main()
