# WeKnora：通过 FCC 使用 ChatGPT OAuth 模型

> 本指南基于 Windows + Docker Desktop 的实际配置排查。不同 WeKnora 版本的字段名称可能不同；以目标版本的界面和请求行为为准。首次设置请先读[新手教程](../docs/QUICKSTART.zh-CN.md)。

## 1. 先理解三个独立部分

- **FCC 对话网关**：本指南使用 `127.0.0.1:18082`，由 FCC 处理 OAuth、上游路由和协议转换。
- **WeKnora**：后端调用 FCC 的 HTTP API，不需要加载 `SKILL.md`，也不应持有 OAuth refresh token。
- **Embedding / rerank**：另外部署的检索模型，与 FCC 对话模型独立。本仓库不包含权重或检索模型服务。

修改对话模型不要求重建已有 embedding 索引。更换 embedding 模型则需要单独评估并重建向量，不能把两件事混为一谈。

## 2. 确认打开的是 WeKnora，而不是其他应用

先以你自己的部署端口为准。历史测试环境的前端是 `http://127.0.0.1/`（80），后端宿主端口是 8081；8080 是另一个应用。这些不是所有 WeKnora 的默认值。不要因为某个端口有响应，就认定那是 WeKnora。

先按照新手教程启动 FCC、由本人完成登录，并在 Model Config 中选择账号实际发现的 `openai/<实际模型ID>`。不要将本文占位符原样填写，也不要猜测账号支持哪些模型。

## 3. 填写对话模型

打开 **设置 → 模型管理 → 添加对话模型**。建议新建独立模型，不覆盖其他正在使用的模型。

| 项目 | 设置 |
|---|---|
| 来源 | API / 远程（remote），不是 Ollama local |
| 提供方 | 自定义 / OpenAI 兼容（generic） |
| 模型名称 | FCC 实际发现并选中的 `openai/<实际模型ID>` |
| 高级 → 远端模型名 | 同一个完整 ID，保留 `openai/` 前缀 |
| 请求协议 | `openai-completions` |
| Base URL：WeKnora 后端直接在同一宿主机运行 | `http://127.0.0.1:18082/v1` |
| Base URL：Docker Desktop 容器后端 | `http://host.docker.internal:18082/v1`，需先验证可达及 SSRF 规则 |
| API Key | FCC 开启 Proxy Authentication 后填写本地代理 token；关闭时可留空 |
| 高级 → 协议兼容覆盖（JSON） | `{"thinking_format":"none"}` |

Base URL **只到 `/v1`**，不要包含 `/chat/completions`，也不要填 `/admin`。API Key 不是 ChatGPT 密码、OAuth token 或出站网络代理地址。`openai_api/<ID>` 是不同的 Platform API 计费路径，不要替换 `openai/<ID>` 来假装订阅已连通。

### 必须注意：thinking_format

在“协议兼容覆盖（JSON）”粘贴合法 JSON：

```json
{
  "thinking_format": "none"
}
```

所调查版本的 Generic 提供方默认使用 vLLM/SGLang 风格的 `chat_template_kwargs.enable_thinking`。FCC 目标接口不接受这个字段，会报：

```text
This destination cannot represent Chat fields: chat_template_kwargs
```

`none` 让 WeKnora 不再发送这类思考控制字段，**不等于强制关闭上游模型自身的推理**。单把“思考”开关切为关闭仍可能发送 `enable_thinking:false`，因此不一定能解决问题。

若旧模型存在 `extra_config.thinking_control`，该旧设置可能覆盖 `spec.compat`；需检查并移除冲突值或设为目标版本支持的 none。不要修改全局 Generic 默认来修复单个 FCC 模型。保存后重新打开模型，核对模型名、远端模型名、URL、协议和 JSON 均已持久化。

helper 会输出参考配置，不会替你保存模型：

```powershell
$s = Join-Path $HOME 'AgentTools\free_claude_code_copy'
$g = Join-Path $s 'scripts\gateway.py'
python -I $g weknora-config --base-url http://host.docker.internal:18082/v1 --allow-remote --model 'openai/<实际模型ID>'
```

这里 `--allow-remote` 只允许生成非 loopback URL 的参考字段，不会开放 FCC 监听地址。输出不是完整 create-model API payload，也不包含真实 key。Chat 参考字段的兼容设置位于 `parameters.spec.compat`。

## 4. Docker 网络与 SSRF：先诊断，不直接开放端口

容器里的 `127.0.0.1` 是容器自身，不是 Windows 宿主机。Docker Desktop 通常提供 `host.docker.internal`；Linux Docker 或其他网络环境可能没有同样行为。

在安装了 curl 的实际 WeKnora 后端容器内，可以先做不生成文本的健康检查。替换容器名：

