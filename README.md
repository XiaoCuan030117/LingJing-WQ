# 最小 Coding Agent（CLI + WebUI）

使用 Python 普通函数和直接模型 SDK，实现自然语言任务 → 模型工具调用 → 实际执行 → 结果回传 → 最终回答。提供单轮 CLI 和 Streamlit 连续对话界面，支持读取 UTF-8 文件、写入文件和运行 Shell。写入和 Shell 均需逐次确认。当前完成 PLAN 的第三阶段：信息不足时可通过 `ask_user` 提问，收到回答后继续原任务。

## 安装与配置

要求 Python 3.12+。在仓库根目录用 PowerShell 执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

在项目根目录的 `.env` 中填写以下配置；首次使用且文件不存在时，可复制 `.env.example`，不要覆盖已有密钥：

```dotenv
OPENAI_API_KEY=公司提供的密钥
OPENAI_BASE_URL=https://服务商地址/v1
OPENAI_MODEL=支持工具调用的模型名称
```

CLI 和 WebUI 都会自动读取项目根目录 `.env`，不依赖当前工作目录，也不会读取工具工作目录中的同名文件。系统环境变量优先于文件（包括显式空值）；支持引号和注释，不展开 `${变量}`。文件内容不会写入进程环境。WebUI 修改配置后点击“新建对话”生效，已有对话继续使用原配置。

