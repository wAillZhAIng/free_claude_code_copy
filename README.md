# Portable Model Gateway · 中文入门

把 FCC（Free Claude Code）提供的模型网关，接到支持自定义 HTTP 端点的 Agent 或 WeKnora。**本仓库是自包含的集成 Skill 与操作工具，不是重新实现 FCC，也不是“无限免费模型”服务。**

第一次使用请从 **[Windows 小白教程](docs/QUICKSTART.zh-CN.md)** 开始。它包含普通用户安装 Python / Git / uv、登录、代理设置、验收和排错的完整步骤。

## 先理解边界

- FCC 的管理界面、OAuth、模型发现、路由和协议转换来自**独立安装的上游运行时**；本仓库提供隔离安装、诊断、兼容层与协议探针。
- ChatGPT 订阅路线在 FCC 中使用 `openai/<实际模型ID>`；`openai_api/<实际模型ID>` 是 **OpenAI Platform API 独立计费路线**。不能把订阅当作 Platform 余额，也不要静默 fallback 到收费 API。
- OAuth 显示 Connected 只表示连接状态，不证明模型权限、剩余额度、真实生成或账单来源。第三方适配不代表提供方允许任意工作负载，请自行确认账号权限和服务条款。
- 安装 Skill 不会自动替换任何 Agent 的底层模型。宿主必须支持相应协议和自定义 Base URL；不支持时需要专门适配。
- 不读取或迁移浏览器 cookie、OAuth 缓存、其他产品的 token。授权登录必须由本人在真实 provider 页面完成。

## 从哪里开始

| 你要做的事 | 入口 |
|---|---|
| 第一次在 Windows 上安装和运行 | [详细中文教程](docs/QUICKSTART.zh-CN.md) |
| 给 Agent 阅读操作边界与步骤 | [SKILL.md](SKILL.md) |
| 接入 WeKnora / Docker / SSRF 排错 | [references/weknora.md](references/weknora.md) |
| 看哪些验证通过、哪些仍未完成 | [VALIDATION.md](VALIDATION.md) |
| 查看固定上游与许可 | [upstream.json](upstream.json)、[LICENSE](LICENSE) |

## 仓库布局

仓库根目录本身就是一个 self-contained Skill，**不是**在仓库里面再找一层 `portable-model-gateway/`。

```text
free_claude_code_copy/
├── README.md
├── SKILL.md
├── LICENSE
├── upstream.json
├── VALIDATION.md
├── docs/QUICKSTART.zh-CN.md
├── scripts/
│   ├── gateway.py
│   ├── fcc_compat.py
│   └── fcc_launcher.py
├── references/weknora.md
└── tests/
```

不必复制到任何 Skill 目录也能运行。运行数据默认位于 `%LOCALAPPDATA%\portable-model-gateway`，不在仓库中：`runtime/` 是 FCC 独立环境，`home/.fcc/` 是本工具专属的 FCC 配置和授权状态。不要上传凭据、模型权重、venv、runtime 或 `.fcc`。

## 已装好 Python / Git / uv？最短操作路径

以下为 **Windows 普通用户 PowerShell** 命令，不需要管理员终端。尚未安装依赖时，先读详细教程：helper 使用官方 Python **3.10+（建议 3.12）**，FCC 另由 uv 安装固定的 **Python 3.14.10**。不要改 pin 来迁就系统 Python。

### 1. 克隆、诊断、预览安装

```powershell
New-Item -ItemType Directory -Force -Path (Join-Path $HOME 'AgentTools') | Out-Null
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
git clone --branch main https://github.com/wAillZhAIng/free_claude_code_copy.git "$s"
$g = Join-Path $s 'scripts\gateway.py'
python -I "$g" doctor
python -I "$g" install-runtime
```

`$s` 是仓库根目录，`$g` 是脚本绝对路径。**每开一个 PowerShell 窗口，都要重新赋值**；不要求当前工作目录位于仓库中。若目录已经克隆，不要重复 clone，直接赋值即可。

`doctor` 不读凭据、不访问 provider；`install-runtime` 不带 `--execute` 仅打印计划。安装会下载 Python 和依赖、执行第三方构建代码，审阅计划并同意后才运行下一步。

### 2. 明确安装，再生成本机兼容层

```powershell
python -I "$g" install-runtime --execute
python -I "$s\scripts\fcc_compat.py"
python -I "$s\scripts\fcc_compat.py" --execute
```

对于 Chat Completions 路线，建议使用该兼容层：它校验固定 FCC 转换器源码指纹，在本仓库生成 `compat/fcc_responses_stream.py`，**不改已安装包、不改登录文件**。源码或已有副本不符会拒绝覆盖。它只补充 `response.metadata` 的保留处理，不负责网络、鉴权、额度或其他转换错误。

### 3. 前台运行，保持此终端打开

```powershell
python -I "$g" start --port 18082 --compat-metadata
```

- 管理页：<http://127.0.0.1:18082/admin>
- 宿主 Base URL：`http://127.0.0.1:18082/v1`
- 仅监听本机 loopback；不会自动开放局域网。
- 命令持续占用终端是正常现象。只用 Ctrl+C 停止自己启动的实例；端口占用时不要停止他人的服务。

