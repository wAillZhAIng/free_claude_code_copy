# Windows 新手教程：从零连接本地模型网关

本教程面向没有 Python / Agent 配置经验的 Windows 用户。使用**普通用户 PowerShell**，不要求管理员权限，也不需要先安装到 Skill 目录。

你将得到一个仅监听本机的 FCC 网关：宿主用 HTTP 调用它，FCC 负责上游登录和协议转换。**不是把 ChatGPT 订阅变成 OpenAI Platform API 余额，也不是解除额度限制。**

> 教程中的命令供你审阅后自行执行。安装会下载依赖并执行上游代码；标注“生成验收”的命令会调用模型、消耗额度。不要整页一键运行。

## 目录

1. [理解三个角色与两套 Python](#1-理解三个角色与两套-python)
2. [安装官方依赖](#2-安装官方依赖)
3. [克隆仓库并设置绝对路径](#3-克隆仓库并设置绝对路径)
4. [诊断并安装 FCC 独立运行时](#4-诊断并安装-fcc-独立运行时)
5. [生成受指纹保护的本机兼容层](#5-生成受指纹保护的本机兼容层)
6. [前台启动并保持终端运行](#6-前台启动并保持终端运行)
7. [本人登录、代理设置和模型选择](#7-本人登录代理设置和模型选择)
8. [先做不生成文本的检查](#8-先做不生成文本的检查)
9. [配置普通 HTTP Agent](#9-配置普通-http-agent)
10. [可选：明确同意消耗额度后做生成验收](#10-可选明确同意消耗额度后做生成验收)
11. [接入 WeKnora](#11-接入-weknora)
12. [可选：安装到宿主的 Skill 目录](#12-可选安装到宿主的-skill-目录)
13. [按顺序排查常见问题](#13-按顺序排查常见问题)
14. [数据、安全、许可和验收边界](#14-数据安全许可和验收边界)

## 1. 理解三个角色与两套 Python

```text
Agent / WeKnora 后端
    → 你本机的 FCC HTTP 网关
    → FCC 配置的真实模型提供方
```

- **本仓库的 helper**：`scripts/gateway.py`，只用 Python 标准库。负责诊断、安装、启动、模型列表与探针，不自行实现 OAuth。
- **FCC 运行时**：独立安装的第三方依赖，提供管理界面、provider 登录、模型发现、路由和协议转换。
- **宿主**：真正发起对话的 Agent 或 WeKnora。它必须能配置自定义端点和正确协议；加载说明文件不会自动修改模型 transport。

| Python 用途 | 版本与来源 | 是否共用系统安装 |
|---|---|---|
| 运行本仓库 helper | 官方 Python 3.10+，建议 3.12 | 使用你安装的 `python` |
| 运行固定 FCC 版本 | **Python 3.14.10**，由 uv 单独下载和创建环境 | 不替换系统 Python |

**不要因为系统装的是 3.12，就把 FCC 的 3.14.10 pin 改成 3.12。** 两套 Python 共存是正常设计。固定 FCC 上游 commit 为 `56621010ada15b633d76ab19178764bb3e81bcc5`，对应 FCC **6.19.11**。

### 三种连接设置不是一回事

| 名称 | 解决什么问题 | 填在哪里 |
|---|---|---|
| 出站 `OPENAI_PROXY` | FCC 如何连接上游网络 | FCC 管理界面对应代理设置 |
| 宿主 Base URL | Agent / WeKnora 如何找到本地 FCC | 宿主模型配置，例如 `http://127.0.0.1:18082/v1` |
| Proxy Authentication token | 谁可以调用你的本地网关 | FCC 中启用；宿主 API Key 中填写此本地 token |

本地网关 token **不是** OpenAI OAuth token，也不是出站代理地址。不要相互替换。

## 2. 安装官方依赖

从开始菜单打开 **PowerShell**，不要选择“以管理员身份运行”。如果设备由组织管理且禁止安装，联系管理员，不要绕过组织策略。

本教程不会让你把未经解释的远程脚本下载后直接执行。

### 2.1 安装官方 Python 3.10+，建议 3.12

1. 打开 Python 官方 Windows 下载页：<https://www.python.org/downloads/windows/>。
2. 选择有官方 Windows 安装程序的 Python 3.12 版本，按电脑架构下载。普通 Intel / AMD 电脑通常选 64-bit；ARM 电脑按官方说明选对应版本。
3. 在安装器中勾选 **Add python.exe to PATH**，使用当前用户安装，不选择给所有用户安装。安装器界面随版本变化；如果操作要求管理员权限，返回检查是否选了全用户安装。
4. 安装后关闭并重新打开普通 PowerShell。

检查：

```powershell
python --version
python -I -m pip --version
```

期望 `python` 至少是 3.10，本教程建议显示 3.12.x。`-I` 是 Python 的隔离模式，避免当前目录或用户扩展意外影响 helper。

如果 `python` 只打开 Microsoft Store，先检查官方安装是否成功、PATH 是否生效；必要时在 Windows“应用执行别名”中关闭冲突的商店别名。若只认 `py -3.12`，可以用 `py -3.12` 替换后文命令开头的 `python`，不要改脚本参数。

### 2.2 安装 Git

1. 打开官方 Windows 下载入口：<https://git-scm.com/download/win>，它会指向 Git for Windows 的正式发行。
2. 选择当前用户安装方式；如安装器不提供此方式，可使用官方提供的 Portable Git，解压到你有写权限的目录，按其说明把命令目录加到**用户** PATH。不要为了本教程提升权限。
3. 重新打开 PowerShell，检查：

```powershell
git --version
```

不需要为了克隆公共仓库设置 Git 提交身份，也不要在 URL 中嵌入密码或访问 token。

### 2.3 安装 uv：使用官方文档支持的 pip 方法

官方说明：<https://docs.astral.sh/uv/getting-started/installation/#pypi>。下面使用已安装 Python 的 pip，从 PyPI 安装 uv 到当前用户目录；不是 `irm ... | iex` 一键执行远程脚本。

```powershell
python -I -m pip install --user --upgrade uv
```

安装后重新打开 PowerShell，检查：

```powershell
uv --version
```

如果 pip 提示 Scripts 不在 PATH，或者 `uv` 找不到，不必修改全局环境。下面根据 Python 的用户安装方案计算 uv 的绝对路径：

```powershell
$uv = Join-Path (python -I -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))") 'uv.exe'
& "$uv" --version
```

若 uv 本来就在 PATH 中，也可以这样获取路径：

```powershell
$uv = (Get-Command uv).Source
& "$uv" --version
```

`&` 是 PowerShell 运行一个可执行文件路径的调用运算符。**后文使用 `--uv-path "$uv"` 的地方，需要先在当前窗口定义 `$uv`。** 如果路径不存在，先解决 uv 安装问题，不要换来历不明的下载源。

## 3. 克隆仓库并设置绝对路径

推荐目录是 `$HOME\AgentTools\free_claude_code_copy`。`$HOME` 是你的 Windows 用户目录；无需照搬别人的盘符或用户名。

先确保父目录存在，再克隆指定分支：

```powershell
New-Item -ItemType Directory -Force -Path (Join-Path $HOME 'AgentTools') | Out-Null
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
git clone --branch main https://github.com/wAillZhAIng/free_claude_code_copy.git "$s"
$g = Join-Path $s 'scripts\gateway.py'
```

如果你已经克隆该仓库，**不要再次 clone 到同一目录**，只把 `$s` 设置成已有仓库的绝对路径，然后重新设置 `$g`。

检查文件是否位于预期位置：

```powershell
Test-Path "$s\SKILL.md"
Test-Path "$g"
Test-Path "$s\scripts\fcc_compat.py"
```

都应该为 `True`。仓库根目录就是 Skill 根目录，`SKILL.md`、`scripts/`、`tests/`、`references/` 同级，不要给路径多加一层 `portable-model-gateway`。

### 变量不跨终端保留

- `$s`：Skill / 仓库根目录绝对路径。
- `$g`：`gateway.py` 的绝对路径。
- `$uv`：需要指定独立 uv 时使用的可执行文件绝对路径。

**每次新开 PowerShell 或重启电脑后，都要重新定义变量**。尤其是在一个终端运行服务、另一个终端检查时。下面两行可以反复执行：

```powershell
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
$g = Join-Path $s 'scripts\gateway.py'
```

所有 Python 命令都使用脚本绝对路径，无需 `cd` 到仓库。

## 4. 诊断并安装 FCC 独立运行时

### 4.1 只做诊断

```powershell
python -I "$g" doctor
```

查看输出：

- `helper_python`：当前 helper 的 Python 版本。
- `fcc_python_required`：应为 `3.14.10`。
- `uv_found`、`git_found`：是否能通过 PATH 找到这些工具。
- `state_dir`：运行数据目录。
- `credentials_read`：为 `false`。此命令不读凭据，也不联系 provider。

如果你准备通过 `--uv-path` 使用独立 uv，`uv_found=false` 不代表那个绝对路径不可用；它只检测 PATH。先用 `& "$uv" --version` 检查你指定的程序。

### 4.2 先预览安装计划，不下载

uv 已在 PATH 时：

```powershell
python -I "$g" install-runtime
```

需要指定 uv 路径时，改用：

```powershell
python -I "$g" install-runtime --uv-path "$uv"
```

输出应含 `dry_run: true` 与两条安装计划：uv 为 FCC 创建 Python **3.14.10** 环境，然后安装固定 Git commit 的上游依赖。预览本身不下载、不安装，也不调用模型。

### 4.3 确认信任上游并接受安装后，再执行

**此步骤会下载 Python / FCC / 依赖，并执行第三方构建代码。** 网络失败不应通过禁用 TLS 验证来解决。

uv 在 PATH 时：

```powershell
python -I "$g" install-runtime --execute
```

或者使用刚才检查过的独立 uv，二选一，不要两组都运行：

```powershell
python -I "$g" install-runtime --uv-path "$uv" --execute
```

首次安装可能较大且耗时。成功以命令完成并报告 `installed: true` 为准；出现了某个文件夹不等于安装成功。

### 运行数据存在哪里

默认是 `%LOCALAPPDATA%\portable-model-gateway`；没有 `LOCALAPPDATA` 时回退到 `~/.local/share/portable-model-gateway`。

```text
portable-model-gateway/
├── runtime/       FCC 独立 Python 环境与依赖
└── home/
    └── .fcc/      FCC 专属配置和授权状态；不要读取、复制或上传
```

本工具不会自动复用你原有用户目录下的 `.fcc`、其他产品的登录缓存或浏览器凭据。更换 state directory 意味着使用另一套 FCC 状态，可能需要重新登录。

如需自定义 `--state-dir`，它是 `install-runtime` 和 `start` 的参数，`fcc_compat.py` 也支持；这些命令必须指向同一个目录。不要把 `--state-dir` 传给不支持它的 `doctor` / `models` / `probe`。新手建议使用默认目录。

## 5. 生成受指纹保护的本机兼容层

**安装 FCC 成功后**才执行此节。固定 FCC 6.19.11 的 Chat 转换器存在 `response.metadata` 事件兼容问题，因此本教程的 Chat 路线建议使用项目内 overlay。

先预览，不写文件：

```powershell
python -I "$s\scripts\fcc_compat.py"
```

预览也会读取并校验**已安装转换器源码**，不是读取 OAuth 文件。确认后生成本机副本：

```powershell
python -I "$s\scripts\fcc_compat.py" --execute
```

预期结果：

- `source_unchanged: true`：不改已安装 FCC。
- 生成 `$s\compat\fcc_responses_stream.py`。
- 校验源码 CRLF → LF 规范化后的 SHA-256：`da33b85b4cf450a93b97d69892595e43de36f84730c17e492e2c5750dbba02c5`。
- 指纹不符、找不到唯一转换器、已有 overlay 内容不同，都会停止，而不是强行覆盖。

兼容层只增加对 `response.metadata` 的结构检查，并将其保留到 Chat 的 `provider_metadata` 扩展字段；不拼入正文、不把它当完成信号、不吞掉未知事件、错误、拒绝或截断。启动器还会再次检查源文件与 overlay。

**它不是通用修复开关**，不能解决网络超时、401、额度不足、`chat_template_kwargs` 400 或宿主协议选错。`compat/` 是本机生成物，不要提交；换一个 Skill 安装位置必须重新生成。

## 6. 前台启动并保持终端运行

在终端 A 执行：

```powershell
python -I "$g" start --port 18082 --compat-metadata
```

保持终端 A 打开。程序运行时不会回到 PowerShell 提示符，这是正常的前台服务行为。

- 管理页：<http://127.0.0.1:18082/admin>
- Base URL：`http://127.0.0.1:18082/v1`
- health：`http://127.0.0.1:18082/health`

该脚本**默认端口为 8082**，本教程为避免与已有服务冲突统一使用 **18082**。启动端口和后续 `--base-url` 必须一致。看到管理页地址或 health 正常，不等于提供方模型发现已完成。

只需用 Ctrl+C 停止**自己在此终端启动的实例**。如果端口占用，脚本会拒绝启动；不要结束别人的进程。先确认占用者，再选一个你获准使用的空闲端口，并同步更新所有 URL。

关闭 overlay 的方式：停止自己的实例，然后不带 `--compat-metadata` 重启同一端口；无需还原 site-packages。

```powershell
# 仅在自己的上一个实例已停止后使用；这是原版 FCC 路线
python -I "$g" start --port 18082
```

这不代表原版 Chat 的 metadata 问题已消失。原生 Responses 是另一条路线，详见协议和探针章节。

## 7. 本人登录、代理设置和模型选择

### 7.1 打开本地管理页

用浏览器打开 <http://127.0.0.1:18082/admin>。不要把管理页或 OAuth 界面暴露到公网，也不要把陌生网站伪装的登录页当作真实 provider 页面。

### 7.2 如果上游网络需要代理

在 **FCC 管理界面**配置 `OPENAI_PROXY` 对应的出站代理选项。例如：

```text
http://127.0.0.1:7890
```

**这只是格式示例，不是推荐或保证存在的端口。** 地址、协议与端口必须以你本人代理软件的实际配置为准。代理可能接触请求流量，应只使用你信任且获准使用的代理；不要禁用 TLS 校验。

不要把这个地址填进 Agent 的 Base URL；Agent 的 Base URL 仍指向 FCC。也不要假定在启动终端设置 `$env:OPENAI_PROXY` 就能生效：启动器会过滤环境变量，推荐通过 FCC 界面配置。通用 HTTP 代理 / 证书变量可能继承，但 helper 的 `models` / `probe` 会禁用系统 HTTP 代理，直接访问你指定的本地网关。

### 7.3 ChatGPT 订阅登录

在 FCC 中按以下菜单操作：

**Providers → OAuth providers → OpenAI / ChatGPT → Connect**

由你本人检查跳转目标，在真实 provider 授权页面登录并完成授权。不要让 Agent 读取浏览器信息，不要把密码、cookie、OAuth token、refresh token 粘贴给它，也不要复制另一个软件的 OAuth 缓存来“免登录”。

Connected 是登录状态，不是生成或额度证明。授权流程可能因网络、账号权限与提供方政策变化而失败，请以页面真实提示为准。

### 7.4 选实际可用的模型，再 Apply

进入 **Model Config**：

1. 等待提供方模型发现完成。
2. 选择列表中账号实际可用的 **`openai/<实际模型ID>`**。
3. 点击 **Apply**。
4. 订阅测试时让 **Fallback Models 保持为空**，避免请求走到其他收费 provider。

本教程的 `<实际模型ID>` 是占位符，必须替换，不要原样运行，也不要抄另一台电脑的模型名。

- `openai/...`：FCC 的 OpenAI / ChatGPT 订阅适配路线。
- `openai_api/...`：OpenAI Platform API 路线，**独立 API 计费**。

自定义 API 可通过 **Providers → Custom providers → Add provider** 配置；你必须自行确认其协议、Base URL、信任与计费。它不是订阅失败后的默认替代方案。

### 本地网关鉴权（可选但推荐）

FCC 的 **Proxy Authentication** 控制的是本地网关访问权限。启用后，在宿主 API Key 栏填**本地代理 token**，不是提供方 OAuth token。

helper 从当前 PowerShell 的 `MODEL_GATEWAY_TOKEN` 环境变量读取这个本地 token。为避免 token 出现在命令历史，下面只输入到交互提示，不写入脚本或仓库：

```powershell
$localToken = Read-Host '请输入 FCC 的本地 Proxy Authentication token（不是 OAuth token）' -AsSecureString
$env:MODEL_GATEWAY_TOKEN = [System.Net.NetworkCredential]::new('', $localToken).Password
Remove-Variable localToken
```

此变量只在本窗口及它启动的子进程中有效；另开窗口需要重新输入。环境变量不是加密保险箱，不要输出它、导出全部环境变量或把终端诊断原样公开。使用完成可清除：

```powershell
Remove-Item Env:MODEL_GATEWAY_TOKEN -ErrorAction SilentlyContinue
```

如果没有启用 Proxy Authentication，就不需要此变量。不要把真正的 OAuth token 当成本地 API key。

## 8. 先做不生成文本的检查

保留终端 A 的服务，另开普通 PowerShell 作为终端 B。**重新设置变量**：

```powershell
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
$g = Join-Path $s 'scripts\gateway.py'
python -I "$g" doctor
Invoke-RestMethod -Uri 'http://127.0.0.1:18082/health' -Method Get
```

若启用了 Proxy Authentication，先按上一节在终端 B 设置本地 token。再查看模型列表：

```powershell
python -I "$g" models --base-url http://127.0.0.1:18082/v1
```

| 检查 | 是否请求模型生成 | 能证明什么 / 不能证明什么 |
|---|---|---|
| `doctor` | 否 | helper 版本、PATH 和默认目录；不检查登录 |
| `GET /health` | 否 | HTTP 服务的健康状态；不证明上游已就绪 |
| `models` | 否 | 模型列表；**可能触发上游模型发现网络**，不证明额度或生成 |

公共模型视图可能含宿主别名；订阅路线仍以管理页实际选择的 provider-prefixed `openai/<id>` 为准。健康检查或 Connected 不能代替真实生成验收。

如 health 被你的部署配置要求鉴权，应按其规则发送本地 token，不要关闭认证来绕过检查，也不要误用 OAuth token。

## 9. 配置普通 HTTP Agent

先确认宿主支持**自定义端点**和你打算用的协议。只支持固定云端服务、不允许自定义 Base URL 的产品，不能靠本 Skill 自动改变底层模型。

| 宿主字段 | 建议值 / 注意事项 |
|---|---|
| Provider | 自定义 / OpenAI-compatible；名称因宿主而异 |
| Base URL | 对会自动拼接生成路径的客户端填 `http://127.0.0.1:18082/v1` |
| Model | FCC 管理页实际发现并选择的 `openai/<实际模型ID>` |
| API Key / Bearer token | 启用网关认证时填本地 Proxy Authentication token；未启用时按宿主行为处理，不填 OAuth token |
| Streaming | Chat 根据宿主能力；固定 FCC Responses 必须流式 |
| Tools | 需要宿主、协议转换和模型均支持，单独验证工具结果回传 |

如果宿主要求的是“完整请求 URL”而非 Base URL，应按它的文档填写完整端点；不要让客户端把 `/chat/completions` 重复拼接两次。helper 的 `--base-url` 一律要求停在 `/v1`。

### 三个端点是三种协议

| 完整路径 | 协议 | 本教程的状态与限制 |
|---|---|---|
| `/v1/chat/completions` | OpenAI Chat Completions：`messages`、Chat JSON / SSE | helper 默认路线；建议 metadata overlay；JSON、SSE、tools 要分项验收 |
| `/v1/responses` | 原生 OpenAI Responses：`input`、Responses 事件 / output | **该固定 FCC 版本 stream-only**，不能使用 `stream=false` JSON |
| `/v1/messages` | Anthropic Messages 形状 | FCC 提供的协议入口；本 helper 没有对应探针，不表示任意 Anthropic SDK 已测兼容 |

不能仅改路径就把一种协议变成另一种。SDK 可能额外使用特定认证头、版本头、状态管理和流事件；本教程没有承诺所有 SDK、所有 Agent 自动兼容或自动换模型。HTTP 连通和完整工具多轮兼容是不同层次。

## 10. 可选：明确同意消耗额度后做生成验收

**可以跳过本节。只有你明确同意消耗账号额度，才手动执行某一条命令。** `--confirm-usage` 是执行防护，不是无消耗选项。所有探针只发固定简短测试，不发送知识库数据。

先确认模型 ID 已替换为真实值，提供方发现已完成、网络正常、订阅测试 fallback 为空。不要把下面几条全选执行：

| 你选的探针 | 单次完整运行的模型请求数 | 覆盖 |
|---|---:|---|
| Chat 普通 | 2 | 非流式 JSON + SSE |
| Chat `--tools` | 4 | 上述两次 + 原生工具调用与结果回传两次 |
| Responses `--stream-only` | 1 | 原生 SSE；JSON 明确标记跳过 |
| Responses `--stream-only --tools` | 3 | 上述一次 + 原生工具往返两次 |

这是 helper 在完整正常路径下的次数；失败可能提前停止，上游重试或 fallback 可能增加消耗。分别运行普通与 tools 不是增量测试，而是各自重新执行：例如两条 Chat 命令都运行会共发起最多正常路径的 6 次请求，再加可能的上游重试。

### Chat 路线：建议使用兼容层启动

普通验收（2 次生成请求）：

```powershell
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --confirm-usage
```

或者包含工具验收（完整运行 4 次，不是只追加 2 次）：

```powershell
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --tools --confirm-usage
```

工具是固定的 `gateway_probe` 合成 nonce 测试，不执行任意程序、不调用你的真实业务工具。它检查调用 ID、参数、流式分片和工具结果是否被模型消费，不证明整个 Agent 应用正确。

### 原生 Responses 路线：固定版本只测流式

普通流式验收（1 次生成请求）：

```powershell
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --api openai-responses --stream-only --confirm-usage
```

或者包含工具验收（完整运行 3 次）：

```powershell
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --api openai-responses --stream-only --tools --confirm-usage
```

该路线不依赖 Chat metadata 转换层。`--stream-only` 只适用于 `--api openai-responses`，不能用于 Chat。JSON 会输出 `tested=false` 的跳过说明，**不是通过**；工具回传保留完整原始 Responses output，包括 reasoning，不只回放 function_call。

### 如何读结果

- Chat 的 JSON、SSE、tools_roundtrip 要分别看；只过 SSE 不等于 JSON / tools 都过。
- Responses 的流式检查依赖完整终止事件，不把半截流当成功。
- `billing_verified=false` **有意如此，不是缺少登录的错误**。协议通过不能独立证明订阅账单、余额、剩余额度或提供方政策允许的所有用法。
- 失败后先排查启动状态、网络和错误类型，**不要用无限生成重试来诊断**。

## 11. 接入 WeKnora

完整说明见 **[references/weknora.md](../references/weknora.md)**。WeKnora 是 HTTP 客户端，不需要加载 Skill 才能连接，也不应该持有 OpenAI OAuth refresh token。

先打印参考配置（**不生成、不访问 WeKnora 数据库、不创建模型**）：

```powershell
python -I "$g" weknora-config --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>'
```

如果你明确选用原生 Responses，则打印另一种协议配置：

```powershell
python -I "$g" weknora-config --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --api openai-responses
```

两种路线不要混填。输出只是参考字段，**不是可直接提交的完整 create-model API 请求**。在 WeKnora 中新增一个远程对话模型，不覆盖已有模型：

- 来源：远程 `remote`，不是 Ollama 本地模型。
- 提供商：自定义 / OpenAI 兼容，内部 `generic`。
- 模型名：管理页真实 `openai/<实际模型ID>`，保留 `openai/` 前缀。
- 高级 → 远端模型名：填写同一个完整 `openai/<实际模型ID>`，同样保留 `openai/` 前缀；对应 `parameters.extra_config.remote_model_name`。
- Base URL：**WeKnora 后端实际能访问的地址**，同机原生部署可为 `http://127.0.0.1:18082/v1`。
- API Key：启用网关认证时填本地 Proxy Authentication token。
- API 协议：Chat 选 `openai-completions`；Responses 选 `openai-responses`，并遵守 stream-only 限制。

### Chat 高级 JSON：`thinking_format=none`

在 WeKnora 模型编辑器的“高级 → compat JSON / 兼容性覆盖”中填写下面的**扁平对象**；当前源码保存位置是 `parameters.spec.compat`：

```json
{
  "thinking_format": "none"
}
```

这让 WeKnora 的 Chat 请求不再发出 thinking 控制字段，例如 generic 默认可能使用的 `chat_template_kwargs.enable_thinking`。**不要把 `thinking_format` 嵌到 `chat_template_kwargs` 中，也不要把这段兼容配置直接当成上游请求 body。** 它不等于强行关闭模型自身推理。若已有 compat JSON，应谨慎合并，不覆盖无关设置；其他 WeKnora 版本请按其界面和字段文档确认位置。

若旧模型仍有 `extra_config.thinking_control`，该旧设置可能覆盖 `spec.compat`。检查并移除冲突值，或设为目标版本支持的 `none`；不要为了单个模型修改全局 Generic 默认。保存后重新打开模型，确认模型名、远端模型名、URL、协议与 compat JSON 均已持久化。

`chat_template_kwargs` 导致的 **400** 是请求参数问题；`response.metadata` 导致的 **502** 是响应转换事件问题。它们是两个不同问题，`--compat-metadata` **只处理 metadata**，不能用来解决前者。

### Docker 与 SSRF：不是浏览器能打开就够了

- WeKnora 后端在 Docker 内时，`127.0.0.1` 指容器自己，不是 Windows 宿主机。
- Docker Desktop 常用宿主名 `host.docker.internal`，例如 `http://host.docker.internal:18082/v1`。**先从实际 WeKnora 后端环境测试 `http://host.docker.internal:18082/health`**，具体非生成检查命令见 [WeKnora 说明](../references/weknora.md#4-docker-网络与-ssrf先诊断不直接开放端口)。历史本机容器曾能通过此地址访问 loopback-only FCC，但这不是所有 Docker 部署的保证。
- 本工具有意仅监听 loopback，不自动改防火墙、不开放 LAN。若实际后端健康检查不通，先检查服务、端口和容器网络；只有仍需转发时，再另行审查并批准限定来源、受认证保护的转发或受控同网部署，不要直接暴露管理页。
- WeKnora 的 SSRF 校验拒绝本地 URL 时，由有权限的管理员给**精确 hostname / IP**添加允许项（例如系统 `ssrf.whitelist` 或部署 `SSRF_WHITELIST_EXTRA`，以目标版本文档为准）。**不要关闭 SSRF，不要白名单放行所有地址。**

浏览器在宿主机上打开 FCC 管理页，不证明容器内 Go 后端能连通它。对非 loopback 地址使用 helper 时，还需明确审查并加 `--allow-remote`；它只是客户端安全确认，不会帮你建立转发，也不会自动放宽 WeKnora SSRF。

### WeKnora 应按层验收

1. 本地 FCC health、模型发现和本人登录。
2. 经明确额度许可后的对应协议探针。
3. WeKnora 新模型“测试连接”，随后保存并进行真实流式调试。
4. 一次最小 Agent 工具往返，再测试知识检索 / RAG。
5. 对照真实提供方用量页面核对额度来源。

“测试连接”绿灯只是有限检查；固定版本 Responses 不支持非流式 JSON，非流式连接测试尤其不能当作完整兼容证明。WeKnora 调试、聊天、Agent 或 RAG 也可能实际生成并消耗额度，先征得使用者同意。

**保留现有 embedding / rerank。** 切换对话模型不会自动迁移向量模型、重排、知识库向量维度与检索配置，也不应为此重建或覆盖它们。

## 12. 可选：安装到宿主的 Skill 目录

没有此步骤也能使用网关。仅当宿主支持 Agent Skills 且你希望它阅读此操作流程时再安装。

先查清楚该宿主**实际扫描的 skills 父目录**。以下 `D:\MyAgent\skills` 仅为占位示例，不代表每个 Agent 都用这个目录：

```powershell
python -I "$g" install-skill --skills-dir 'D:\MyAgent\skills'
```

会复制到 `D:\MyAgent\skills\portable-model-gateway`。已有同名目录时拒绝覆盖；不会改全局 settings、权限、默认模型或宿主认证。

`compat/` 不随复制分发。在你确定的新位置重新设置变量、预览并生成兼容层，确认旧的自管实例已停止后再启动：

```powershell
# 请替换为刚才真正使用的宿主目录
$s = 'D:\MyAgent\skills\portable-model-gateway'
$g = Join-Path $s 'scripts\gateway.py'
python -I "$s\scripts\fcc_compat.py"
python -I "$s\scripts\fcc_compat.py" --execute
python -I "$g" start --port 18082 --compat-metadata
```

这组命令使用默认 state directory，因此同一 Windows 用户仍连接原来的独立 runtime 和 FCC home；若你改过 `--state-dir`，预览、生成与启动都要用同一个自定义值。不要让两个实例同时占同一端口。

以后若继续用仓库位置运行，请把 `$s`、`$g` 改回仓库路径。Skill 指令与模型 API 配置仍是两件事。

## 13. 按顺序排查常见问题

先查 **路径 / Python → 安装 → 端口 / health → provider 网络与发现 → 登录 / 本地鉴权 → 模型 ID / 协议 → 参数与转换 → 宿主 / RAG**。不要一遇错就反复运行生成探针。

| 现象 | 优先检查与处理 |
|---|---|
| 脚本找不到，或 `$g` 为空 | 新窗口变量不会继承；重设 `$s`、`$g`，`Test-Path "$g"` 应为 True。仓库根就是 Skill 根 |
| `python` 不存在 / 打开商店 | 安装官方 Python、重开终端、检查 PATH 与商店别名；不要把 FCC pin 改成别的版本 |
| `uv_found=false` | 检查 PATH；如使用独立 uv，先定义 `$uv`、检查版本，在 install-runtime 中加 `--uv-path "$uv"` |
| 旧 uv 不认识 Python 3.14.10 | 使用官方渠道更新或单独安装较新 uv，用 `--uv-path '<新版 uv.exe 的绝对路径>'` 指定；不要静默换 Python 版本 |
| 下载 / TLS 失败 | 检查本人网络、可信代理和证书；不关闭 TLS，不改成未经审查的源 |
| `Runtime exists, possibly partial` | 失败可能留下部分 runtime。先检查实际安装错误，或选择新的 `--state-dir`；**不要盲删整个 home 或默认数据目录**，那里可能有授权状态 |
| `FCC runtime missing` | 确认 install-runtime 成功，安装与启动 state directory 相同；安装计划预览不等于安装完成 |
| 源码指纹不符 / overlay missing or modified | 确认固定 FCC 版本、当前 Skill 位置和 state directory；在当前位置预览生成器。不要改哈希绕过校验、强行覆盖或手改 site-packages |
| `Port unavailable` / 18082 被占用 | 保持已有服务不动；只停止你确认属于自己的实例，或选择另一个空闲端口并同步所有 URL |
| `/health` 正常但 503 / `FCC is still starting` | 等待提供方发现完成，检查 FCC 本地状态与上游网络。健康不等于可生成；不要无限推理重试 |
| 网络超时 / `APIConnectionError` | 先查 FCC 界面出站代理与提供方连接；这不是 metadata overlay 可以修复的问题 |
| 401 | 检查是否启用 Proxy Authentication、当前终端是否设置本地 `MODEL_GATEWAY_TOKEN`；**不能拿 OAuth token 代替** |
| Connected 但生成失败 | Connected 不证明账号有该模型或额度；核对真实 provider 状态、权限和用量，不要转 `openai_api` 静默兜底 |
| 模型不存在 / 走错 provider | 从 FCC 管理页选真实 ID 并 Apply；订阅模型保留 `openai/` 前缀，不用猜测 ID，也不混成 `openai_api/` |
| 明明启动 18082，models / probe 却连错 | 确保每次都有 `--base-url http://127.0.0.1:18082/v1`；helper 默认指向 8082 |
| Base URL 报错 / 404 | helper URL 应停在 `/v1`，不带完整生成路径、用户名密码、query 或 fragment；不跟随 HTTP 重定向 |
| `chat_template_kwargs` 相关 400 | 请求参数问题；检查 WeKnora Chat 高级 JSON 的 `thinking_format: "none"`、协议与合并后的字段，不要当成 metadata 错误 |
| `Chat cannot represent upstream Responses event response.metadata` 502 | 响应转换问题；检查 overlay 是否在当前目录生成、是否带 `--compat-metadata` 启动。此开关只处理 metadata |
| Responses `stream=false` 400 | 固定 FCC 仅支持流式；用 `--api openai-responses --stream-only` 验收，不把跳过 JSON 写成通过 |
| 工具探针失败 | 检查协议、原生 tools、调用 ID、工具结果回传与宿主历史重放；有文本回复不证明 tools 正常 |
| WeKnora SSRF 拒绝本地地址 | 由管理员加精确白名单，不关闭校验、不放行全网；参考 [WeKnora 说明](../references/weknora.md) |
| Docker 后端连接拒绝 | `127.0.0.1` 是容器自己；先从实际后端检查 `host.docker.internal:18082/health`，若不通再查服务、端口和网络；确需转发时另行审查受控方案，不假定所有部署都需要转发 |
| `billing_verified=false` | 有意保留，表示协议测试没有独立验证计费；不是要你提供 OAuth 缓存，也不是额外失败 |

### 旧版 uv：可选的独立安装例子

如果你不想覆盖现有 uv，可用当前用户可写的**新目录**安装官方 PyPI uv，然后明确指定可执行文件。先确认目录不存在；如已存在，选新名字，不要覆盖旧环境：

```powershell
$bootstrap = Join-Path $HOME 'AgentTools\gateway-bootstrap-uv'
# 已在克隆步骤创建 AgentTools；请先确认 $bootstrap 尚不存在
Test-Path "$bootstrap"
```

仅当结果为 `False`，且你同意下载和安装 uv 时：

```powershell
python -I -m venv "$bootstrap"
& "$bootstrap\Scripts\python.exe" -I -m pip install --upgrade uv
$uv = Join-Path $bootstrap 'Scripts\uv.exe'
& "$uv" --version
python -I "$g" install-runtime --uv-path "$uv"
# 审阅预览并同意执行后：
python -I "$g" install-runtime --uv-path "$uv" --execute
```

这是 uv 的辅助安装环境，不是 FCC runtime；FCC 仍安装固定 Python **3.14.10**。不需要修改全局 uv 或系统 Python。若先前已留下部分 FCC runtime，仍须先处理“拒绝覆盖”问题，更新 uv 不会自动清理它。

## 14. 数据、安全、许可和验收边界

### 不该上传或分享的内容

不要提交或上传：凭据、cookie、OAuth token / refresh token、真实本地网关 token、`.fcc/`、整个 FCC home、runtime、venv、模型权重、含敏感请求或响应的原始日志。也不要把它们复制到 Skill 分发目录。

本工具不读 OAuth 凭据；启动 FCC 时使用专属 home，不继承模型 API key 环境变量。运行时仍需处理它自己的登录状态。不要为了“方便迁移”复制旧产品缓存；新状态目录请走本人正式登录流程。

### 本地测试不等于真实模型通过

你可以选择运行仓库离线测试（不启动网关、不调用模型）：

```powershell
python -I -m unittest discover -s "$s\tests" -v
```

部分真实 FCC 转换器回归依赖已安装 FCC，未装时可能跳过；应查看测试输出，不要把 mock 结果或跳过项写成真实订阅验收成功。

**真实订阅 JSON / SSE / tools 的所有组合，以及完整 WeKnora RAG，尚未全部验收。** 具体历史状态与限制见 [VALIDATION.md](../VALIDATION.md)。记录只对指定日期、版本和测试范围有效，不保证某台机器上的服务现在或以后一直运行，也不证明账单来源。

### 上游与许可

上游为 <https://github.com/Alishahryar1/free-claude-code>，作为独立依赖安装，固定 commit：

```text
56621010ada15b633d76ab19178764bb3e81bcc5
FCC 6.19.11 / Python 3.14.10
```

上游归属及 **AGPL-3.0-only** 许可应保留；本集成工具和兼容修改同样按 AGPL-3.0-only 提供。详情见 [LICENSE](../LICENSE)、[upstream.json](../upstream.json) 和生成器源码。修改、再分发或通过网络提供修改版本时，应评估并履行相应源码提供义务。固定 Git commit 没有锁定全部传递依赖，不代表完整构建可复现。

**这不是 OpenAI / Anthropic 官方产品。** 不承诺无限使用、不保证任意订阅模型开放、不承诺任意 Agent 自动换模型，也不会在订阅失败时静默切到 Platform 独立计费 API。
