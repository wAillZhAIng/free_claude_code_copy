# 验证记录与已知限制

发布准备日期：2026-11-15。本文区分历史实测、本次离线测试与尚未完成的端到端验收。任何一次健康检查都不保证服务永久运行，也不证明配额或计费归属。

## 固定依赖与分发范围

- 上游：[Alishahryar1/free-claude-code](https://github.com/Alishahryar1/free-claude-code)。
- Commit：`56621010ada15b633d76ab19178764bb3e81bcc5`；FCC 6.19.11；隔离 Python 3.14.10。
- helper 仅使用标准库，要求 Python 3.10+。主机历史 helper Python 为 3.12.2。
- 本仓库分发操作 Skill、安装/诊断/探针 helper、兼容副本生成器和测试；不内嵌 FCC 运行时或任何授权状态。
- 仅固定上游 Git commit，没有锁定全部传递依赖；不声称完整可复现构建。
- `compat/` 必须在本机重新生成，不纳入 Git 或 Skill 安装拷贝。

## 历史实测（不是本次重新调用模型的结果）

| 项目 | 状态与边界 |
|---|---|
| 隔离安装 | 固定版本已安装，使用独立 runtime 与 home，没有复用其他产品凭据 |
| OAuth | 用户本人曾完成 OpenAI / ChatGPT 登录，公共状态曾显示 Connected；未读取 OAuth 文件 |
| 早期离线回归 | 46/46 通过，使用 FCC Python 执行，包含真实转换器回归 |
| 原版 Chat Completions | 真实请求遇到 `response.metadata`，返回 502 |
| 原生 Responses 流式 | 真实文本生成通过，终止为 `response.completed` |
| 原生 Responses tools | 真实合成工具往返通过，保留 call_id 与 reasoning/output 回放 |
| 原生 Responses 非流式 | 固定 FCC 版本明确不支持，`stream=false` 返回 400；不能标为通过 |
| 带 metadata 兼容层的 Chat JSON/SSE/tools | 尚未完成真实完整验收；历史测试遇到启动中 503 与上游超时 |
| Docker Desktop → FCC | 曾从实际 WeKnora 应用容器访问 loopback-only Windows FCC 的 18082 健康接口；不是所有 Docker 部署的保证 |
| WeKnora 模型保存 | 已保存并刷新核对 FCC 对话模型及另外部署的两个检索模型；检索连接测试成功 |
| WeKnora Chat 参数 | 用户真实聊天遇到 `chat_template_kwargs` 的 400，检索结果正常但生成失败 |
| 该参数修正 | 源码确认 `thinking_format=none` 跳过该字段；原环境尚未代为保存或完成生成重测 |
| 完整 WeKnora 工具/RAG | 尚未验收；模型保存与检索成功不能代替最终回答成功 |
| 订阅配额/账单归属 | 未独立验证；不得从 Connected、模型路由或 HTTP 200 推导已验证 |

历史原生 Responses 的三请求工具探针返回 `stream.ok=true`、`tools_roundtrip.ok=true`、`calls=1`、`billing_verified=false`；JSON 明确为跳过。历史上游网络超时只说明当时网络，不代表发布时仍然如此。

## 本次仓库发布验证

本次拟执行发布版检查，但执行仓库 Python 脚本的权限被拒绝，因此**未运行本发布目录的测试、doctor、安装预览或兼容副本生成器**；没有重新登录、读取 provider 凭据或发起订阅 LLM 推理。对本发布目录仅进行源码静态解析、分发文件/相对链接/凭据特征检查和 Git 差异审核；这些不能证明运行正确。下方命令供另行获准后复核，不是本次通过记录。

执行偏差说明：文档协作者报告，曾误运行原发行包（不是新仓库）的只读 `doctor`、`install-runtime` 预览及 `--help`，尽管协调指令要求停止执行目标脚本；随后已停止。安装输出为 `dry_run=true`、诊断显示 `credentials_read=false`，未执行安装、overlay 生成、测试、服务启动、模型探针或生成请求。原发行包命令的输出不能当作本仓库运行验证，也不能把本轮描述成完全没有执行脚本。

```powershell
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
python -I -m unittest discover -s "$s\tests" -v
python -I "$s\scripts\gateway.py" doctor
python -I "$s\scripts\gateway.py" install-runtime
python -I "$s\scripts\gateway.py" weknora-config --base-url http://127.0.0.1:18082/v1 --model 'openai/<实际模型ID>'
```

本次静态检查结果：**14 个分发文件检查通过，其中 5 个 Python 文件完成 AST 语法解析**；相对文档链接、明确分发清单、上游 pin 和常见凭据特征检查均未发现问题。检查器将目标源码仅作为数据读取，未导入或执行目标模块；正则扫描不能证明排除了所有可能的秘密。

- 普通 helper Python 未安装 FCC 时，转换器测试会明确 skip；不能把 skip 当作通过。
- 完整转换器回归需要已授权安装的固定 FCC 运行时，且已在当前仓库位置生成兼容副本。可用该 runtime 的 Python 执行同一套测试，不需要启动服务或调用模型。
- 新增发布防护：Skill 安装只复制 `SKILL_FILES` 的明确文件清单，不复制仓库偶然出现的 `.env`、凭据、运行状态或任意额外文件；缺文件时先拒绝再拷贝。
- `weknora-config` 的 Chat 配置现在包含远端模型名和 `parameters.spec.compat.thinking_format=none`；Responses 不套用 Chat 专属兼容字段。

## 两个兼容问题不要混淆

1. **响应事件** `response.metadata`：`fcc_compat.py` 对原模块校验规范化换行后的 SHA-256，再生成项目内副本。`start --compat-metadata` 只在进程内替换这一个模块，不修改 site-packages。元数据保留为 `provider_metadata`，不拼入正文；未知事件、错误、拒绝与终止校验不放宽。
2. **请求字段** `chat_template_kwargs`：在 WeKnora 模型级设置 `{"thinking_format":"none"}`，必要时清理冲突的旧 `thinking_control`。metadata 副本不负责移除请求参数，也不应静默吞掉所有未知字段。

原模块规范化 SHA-256：`da33b85b4cf450a93b97d69892595e43de36f84730c17e492e2c5750dbba02c5`。指纹不符就停止，不自动改成 latest 或绕过检查。关闭 metadata 兼容层只需在停止自己管理的实例后，不带 `--compat-metadata` 重启。

## 待用户明确批准后再做的验收

- Chat JSON、SSE 与原生工具结果回传。
- 修正参数后的 WeKnora 短聊天、Agent tools 和完整知识库问答。
- 各宿主的专用协议字段、上下文限制、图像输入和高级工具兼容。
- 账号实际模型权限、用量与计费归属。
- Linux/macOS 冷启动、长期稳定性、并发负载和互联网部署安全。

不要无限重试生成；普通 Chat 探针消耗 2 次请求、带 tools 共 4 次；Responses `--stream-only` 为 1/3 次，上游重试可能增加消耗。`--confirm-usage` 只是执行保护，不能替代用户对额度消耗的许可。