脚本默认端口是 **8082**，本教程统一显式使用 **18082**。后续 `models` / `probe` / `weknora-config` 也必须指定对应 `--base-url`，否则会连到默认 8082。

### 4. 本人登录并选模型

在 FCC 管理页依次选择 **Providers → OAuth providers → OpenAI / ChatGPT → Connect**，本人检查真实 provider 授权页面并完成登录。不要向 Agent 发送密码、cookie 或 OAuth token，也不要复制旧 OAuth 缓存。

在 **Model Config** 中选择账号实际发现的 `openai/<实际模型ID>`，点击 **Apply**。不要照搬别人的模型 ID；订阅验证阶段保持 **Fallback Models 为空**，避免走到其他付费 provider。

三种容易混淆的设置：

| 设置 | 用途 |
|---|---|
| FCC 界面里的 `OPENAI_PROXY` | FCC 访问上游的出站网络代理；按自己的代理软件实际地址填写 |
| 宿主的 Base URL | Agent / WeKnora 访问 FCC，例如 `http://127.0.0.1:18082/v1` |
| FCC 的 Proxy Authentication token | 本地网关鉴权；启用后填到宿主 API Key，**不是 OAuth token** |

### 5. 另开终端做非生成检查

```powershell
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
$g = Join-Path $s 'scripts\gateway.py'
Invoke-RestMethod -Uri 'http://127.0.0.1:18082/health' -Method Get
python -I "$g" models --base-url http://127.0.0.1:18082/v1
```

启用 Proxy Authentication 后，先按[教程的本地 token 步骤](docs/QUICKSTART.zh-CN.md#本地网关鉴权可选但推荐)为此窗口设置 `MODEL_GATEWAY_TOKEN`。`doctor`、health、models 均不发送生成请求，但 `models` 可能触发上游模型发现网络。健康检查不证明 provider 就绪。

## 接入宿主时，协议要匹配

| 宿主项目 | 填写方式 |
|---|---|
| Provider | 自定义 / OpenAI-compatible（Chat 或 Responses）；Messages 需宿主明确支持该协议 |
| Base URL | 支持自动拼接路径的客户端填 `http://127.0.0.1:18082/v1`，不要再加完整生成路径 |
| Model | FCC 管理页实际选择的 `openai/<实际模型ID>` |
| API Key | 启用 Proxy Authentication 时用本地网关 token；未启用则按宿主要求处理，不填 OAuth token |

`/v1/chat/completions`、`/v1/responses`、`/v1/messages` 是不同协议，不能只改 URL 就当作互相兼容。固定 FCC 版本的 Responses **仅支持流式**，不支持 `stream=false`；不能因此宣称任意 SDK、任意 Agent 都已测试兼容。WeKnora 接法见[专门说明](references/weknora.md)。

## 生成验收是可选的，而且消耗额度

**以下不是安装必做步骤，不会自动执行。确认你愿意消耗账号额度后才运行。** 把模型占位符替换成实际发现的完整 ID：

```powershell
# Chat：普通探针共两次请求（JSON + SSE）
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --confirm-usage
# Chat：带工具验收共四次请求；不是在上面基础上只追加两次
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --tools --confirm-usage
# 原生 Responses：stream-only 一次；加 --tools 则共三次
python -I "$g" probe --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>' --api openai-responses --stream-only --confirm-usage
```

上游重试或 fallback 可能增加消耗。工具探针仅回传合成 nonce，不执行任意本地工具。`billing_verified=false` 是有意保留的：协议通过不证明账单来源。真实订阅 JSON / SSE / tools 的所有组合，以及完整 WeKnora RAG，**尚未全部验收**；以 [VALIDATION.md](VALIDATION.md) 的日期与具体范围为准，不保证其中的现场服务一直运行。

## 可选：安装给支持 Skills 的宿主

```powershell
# 将路径替换成该宿主真实扫描的 skills 父目录
python -I "$g" install-skill --skills-dir 'D:\MyAgent\skills'
```

会新增 `portable-model-gateway/`，已有同名目录时拒绝覆盖；不会自动改宿主模型或权限。生成的 `compat/` 不会复制，**使用新位置启动前，需要在新位置重新预览并执行 `scripts/fcc_compat.py`**。详细命令见教程。

## 来源与许可

- 上游：[Alishahryar1/free-claude-code](https://github.com/Alishahryar1/free-claude-code)。固定 commit：`56621010ada15b633d76ab19178764bb3e81bcc5`，对应 **FCC 6.19.11**。
- FCC 作为独立依赖安装；本集成工具和兼容修改按 **AGPL-3.0-only** 提供，保留上游归属，详见 [LICENSE](LICENSE) 与 [upstream.json](upstream.json)。修改、分发或以网络服务提供修改版本时，应评估相应源码提供义务。
- 固定上游 commit 不等于锁定全部传递依赖，不能宣称完整构建可复现。
- **本项目不是 OpenAI 或 Anthropic 官方产品，也不代表其背书。** 不提供绕过订阅限制、无限额度或通用自动换模型能力。