```powershell
docker exec WeKnora-app curl --noproxy '*' --connect-timeout 5 --max-time 15 --fail --silent --show-error http://host.docker.internal:18082/health
```

历史测试环境中，FCC 保持只监听 Windows loopback，也能从实际容器通过这个地址访问；**这不是所有 Docker 部署的保证**。健康正常只证明 HTTP 可达，不证明 OAuth、额度或文本生成。容器没有 curl 时，不要把“命令不存在”误判为服务故障。

如果连接拒绝/超时，不要直接改成 `0.0.0.0`、关闭防火墙或把 `/admin` 暴露出去。先检查服务进程、端口和容器网络；需要转发时，应另行设计限定来源、带认证的方案并明确批准暴露范围。本仓库不自动修改这些设置。

如果报 SSRF 拒绝，由管理员在 WeKnora 支持的系统设置 `ssrf.whitelist` 或部署变量 `SSRF_WHITELIST_EXTRA` 中加入精确主机名：

```text
host.docker.internal
```

- 只填 hostname，不填协议、端口、路径。
- 保留已有侧车主机条目，不要用新值覆盖整份原列表。
- 精确主机名白名单允许访问该主机，不是只允许 18082。
- `.env` 注释行不会生效；环境变量更改需要重新创建对应应用容器，单纯 restart 不会重新读取新环境。
- 对已有部署先审核配置并使用其正式更新流程，不要随意重启整个 Docker。
- 可以检查运行中应用容器的 `SSRF_WHITELIST_EXTRA`，确认实际生效值；仅修改文件并不代表生效。
- 不要关闭 SSRF、放行全网/整个私网，或误填 `local.docker.internet`。

## 5. 为什么只显示文档、没有回答？

检索和回答生成是两个阶段。已经显示引用文档、检索数量，不代表对话模型已生成成功。

若同时出现 `chat_template_kwargs` 的 400：检索成功，生成请求被拒绝。先修改上面的模型级 `thinking_format` 并核对旧设置，再有限重试。不需要因此重建知识库。

若报 `response.metadata` 的 502：这是另一个问题，按新手教程生成兼容副本，再用 `start --compat-metadata` 启动。本兼容层只保留特定响应元数据，**不会删除任意不支持的请求参数**。

“图片无法显示/预览”需要单独调查存储、图片 URL、访问权限和前端请求；不能仅凭这一条 400 判断图片问题同因。

## 6. 保存与验证顺序

1. FCC `/health` 正常，用户本人完成 OAuth、选择模型并 Apply。
2. 确认路由前缀为 `openai/`，订阅排查阶段 Fallback Models 保持为空。
3. 从实际后端环境确认健康接口可达，并核对 SSRF。
4. 保存模型后重新打开，确认配置已保存，而非仅填写草稿。
5. **获得额度使用许可后**，再进行“测试连接”、模型调试或一次短聊天；这些动作可能调用上游。
6. 查看真实流式正文是否出现；绿色连接提示不是全部兼容证明。
7. 如要使用 Agent 工具，再单独验证工具调用和结果回传。
8. 最后在实际使用的 Agent/对话配置中选择该模型，再验证已有知识库问答。新建模型不等于已经绑定到 Agent。
9. 如需确认消费来源，对照 FCC 路由及提供方可见用量记录；HTTP 200、Connected 和模型自报身份均不是独立计费证明。

## 7. 已确认与尚未验收

历史环境已完成三个模型的 UI 保存、刷新核对及本地 embedding/rerank 连接测试；Chat 的 `chat_template_kwargs` 故障已有源码依据。**截至发布准备阶段，原环境的 `thinking_format=none` 尚未代为保存，修正后的完整 WeKnora 生成、工具链和 RAG 尚未验收。** 本文是正确配置与待验收步骤，不是对完整链路已通过的声明。

本仓库没有打包本地 embedding/rerank 服务或模型；不应把单机的 18085 示例当作你已经安装的服务。详见 [VALIDATION.md](../VALIDATION.md)。

## 8. 目标版本源码定位

- `internal/types/model.go`：`parameters.spec.compat` 与模型字段。
- `internal/models/providers/generic.go`：Generic 默认思考格式。
- `internal/models/api/openaicompletions/request.go`：`applyThinking` 在 none 时跳过字段。
- `internal/models/runtime/resolve.go`：模型级兼容与旧 `thinking_control` 的覆盖顺序。
- `internal/models/api/endpoint.go`：URL 拼接和 SSRF 校验。
- `internal/handler/initialization.go`：连接检查限制。
- `internal/handler/model.go`：保存模型后的流式调试。

这些是调查时的文件位置，不承诺其他 WeKnora 版本完全相同。