配置密钥时暂停录屏，完成后恢复。`.env` 已被 Git 忽略，勿将密钥填入 `.env.example`。`OPENAI_BASE_URL` 可省略以使用 SDK 的默认服务地址，模型名称必须明确设置。公司接口须支持 Chat Completions 的 `tools`、`tool_calls` 和 `tool_call_id`，以实际连通验证为准。协议参考：[OpenAI 官方工具调用文档](https://developers.openai.com/api/docs/guides/function-calling)。

## 运行与真实验收

先在系统临时目录准备独立工作目录：

```powershell
$agentDemoDir = Join-Path ([System.IO.Path]::GetTempPath()) ('agent-demo-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $agentDemoDir
Set-Content -LiteralPath (Join-Path $agentDemoDir 'notes.txt') -Encoding UTF8 -Value '本项目需要读取文件、写入文件和运行命令三个工具。'
.\.venv\Scripts\python.exe -m src.cli --workspace $agentDemoDir '读取 notes.txt 并总结内容'
.\.venv\Scripts\python.exe -m src.cli --workspace $agentDemoDir '创建 hello.py，打印 hello agent，然后运行该脚本并报告实际输出'
Get-Content -LiteralPath (Join-Path $agentDemoDir 'hello.py')
```

核对总结符合原文、脚本实际存在、命令退出码为 0 且输出包含 `hello agent`。每次写入或执行前会展示完整参数，含目标路径、覆盖标记或命令及工作目录；输入 `y` 才允许，其他输入或 EOF 均拒绝。另跑一次写入任务并拒绝，确认文件没有生成。工具失败会显示结构化结果，模型可修正后再次请求；任何新写入或命令仍需单独批准。

Windows 默认固定使用 `powershell.exe -NoProfile -NonInteractive`；可通过 `--shell` 指定 `pwsh`。POSIX 默认 `sh`，也支持 `bash`/`dash`。命令的工作目录固定为 `--workspace`，目录必须已存在；Shell 不继承交互输入。本机 PowerShell 执行策略可能禁止 `.ps1` 文件，工具会如实返回错误；演示使用 Python 脚本，不修改系统执行策略。退出码：0 表示模型正常结束，1 表示启动或循环失败，130 表示用户中断；模型正常解释工具失败时也可能返回 0，应同时检查工具结果。

## 结构与状态

- `app.py`：Streamlit 聊天界面、工具结果、审批控件及会话状态。
- `src/model.py`：环境配置与模型适配，60 秒超时、关闭 SDK 自动重试，不输出 API 错误原文。
- `src/tools.py`：参数校验、工作目录约束、文件和 Shell 工具。
- `src/agent.py`：串行队列、消息与调用 ID、步数、一次性授权令牌。
- `src/cli.py`：任务入口、结果展示及授权输入。
- `tests/`：模拟模型、SDK 模拟 HTTP、实际临时文件和无害 Shell 测试。

状态为 `idle → running → waiting_approval/waiting_user → running → completed/failed`。`advance()` 在等待授权或回答期间不会请求模型或重放调用；`approve(token, allowed)` 和 `reply(token, text)` 分别消费当前审批或回答令牌。`continue_task()` 仅在上一轮完成后开启下一轮，保留消息上下文并重置本轮调用计数；失败后需新建对话。

## WebUI 启动与验收（第二阶段）

先按上方安装步骤安装依赖，并填写项目根目录的 `.env`（或设置系统环境变量），然后运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

打开 `http://127.0.0.1:8501`。页面不显示或保存密钥。

1. 在侧栏选择已存在的临时工作目录，输入“读取 notes.txt 并总结”。核对回答和展开的工具结果，然后追问以验证上下文保留。
2. 请求创建文件，核对显示的完整路径、覆盖提示和待写内容。批准前文件不应改变；点击“允许本次”后核对文件内容。
3. 请求运行命令，核对完整命令和工作目录。点击“拒绝本次”，确认无副作用且 Agent 能继续说明结果。
4. 请求依次写入两个文件。在每个审批处触发 Streamlit 的 Rerun，确认待审批项不丢失；允许第一个、拒绝第二个，核对结果。
5. 本轮完成后继续提问；失败时页面显示原因，点击“新建对话”后可重试或更换目录。

会话与待审批队列保存在 `st.session_state`；审批按钮绑定一次性令牌，普通页面重跑不会重复执行。运行或等待审批时禁止新任务覆盖当前任务，工作目录在本段对话中固定。浏览器刷新或断开连接可能丢失会话，进程重启不恢复；历史仅保存在内存中。模型调用同步执行，无流式输出、持久化或后台任务，长对话仍受模型上下文窗口限制。网页仅供本机单用户演示，CLI 行为保持可用。阶段一基线提交为 `b69f477`。

## 边界与失败处理

文件读写各限制 100 KiB，按解析后的路径限制在工作目录内；写入为完整覆盖并可创建父目录。读取错误、越界、参数错误和非零退出码会返回模型。每轮上限为 12 次模型请求、20 次工具调用；API 错误或达到上限后停止，不自动重试。

Shell 超时 30 秒，输出合计最多保留 20 KiB，截断会标记；输出按 UTF-8 解码，非 UTF-8 字节用替代字符表示。超时终止直接 Shell 进程，但不保证终止全部子进程；不支持后台或交互式命令。Shell 仍拥有当前用户权限，可访问工作目录外资源，文件路径校验也不是抵抗并发文件替换的沙箱。请只在本机可信的临时工作目录演示。

## ask_user 暂停与恢复（第三阶段）

`ask_user` 接受一个非空字符串参数 `question`。调用后显示问题和回答表单，无须批准提问本身；用户提交非空回答后，以 `{"ok": true, "data": {"answer": "用户回答"}}` 回传原工具调用 ID，再继续队列或请求模型。回答不会被当成新的顶层任务。

验证步骤：输入“创建一个打印 hello 的 Python 脚本，先问我保存的文件名”。页面应进入等待回答；填写 `hello.py` 并提交，随后核对写入审批中的路径和内容，批准后检查文件存在及最终回答。空回答会提示重填，等待期间 Rerun 不增加模型请求；重复或过期提交无效。同一响应含多个问题时逐个提问，每个问题使用独立表单。

CLI 同样会显示问题并等待输入；空回答重新询问，EOF 结束任务并返回退出码 1，Ctrl+C 返回 130。不会以空回答代替用户意见。会话丢失后无法恢复，仍不提供持久化或后台等待服务。问题是否需要提出由模型判断，系统提示词要求缺少必要信息时使用该工具。

## 测试与检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

测试不调用付费 API：模型响应和 HTTP 使用模拟，文件与 Shell 使用真实临时目录。覆盖多步调用、审批暂停／拒绝／重复事件、错误回传、循环上限、大小边界、Shell 退出与超时。符号链接测试在系统不允许创建链接时明确跳过。

`tests/test_app.py` 使用 [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest) 在 pytest 内运行真实页面脚本，覆盖聊天、上下文、审批、rerun、失败重置及会话隔离，无需浏览器自动化服务。只运行本阶段测试可使用 `python -m pytest tests/test_app.py tests/test_agent.py`。真实 API 页面验收需单独执行，不包含在日常离线测试中。

真实模型验收必须另行执行上述命令并记录结果；离线测试通过不代表公司接口已验证。按 `TASK.md` 录制开发过程并提供 GitHub 地址；阶段一真实演示通过后提交独立 commit，再开始阶段二。
