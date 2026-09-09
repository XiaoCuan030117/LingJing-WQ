# Coding Agent

一个轻量的 Coding Agent，使用 Python、OpenAI 兼容接口和 Streamlit，实现文件总结、脚本编写与执行。

- **CLI 与 WebUI**：支持命令行任务和网页多轮对话。
- **工具审批**：读取自动执行，写入文件和运行命令前逐次征求同意。
- **补充提问**：信息不足时通过 `ask_user` 提问，回答后继续原任务。

## 快速开始

推荐 Python 3.12。以下命令在仓库根目录使用 PowerShell 执行。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 配置模型

首次使用时，将 `.env.example` 复制为 `.env`，保留已有配置：

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

填写密钥、API 基础地址和模型名称：

```dotenv
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://服务商地址/v1
OPENAI_MODEL=支持工具调用的模型名称
```

支持 OpenAI 官方及兼容 Chat Completions 工具调用的服务。`OPENAI_BASE_URL` 可省略以使用默认地址，不要填写完整的 `/chat/completions` 路径。

程序自动加载项目根目录的 `.env`，系统环境变量优先。网页端修改配置后点击“新建对话”生效。`.env` 已被 Git 忽略，请勿提交密钥。

### 3. 启动 WebUI

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

打开 `http://127.0.0.1:8501`，在侧栏选择已存在的工作目录，即可输入任务。

## 使用方式

### 网页对话

可以尝试以下任务：

- “读取 notes.txt 并总结内容。”
- “创建一个打印 hello agent 的 Python 脚本，先问我保存的文件名，然后运行它。”

写入或运行命令前，页面展示目标路径、文件内容或完整命令，点击“允许本次”后执行；拒绝会作为结果返回 Agent。补充问题通过表单回答，空回答不会继续任务。

本轮完成后可继续追问；失败后可新建对话重试。展开工具结果可查看实际输出和错误信息。

一个完整演示流程是：**提出脚本需求 → 回答文件名 → 批准写入 → 拒绝执行 → 明确重新请求运行 → 批准并查看输出**。也可尝试读取不存在的文件或拒绝创建文件，观察错误反馈和文件是否发生变化。

### 命令行

将工作目录替换为已有目录，文件总结示例需要目录内存在 `notes.txt`：

```powershell
.\.venv\Scripts\python.exe -m src.cli --workspace 'D:\你的工作目录' '读取 notes.txt 并总结内容'
.\.venv\Scripts\python.exe -m src.cli --workspace 'D:\你的工作目录' '创建 hello.py，打印 hello agent，然后运行脚本'
```

审批时输入 `y` 允许，其他输入拒绝；出现补充问题时直接输入回答。Windows 默认使用 PowerShell，可通过 `--shell pwsh` 指定解释器。

## 工作原理

CLI 和 WebUI 共用一个串行 Agent 循环：

```text
用户任务 → 模型决策 → 工具调用 → 结果回传 → 继续决策或最终回答
                       ↓
                 等待审批或补充回答
```

循环保存消息历史和待处理工具队列，等待用户输入时暂停。收到决定或回答后从原位置继续，一次性令牌防止重复提交和页面重跑导致重复执行。权限检查在工具执行层完成。

文件缺失、路径越界和命令失败等错误会返回模型；模型请求失败或达到循环上限时停止本轮任务。

## 项目结构

```text
app.py               Streamlit 界面
src/
  agent.py           Agent 循环与交互状态
  model.py           模型接口与配置加载
  tools.py           文件、Shell 和提问工具
  cli.py             命令行入口
tests/               核心、工具、接口及页面测试
.env.example         配置示例
requirements.txt     运行依赖
requirements-dev.txt 开发与测试依赖
```

## 测试

安装开发依赖后运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

测试使用模拟模型和 HTTP 响应，不调用付费 API；文件和 Shell 操作在临时目录执行。页面通过 Streamlit AppTest 验证对话、审批、提问恢复和重复事件处理。符号链接测试在权限不足时跳过。

真实模型可按上面的使用示例验证，并核对生成文件与工具输出。

## 限制与注意事项

- 面向本机单用户使用。会话仅保存在内存，刷新或重启可能丢失；不提供持久化、工具并行或后台任务。
- 文件工具限于工作目录内的 UTF-8 文件，单次读写上限为 100 KiB。文件内容和工具输出会发送给配置的模型服务。
- Shell 拥有当前用户权限，工作目录不是安全沙箱。命令限时 30 秒，输出最多保留 20 KiB；超时不保证清理全部子进程，不支持交互式命令。
- 每轮最多 12 次模型请求、20 次工具调用，模型请求超时为 60 秒。模型行为和回答质量取决于所配置服务，应以实际工具结果确认任务是否完成。
