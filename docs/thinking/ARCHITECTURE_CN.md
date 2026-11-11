# ARTEMIS 架构设计

> 基于 2026-11 代码库(main @ 371aa6d)的架构分析。ARTEMIS 是一个让 AI 助手 / 测试套件"像人一样操作 Android 真机"的智能体自动化平台(基于 [minitap/mobile-use](https://github.com/minitap-ai/mobile-use) 演进)。
> 官方架构示意图见 [`docs/assets/artemis_architecture_diagram.png`](assets/artemis_architecture_diagram.png)。

整体是清晰的**分层单体 + 多进程运行时**结构,自上而下分六层:

```
┌─ 接入层 ─────────────────────────────────────────────────────────┐
│ CLI · Web 控制台 (FastAPI :8000) · MCP Server · Python 薄客户端 SDK │
├─ 编排层 ─────────────────────────────────────────────────────────┤
│ Pro: LangGraph 状态图 (多智能体循环)   Flash: 单循环响应式执行器     │
├─ 智能体层 ────────────────────────────────────────────────────────┤
│ Planner · Operator · Checker · Validator · Summarizer · Explorer  │
├─ 工具层 ──────────────────────────────────────────────────────────┤
│ 手机动作工具 · ADB/诊断 · 笔记(Scratchpad) · 历史召回 · 视频/日志分析  │
├─ 设备执行层 ───────────────────────────────────────────────────────┤
│ Controllers → Drivers (ADB/scrcpy) → Clients → 设备端无障碍 Helper APK │
├─ 记忆与基础设施 ───────────────────────────────────────────────────┤
│ 会话账本/历史压缩 · Trace 遥测 · 守护进程/设备池 · LLM 路由          │
└──────────────────────────────────────────────────────────────────┘
```

## 1. 接入层(多种入口,共享同一内核)

- **CLI**:`artemis/main.py` → `artemis/interfaces/cli/`,子命令 `run / init / doctor / batch / bench / mcp / server / trace / ui / helper` 等。
- **Web 控制台**:`uv run artemis ui` 起 FastAPI + uvicorn(`artemis/resources/`、`apps/showcase_ui/` 是 Angular 前端,`apps/admin_console/` 是管理台),提供实时投屏、任务队列、推理流观测与回放。
- **MCP Server**:`mcp_server/`(FastMCP,stdio/sse),向 Claude Code / Antigravity / Cursor / Codex 等 IDE 暴露 5 个标准工具(`mobile_run_task`、`mobile_manage_task`、`mobile_get_device_state`、`mobile_inspect_trace`、`mobile_diagnose`)。任务以**分离的后台进程**运行,完成后经多渠道通知器(`notifiers/`:桌面通知、webhook、AgentAPI、文件审计、composite 分发)唤醒 IDE 侧的 agent。`mcp_server/rules.md` 是给 IDE 智能体挂载的"移动端测试思维准则"。
- **Python SDK**:两轨——`packages/artemis-client`(零运行时依赖的**薄 HTTP 客户端**,ADB/模型/图像处理全部留在设备主机侧)和本地 `artemis/sdk/`(嵌入式编程 API)。

## 2. 编排层:双执行模式

核心设计是 **Flash / Pro 双 profile,共用一套会话记录账本**。

### Pro(LangGraph 多智能体图)

入口 `artemis/graph/graph.py` 的 `get_graph()`,每轮循环:

```
planner → convergence → perception → operator → execution_check
   →(分支)→ validator → summarizer → convergence → exit_settlement / END
```

- **Planner** 维护带里程碑和 `verify` / `assert` 检查项的 Markdown 计划。
- **Operator** 按计划执行,持有全套工具(Explorer 定位、笔记、历史召回、视频分析、ADB 诊断)。
- **Validator** 是动作下发前的安全网:XML 树优先、像素兜底校验目标;一轮内多个动作作为快速动作序列(fast-action burst)连发。
- **Checker**(`graph/checkpoints.py` 的检查点账本)只读校验里程碑,退出前对照原始目标终审(`--verification-level`:off / final / checkpoints / strict)。
- 被拦截/失败的动作形成 **execution incident**,持续留在 Operator 上下文直到恢复——没有独立的"修复智能体"。
- 相关模块:`graph/state.py`(状态定义)、`graph/perception.py`(感知节点)、`graph/visibility.py`(strict state 可见性)。

### Flash(响应式单循环)

`artemis/agents/flash/`:不进图编排,单模型"观察 → 思考 → 执行"循环(单步约 3–5 秒),`context_compressor.py` 做历史压缩 + 异步 summarizer;对自动消失的瞬态控件用 `click_sequence` 把多次点击串成原子序列。局限:无计划/笔记、无执行前安全网、无检查点与终审、不能跑 ADB 命令。

## 3. 智能体层(`artemis/agents/`)

每个智能体一个目录,`*.json`(模型/提示配置)+ `*.py`(逻辑);`prompt_assembly.py` 统一组装提示。

| 智能体 | 职责 |
|---|---|
| `planner` | 任务拆解、计划与检查项维护 |
| `operator` | 按计划执行动作、调用工具、事故恢复 |
| `checker` | 检查点与终审 |
| `validator` | 执行前安全网(XML + 像素校验) |
| `summarizer` | 历史/截图压缩为视觉摘要 |
| `explorer` | 元素定位专家;感知深度分 `flash/pro/ultra` 三档(`tiers.py`),结合无障碍树 + OCR + 视觉模型,覆盖 Canvas/Compose/Flutter 自绘 UI |
| `diagnoser` / `log_analyzer` | Logcat 与异常诊断 |
| `history_analyzer` / `video_analyzer` | 历史召回与整段录屏分析 |
| `object_detector` / `image_processor` | 视觉检测与图像处理 |
| `hopper` | 实体抽取(原 legacy "hopper") |
| `outputter` | 报告与结构化输出 |

## 4. 工具与设备执行层

- **工具**(`artemis/tools/`):笔记/scratchpad、`run_adb_command` + `manage_task`(后台任务)、`ask_explorer` / `ask_diagnoser`、历史召回(`search_history` / `replay_steps`)、视频/日志分析、wait 等;`toolchain/`(descriptors + resolver)与 `core/tool_declaration.py` 负责工具声明与解析;`artemis/mcp/`(action_server、actuators、observation、xml_search_server)是动作的服务端执行实现。
- **设备控制链路**:`controllers/`(unified/device controller 抽象)→ `drivers/`(`android/`:adb_driver、hierarchy、input_ime、recorder;另有 `cloud/`、`mock/` + factory)→ `clients/`(`accessibility_client.py`、`ui_automator_client.py`、`adb_tunnel.py`)。
- **设备端组件**:`packages/artemis-accessibility-helper/`(Kotlin/Gradle 编成的 APK)——轻量无障碍服务,读取屏幕布局但不占用 UiAutomation 连接;失效时自动回退 UIAutomator2,并在任务时间线与报告中说明。

## 5. 记忆、遥测与运行时

- **共享历史压缩**(`artemis/memory/` + `data_engine/`):截图折叠为视觉摘要、更早步骤分块归档、可按需召回;`transcript.py` / `step_capsule` 定义会话账本格式。上下文阈值决定何时替换原始记录——这是 Flash 不限步数的基础。
- **Trace / 遥测**(`telemetry/`):结构化轨迹 + 回放;trace 目录布局由 `runtime/trace_store.py` 统一,MCP server、管理台与 worker 进程共享。
- **运行时基础设施**(`artemis/runtime/`):守护进程生命周期(`server_lifecycle`、`daemon_client`、`supervisor`)、设备池与设备锁(`device_pool`、`device_lock`)、防休眠租约(`awake_lease` / `awake_service`)、helper 自动安装(`helper_manager`)、取消请求(`cancel_requests`)——支撑多进程协同与并发多设备。
- **LLM 层**(`llm/`):`router.py` 多模型路由(Gemini / Claude / GPT-4o / Qwen-VL)、`structured.py` + `schemas.py` 结构化输出、`reliability.py` 重试降级、`fake_model.py` 供测试;`services/token_meter.py` 计量。

## 6. 配置与部署

- **配置三层**:`config/artemis.jsonc`(agent 行为,如 `pro.explorer.mode` / `flash.explorer_mode`)、`artemis/config/`(Pydantic settings)、`.env`(环境变量,如 `ARTEMIS_HIERARCHY_BACKEND`、`ARTEMIS_HELPER_AUTO_INSTALL`)。
- **部署**:`Dockerfile` + `start.sh` / `start.bat` 一键装机(自动装 ADB/scrcpy/FFmpeg/uv 并把 MCP 与 rules 挂载到各家 IDE);`playground/` 是容器化演示栈(artemis_container + nginx_container + backend_manager)。
- **质量体系**:`tests/`(unit / integration / e2e / fixtures)、`make test`(确定性主套件,CI 用)、`.quality-baseline.json` 质量棘轮、pre-commit、`pyright-core.json`(核心模块严格类型检查)。

## 设计哲学(一句话)

入口协议多样(CLI / Web / MCP / SDK)但内核唯一;Pro 用 LangGraph 图编排换取"计划 + 执行前校验 + 检查点终审"的可靠性,Flash 用单循环换取速度,两者共享同一压缩历史账本;所有设备侧感知收敛到 drivers / clients / 无障碍 Helper,LLM 路由与工具系统居中解耦。
