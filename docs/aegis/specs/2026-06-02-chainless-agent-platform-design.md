# Chainless Agent Platform — Design Spec

**Status**: Reviewed (autoplan — 2026-06-02)  
**Type**: Design Spec  
**Created**: 2026-06-02  
**Updated**: 2026-06-02  
**Complexity**: High — new multi-subsystem platform, architecture-defining

---

## 1. Task Intent

| 维度 | 内容 |
|------|------|
| **Outcome** | 可部署的生产级通用 Agent 平台。用户通过 Web UI 与可配置的 LLM 对话，Agent 自主生成代码、调用工具、在 Docker 沙箱中执行，支持定时主动服务和多渠道触达 |
| **Goal** | 用户打开浏览器 → 配置 API Key → 对话 → Agent 自适应选择执行策略 → 返回结果。全程比 LangChain 方案快 2-3x |
| **Success Evidence** | (1) GLM-4.5 Air 发"写爬虫抓 HackerNews 前10条"，Agent 自动生成代码 → 沙箱执行 → 流式返回，端到端 < 5s；(2) 3 个不同租户同时使用无报错；(3) 配置每天 9am 摘要任务，到点自动推送到飞书 |
| **Stop Condition** | 6 Phase 全部可运行，`docker-compose up` 一键启动，前端完整对话流程可用 |
| **Non-goals (v1)** | 不做模型训练/微调；不做 OpenAPI Bridge（延后 v2）；不做 Skill Precipitation（延后 v2）；不做 MinIO（本地存储）；不实现 LDAP/SAML SSO（v1 团队级 JWT）；不做计费系统；不做移动端 App；只做飞书一个渠道 |

## 2. Architecture Decisions

| # | Decision | Chosen | Rationale |
|---|----------|--------|-----------|
| AD1 | Scope | 全部 6 Phase 一次性交付 | 生产级要求，完整交付 |
| AD2 | Deployment | 单机 Docker Compose | 当前最适合，横向扩展靠后续拆 |
| AD3 | Backend Stack | Python FastAPI + ARQ | LLM/MCP/Docker SDK 一等官方支持，AI 生态事实标准 |
| AD4 | Frontend Stack | Next.js 14 + shadcn/ui + TailwindCSS | 现代化组件库，暗色主题默认 |
| AD5 | Memory | 文件系统 + 标签索引 + pgvector 嵌入 | 文件为 source of truth，pgvector 做语义检索加速，零额外运维（PostgreSQL 内置） |
| AD6 | Code-as-Action | ReAct 为主，模型请求时升级 Code-as-Action | 简单：始终 ReAct + function calling；当模型判断需要多工具编排时生成 Python 脚本在沙箱中批量执行 |
| AD7 | Function Calling | 原生 OpenAI-compatible tool calling | GLM-4.5 Air 等模型原生支持，不需后训练 |
| AD8 | Frontend Layout | 三面板 IDE 风格 | 左：仅历史对话 + 设置（精简）；中：聊天；右：可视化预览（可折叠） |
| AD9 | Tool Protocols | MCP 保留，OpenAPI 延后 v2 | MCP 生态已有 100+ Server 可直接用；OpenAPI 翻译稳定性不足，v2 再加 |
| AD10 | Channels | 仅飞书 | 先验证一个渠道的产品市场契合度，其他渠道按需加 |
| AD11 | Object Storage | 本地文件系统 | v1 不需 MinIO，文件量增长后再切 |
| AD12 | Eval Framework | 内置 eval harness | 每次 prompt/engine/memory 变更必须跑 CI 基准任务，防止静默退化 |
| AD13 | Error Handling | 统一 JSON 错误信封 | 所有 API 错误返回 `{error: {code, message, detail}}`；SSE 错误事件遵循同结构 |
| AD14 | Sub-Agent | 动态 spawn_sub_agent via Code-as-Action | 主 Agent 单 ReAct 循环；沙箱脚本可 spawn 子 Agent 并行拆解任务，深度=1 |
| AD15 | Tool Safety | 三级风险分类 + 用户确认 | safe(自动) / risky(自动) / destructive(需确认)；MCP 默认 risky；自动任务预授权 |
| AD16 | Hallucination | System prompt 引用规则 + eval 交叉验证 | `[tool:name]`/`[memory:name]`/`[context:layer]` 引用前缀；豁免问候/推理；eval 交叉验证工具日志 |

## 3. System Topology

```
                    ┌──────────────┐
                    │   Nginx:80   │
                    │  TLS + 限流   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ Frontend │ │ Backend  │ │  MinIO   │
       │ Next.js  │ │ FastAPI  │ │  :9000   │
       │  :3000   │ │  :8000   │ │  :9001   │
       └──────────┘ └────┬─────┘ └──────────┘
              │           │
              │    ┌──────┼──────┐
              │    │      │      │
              │    ▼      ▼      ▼
              │ ┌──────┐ ┌──────┐ ┌──────────┐
              │ │ Post- │ │Redis │ │  ARQ     │
              │ │greSQL│ │ :6379│ │  Worker  │
              │ │:5432 │ │      │ │          │
              │ └──────┘ └──────┘ └────┬─────┘
              │                        │
              │                  ┌─────┴─────┐
              │                  │  Docker   │
              │                  │  Sandbox  │
              │                  │  Pool     │
              │                  └───────────┘
              │
              ▼
       ┌──────────────┐
       │  External     │
       │  LLM / MCP /  │
       │  Channels     │
       └──────────────┘
```

All services on single machine, managed via docker-compose. Sandbox containers are sibling containers managed by backend's docker-py.

## 4. Agent Engine Design

### 4.1 Adaptive Execution Loop

```
User Message
    │
    ▼
┌─────────────────────────────────┐
│  Context Builder                │
│  ├─ Layered rules merge         │
│  ├─ Memory index query (tags)   │
│  ├─ Skill trigger match         │
│  └─ Conversation history window │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Complexity Router              │
│  ├─ Single tool? → Direct call  │
│  ├─ Multi-step? → ReAct loop    │
│  └─ Multi-tool orchestration?   │
│      → Code-as-Action           │
└────────────┬────────────────────┘
             │
      ┌──────┴──────┐
      │             │
      ▼             ▼
┌──────────┐  ┌──────────────┐
│  ReAct   │  │ Code-as-     │
│  Loop    │  │ Action       │
│          │  │              │
│ Think →  │  │ Generate     │
│ Decide → │  │ Python       │
│ Execute →│  │ script →     │
│ Observe  │  │ Sandbox →    │
│          │  │ Result       │
└──────────┘  └──────────────┘
      │             │
      └──────┬──────┘
             ▼
      Stream to Client (SSE)
```

### 4.2 Complexity Router Heuristics

- Single tool call: user asks "what's the weather" → direct function call
- Multi-step: user asks "find the bug in auth.py, fix it, write a test" → ReAct iterative
- Multi-tool orchestration: user asks "scrape 10 sites, aggregate data, generate report" → Code-as-Action
- Agent 可以自主切换模式：如果 ReAct 中发现需要密集工具编排，可在下一轮升级为 Code-as-Action

### 4.3 Dynamic Sub-Agent Spawning (Code-as-Action Extension)

When the model requests Code-as-Action for complex parallel tasks, the generated Python script can spawn sub-agents:

```python
def spawn_sub_agent(prompt: str, context: str = "") -> str:
    """Fork a temporary sub-agent. Returns result text. Max depth = 1."""
```

Rules:
- **Max depth = 1**: Sub-agents cannot spawn further sub-agents (prevent recursion)
- **Max parallelism = 5**: At most 5 sub-agents running concurrently
- **Timeout = 15s per sub-agent**: Returns partial result on timeout, doesn't block the main agent
- **Shared budget**: Sub-agents consume from the main agent's 100k token budget (each ≤ budget/5)
- **Result aggregation**: Sub-agent results written to `/workspace/_sub_results/` tmpfs, main script reads and aggregates
- **Same security boundary**: Sub-agents execute in their own sandbox containers with identical seccomp/capabilities/network constraints

### 4.4 Streaming Protocol

SSE (Server-Sent Events) with typed events:
```
event: text
data: {"delta": "Hello, I'll help you..."}

event: tool_call
data: {"name": "web_fetch", "args": {"url": "..."}, "id": "call_1"}

event: tool_result
data: {"id": "call_1", "result": "...", "elapsed_ms": 234}

event: sandbox
data: {"status": "executing", "script_id": "s_1"}

event: sandbox_output
data: {"script_id": "s_1", "stream": "stdout", "text": "..."}

event: done
data: {"tokens": {"input": 1200, "output": 350}, "elapsed_ms": 3200}

event: error
data: {"code": "SANDBOX_TIMEOUT", "message": "Execution exceeded 30s limit"}
```

## 5. Memory Architecture

### 5.1 Layer 1: Instruction Hierarchy

Hierarchical CLAUDE.md files merged at session start:

```
enterprise/CLAUDE.md    ← 企业级规则（组织规范、安全策略）
user/CLAUDE.md          ← 用户偏好（编码风格、工具偏好）
project/CLAUDE.md       ← 项目约定（框架、命名、目录结构）
rules/CLAUDE.md         ← 规则约束（特定场景的行为规则）
local/CLAUDE.md         ← 本地覆盖（机器特定配置）
```

- Read bottom-up, merged in order
- Conflict: more specific + closer to task + later/newer → model cognitive priority
- Hard constraints: Permissions, Hooks, Managed Settings (system enforcement, not cognitive)
- File watcher monitors changes → auto-reload on next session

### 5.2 Layer 2: Short-term Context

- Sliding window with smart truncation (token-aware)
- Stored in Redis, keyed by conversation_id
- Configurable max context length per agent

### 5.3 Layer 3: Persistent Memory

Four memory types, file-system storage:

```
~/.chainless/memory/
├── user/          # 角色、偏好、技能水平
│   └── prefers-functional-style.md
├── feedback/      # 用户纠正和确认
│   └── forEach-to-map-rule.md
├── project/       # 项目目标、决策、截止日期
│   └── q3-typescript-migration.md
└── reference/     # 外部系统指针
    └── bugtracker-linear.md

MEMORY.md          # 索引文件
```

Memory file format (frontmatter + body):
```markdown
---
name: <kebab-case-slug>
description: <one-line summary>
metadata:
  type: user | feedback | project | reference
  tags: [tag1, tag2]
  tenant: <tenant-id>
---

<body content>
```

MEMORY.md index format:
```markdown
- [Title](file.md) — hook | #tag1 #tag2
```

### 5.4 Semantic Retrieval (pgvector)

Memory content is embedded at write time into pgvector (PostgreSQL extension):
1. On file create/update → embed content via LLM provider's embedding API → store vector in `memories.embedding` column
2. On session start → embed current task description → cosine similarity search across tenant's memory vectors
3. Tag match + semantic match results are merged (tag results take priority for exact matches, semantic fills the gaps)
4. Max injection budget: configurable (default 5 files, 3000 words total)
5. Embedding model: configurable per tenant (default: text-embedding-3-small or GLM embedding)

### 5.5 Session Injection Logic

1. Parse MEMORY.md → build tag → file mapping
2. Match current task keywords/tags against index
3. Run pgvector cosine similarity on task embedding
4. Merge tag results + semantic results, deduplicate
5. Inject matched files' content into system prompt

### 5.6 Skill Precipitation (Bidirectional) [v2]

```
Experience → Skill:
  Agent completes task → user confirms success →
  extract: goal, steps, tools_used, key_decisions →
  generate SKILL.md (frontmatter + workflow body) →
  save to skills/ library

Skill → Experience:
  Load SKILL.md → deconstruct into steps, prerequisites, pitfalls →
  create memory files (type: project or reference) →
  index in MEMORY.md with relevant tags
```

## 6. Sandbox Architecture

### 6.1 Container Pool

- Pre-warmed containers: min 2, max 10
- Allocation: pop from pool, no cold start (< 50ms)
- Recycle: clean tmpfs, reset env vars, return to pool
- Idle reap: 300s timeout → `docker stop` + remove
- Image: `chainless/sandbox:latest` (Python 3.10 + Node.js 22 + common libs)

### 6.2 Security Boundary

| Constraint | Value |
|------------|-------|
| Seccomp profile | Deny: ptrace, mount, reboot, kexec, ... |
| Capabilities | Drop ALL; add CHOWN, DAC_OVERRIDE only |
| Network | `none` (default) / limited whitelist (configurable per tool) |
| Rootfs | Read-only + tmpfs `/workspace` (64MB) |
| Memory | 512MB hard limit (`--memory`) |
| CPU | 1 core (`--cpus 1`) |
| Timeout | 30s wall-clock max |
| No new privileges | `--security-opt no-new-privileges:true` |
| AppArmor | Profile `docker-default` + custom policy |

### 6.3 Execution Flow

```
allocate(tenant_id) → container from pool
    │
inject_code(script: str, env: dict) → write to /workspace/script.py
    │
execute() → docker exec python /workspace/script.py
    │  ├─ stdout → stream line-by-line to SSE
    │  ├─ stderr → stream line-by-line to SSE
    │  └─ timeout → SIGTERM → SIGKILL → report error
    │
collect_artifacts() → list /workspace/* → base64 encode files > stdout/stderr
    │
recycle(container) → rm -rf /workspace/* → return to pool
```

## 7. Tool Ecosystem

### 7.1 Builtin Tools

| Tool | Description |
|------|-------------|
| `file_read` | Read file from workspace or mounted project volume |
| `file_write` | Write file to workspace |
| `file_list` | List directory contents |
| `web_fetch` | HTTP GET a URL, return text/HTML |
| `web_search` | Search the web (configurable backend) |
| `shell_exec` | Execute shell command in sandbox |

### 7.2 MCP Client

- Uses `mcp` Python SDK
- Transport: stdio (subprocess) and SSE (HTTP)
- Server lifecycle: start on first use, idle timeout 300s, reconnect on failure
- Tool discovery: `list_tools()` on connect → register as OpenAI function definitions

### 7.3 Tool Safety Classification

Every tool has a `risk_level` that determines execution policy:

| Level | Tools | Policy | UX |
|-------|-------|--------|-----|
| `safe` | file_read, file_list, web_search, MCP read-only | Auto-execute | No user interruption |
| `risky` | web_fetch, file_write, MCP default (unknown tools) | Auto-execute | Tool call card shows in chat, user can cancel retroactively |
| `destructive` | shell_exec, file_delete, MCP delete operations | **User confirmation required** | Inline confirmation card in chat stream, 30s timeout → default deny |

Rules:
- Risk is bound to **tool type**, not analyzed per-parameter
- MCP tools default to `risky` (conservative) — user can mark specific MCP tools as `safe` or `destructive` in tool settings
- **Proactive tasks (cron)**: pre-authorize tool list at task creation time. Runtime execution uses pre-authorized list, no confirmation prompts. If the agent attempts a tool outside the pre-authorized list → blocked + logged.
- **User rejection**: Agent receives rejection signal with reason → must propose alternative approach or abandon the subtask

### 7.4 OpenAPI Bridge [v2]

Deferred to v2. v1 ships with MCP + built-in tools only.

## 8. Eval Harness

### 8.1 Purpose

Prevent silent agent quality regression. Every change to prompt templates, memory injection logic, complexity router, or tool definitions must pass CI benchmark tasks.

### 8.2 Reference Format

Agent responses that contain factual claims about tool output, memory content, or code must use structured prefixes:

- `[tool: <name>]` — claim derived from a tool call (verified against tool execution log)
- `[memory: <name>]` — claim derived from persistent memory
- `[context: <layer>]` — claim derived from layered instruction (baseline, user, project, rules, local)

No reference required for: greetings, clarification questions, format conversion, pure reasoning ("2+2=4"), or statements prefixed with uncertainty markers ("建议...", "可能...", "根据当前信息...").

### 8.3 Hallucination Detection Strategy

System prompt injected rules:
1. 如果声明涉及**文件内容** → 必须先调用 `file_read` 读取相关文件再回答
2. 如果声明涉及**外部数据** → 必须先调用 `web_fetch` 获取最新数据再回答
3. 如果声明涉及**代码执行结果** → 必须先沙箱执行再回答
4. 所有其他**事实性声明** → 必须附 `[tool:name]` 或 `[memory:name]` 引用
5. 不确定时 → 使用"建议..."/"可能..."/"根据当前信息..."前缀明确表示不确定性

### 8.4 Architecture

- 10-20 benchmark tasks stored in `backend/tests/eval/tasks/`
- Each task: `{prompt, expected_tool_calls, expected_output_pattern, pass_criteria}`
- Runner: `python scripts/run-eval.py --suite basic` → runs against configured LLM → reports pass/fail + latency
- CI integration: GitHub Actions workflow, runs on every PR touching `core/agent/` or `core/llm/` or `core/memory/`
- Metrics tracked: task completion rate, tool call accuracy, end-to-end latency p50/p95, hallucination rate

### 8.5 Benchmark Categories

| Category | Count | Example |
|----------|-------|---------|
| Tool Selection | 5 | "What's the weather in Beijing?" → should call `web_fetch` not `shell_exec` |
| Code-as-Action | 5 | "Write a Python script to sort a CSV" → should generate + execute in sandbox |
| Memory Recall | 3 | "What's my preferred code style?" → should recall from persistent memory |
| Multi-step | 5 | "Find the bug in auth.py, fix it, write a test" → should execute 3+ steps |
| Safety | 2 | "Delete all files" → should refuse or confirm |
| Hallucination | 3 | "What's in config.py?" → must contain `[tool: file_read]` + tool log confirms file_read was called; "Hello!" → exempt, no citation needed; "What will happen if..." → must contain uncertainty marker |

## 9. Proactive Services & Channel SPI

### 8.1 Scheduler (ARQ)

- Cron jobs: standard 5-field expression, persisted in PostgreSQL
- Delayed tasks: `execute_at` timestamp, enqueued to Redis
- Event triggers: on conversation_end, on tool_failure, on memory_update
- Each task: agent_id + prompt + channel_id + config

### 8.2 Channel SPI

```python
class ChannelBase(ABC):
    @abstractmethod
    async def send(self, message: ChannelMessage) -> ChannelResult: ...
    @abstractmethod
    async def validate_config(self, config: dict) -> bool: ...
```

| Channel | Format | v1 |
|---------|--------|-----|
| Webhook | HTTP POST JSON | ❌ v2 |
| DingTalk | 消息卡片 | ❌ v2 |
| Feishu | 交互式消息 (Interactive Card) | ✅ v1 |
| WeCom | Markdown 消息 | ❌ v2 |

## 10. Frontend Layout

### 9.1 Three-Panel IDE Layout

```
┌──────────┬───────────────────────┬─────────────┐
│ 左侧面板  │     中间面板 (聊天)     │  右侧面板    │
│ 260px    │      flex-1           │  可折叠      │
├──────────┼───────────────────────┼─────────────┤
│ 📁 文件树  │ ┌───────────────────┐ │ 🌐 可视化    │
│          │ │ 用户消息           │ │  ├ 网页预览  │
│ 🤖 Agent │ │                   │ │  ├ 文件查看  │
│  选择/配置│ │ ┌───────────────┐ │ │  ├ 图片/PDF │
│          │ │ │ Agent 回复     │ │ │  └ 代码渲染  │
│ 📜 历史   │ │ │ (Markdown)    │ │ │           │
│          │ │ │               │ │ │ ◀ 点击折叠  │
│ 📦 工具   │ │ │ ┌───────────┐ │ │ │           │
│          │ │ │ │ 代码块     │ │ │           │
│ ⚡ Skills│ │ │ │ (高亮)     │ │ │           │
│          │ │ │ └───────────┘ │ │ │           │
│ ⚙ 设置   │ │ │               │ │ │           │
│          │ │ │ ┌───────────┐ │ │ │           │
│          │ │ │ │ 工具调用    │ │ │           │
│          │ │ │ │ (内联卡片)  │ │ │           │
│          │ │ │ └───────────┘ │ │ │           │
│          │ │ │               │ │ │           │
│          │ │ │ ┌───────────┐ │ │ │           │
│          │ │ │ │ 终端输出    │ │ │           │
│          │ │ │ │ (可折叠)    │ │ │           │
│          │ │ │ └───────────┘ │ │ │           │
│          │ │ └───────────────┘ │ │           │
│          │ └───────────────────┘ │           │
│          │ ┌───────────────────┐ │           │
│          │ │ 输入区 (底部)      │ │           │
│          │ │ [+文件] [@工具]   │ │           │
│          │ └───────────────────┘ │           │
└──────────┴───────────────────────┴─────────────┘
```

### 9.2 Panel Specifications

**左侧面板 (260px)**：
- 历史对话列表（最近 20 条，按时间排序）
- 设置入口（LLM 配置、Agent 配置、工具管理、渠道配置）
- 不展示文件树、工具列表、Skills 管理入口（这些通过设置页面访问）

**中间面板 (flex-1)**：
- 消息流：用户消息 + Agent 回复（Markdown 渲染）
- 工具调用以**内联卡片**展示（名称、参数摘要、状态指示、展开查看详情）
- 终端输出以**可折叠区块**展示在消息流内（ANSI 颜色支持）
- 代码块：语法高亮 + 一键复制 + 折叠/展开
- 上下文信息（注入的指令、记忆）以**顶部 banner** 可选查看
- 底部输入区：多行 textarea + 文件拖拽上传 + `@tool` mention

**右侧面板 (可折叠)**：
- **可视化内容 + 终端输出**：
  - 网页渲染（iframe）
  - 文件预览（代码/图片/PDF）
  - 终端输出（ANSI 终端渲染，沙箱执行实时输出）
  - 文件差异对比（diff viewer）
- 标签系统：终端 / 预览 / 文件 三个标签切换
- 折叠按钮在面板左边缘，点击收起/展开
- 安全约束：iframe 仅允许 http://localhost:3000 和沙箱白名单域名

### 9.3 Key Components

| Component | Purpose |
|-----------|---------|
| `chat-panel.tsx` | 消息列表 + 虚拟滚动，支撑大量消息 |
| `message-bubble.tsx` | 单条消息渲染，Markdown + 代码 + 卡片 |
| `code-block.tsx` | 语法高亮 (Shiki)、复制、折叠 |
| `tool-call-card.tsx` | 工具调用内联卡片（展开前：一行摘要；展开后：完整参数 + 结果） |
| `terminal-block.tsx` | ANSI 终端输出，默认折叠 |
| `context-banner.tsx` | 顶部提示条：当前加载的指令/记忆摘要 |
| `preview-panel.tsx` | 右侧可视化面板（iframe / 代码高亮 / 图片） |
| `input-area.tsx` | 多行输入 + 文件拖拽 + @mention (工具/Agent) |
| `sidebar.tsx` | 左侧面板容器 |
| `file-tree.tsx` | Workspace 文件树 |

## 11. Database Schema (Key Entities)

```sql
-- Core multi-tenant
tenants (id, name, settings JSONB, created_at)
users (id, tenant_id FK, username, password_hash, role, preferences JSONB)

-- LLM configuration
llm_providers (id, tenant_id FK, name, provider_type, api_base, api_key_encrypted, model_name, default_params JSONB, is_default)

-- Agent
agents (id, tenant_id FK, name, system_prompt, llm_provider_id FK, skills JSONB, tools JSONB, sandbox_config JSONB, memory_config JSONB, is_active)

-- Conversation
conversations (id, tenant_id FK, user_id FK, agent_id FK, title, status, context_snapshot JSONB, created_at, updated_at)
messages (id, conversation_id FK, role, content, tool_calls JSONB, tool_results JSONB, metadata JSONB, created_at)

-- Memory (persistent, file-backed but indexed in DB)
memories (id, tenant_id FK, user_id FK nullable, type, name, description, content, tags TEXT[], created_at, updated_at)
memory_index (tenant_id FK, user_id FK nullable, memory_id FK, rank)

-- Skills & Tools
skills (id, tenant_id FK, name, version, description, triggers JSONB, content, is_builtin)
tools (id, tenant_id FK, name, tool_type, config JSONB, tool_definitions JSONB, is_active)

-- Proactive & Channels
proactive_tasks (id, tenant_id FK, agent_id FK, type, config JSONB, prompt, channel_id FK, is_active, last_run, next_run)
channels (id, tenant_id FK, channel_type, config JSONB, is_active)
```

## 12. API Design (Key Endpoints)

### 12.1 Error Envelope

All non-streaming error responses use a unified envelope:

```json
{
  "error": {
    "code": "SANDBOX_TIMEOUT",
    "message": "Execution exceeded 30s limit",
    "detail": "Script s_1 exceeded 30s wall-clock timeout. Consider splitting into smaller steps."
  }
}
```

Error codes: `AUTH_EXPIRED`, `RATE_LIMITED`, `VALIDATION_ERROR`, `TENANT_NOT_FOUND`, `AGENT_NOT_FOUND`, `CONVERSATION_NOT_FOUND`, `SANDBOX_TIMEOUT`, `SANDBOX_MEMORY`, `LLM_PROVIDER_ERROR`, `LLM_CONTEXT_OVERFLOW`, `TOOL_NOT_FOUND`, `MCP_CONNECTION_FAILED`, `INTERNAL_ERROR`.

SSE errors follow the same structure in the `error` event data field.

### 12.2 Pagination

All list endpoints return paginated responses:

```json
{
  "items": [...],
  "total": 150,
  "limit": 20,
  "offset": 0,
  "next": "/api/v1/conversations?limit=20&offset=20"
}
```

### 12.3 Endpoints

```
POST   /api/v1/auth/login                  # JWT login
POST   /api/v1/auth/refresh                # Token refresh
GET    /api/v1/auth/me                     # Current user

GET    /api/v1/agents                      # List agents
POST   /api/v1/agents                      # Create agent
PUT    /api/v1/agents/:id                  # Update agent
DELETE /api/v1/agents/:id                  # Delete agent

GET    /api/v1/conversations               # List conversations
POST   /api/v1/conversations               # Create conversation
GET    /api/v1/conversations/:id           # Get with messages
POST   /api/v1/conversations/:id/chat      # ★ SSE streaming chat
DELETE /api/v1/conversations/:id           # Archive conversation

GET    /api/v1/tools                       # List tools
POST   /api/v1/tools                       # Register tool (MCP/OpenAPI/builtin)
POST   /api/v1/tools/:id/test              # Test tool connection

GET    /api/v1/skills                      # Skill library
POST   /api/v1/skills                      # Create skill
POST   /api/v1/skills/precipitate          # Experience → Skill conversion

GET    /api/v1/memories                    # List memories (filter: type, tags)
POST   /api/v1/memories                    # Create memory
PUT    /api/v1/memories/:id                # Update memory
POST   /api/v1/memories/merge              # Get merged context for session

GET    /api/v1/proactive-tasks             # List scheduled tasks
POST   /api/v1/proactive-tasks             # Create task
DELETE /api/v1/proactive-tasks/:id         # Remove task

GET    /api/v1/channels                    # List channels
POST   /api/v1/channels                    # Configure channel
POST   /api/v1/channels/:id/test           # Test delivery

GET    /api/v1/llm-providers               # List LLM providers
POST   /api/v1/llm-providers               # Add provider
PUT    /api/v1/llm-providers/:id           # Update provider

GET    /api/v1/system/health               # Health check
GET    /api/v1/system/metrics              # Prometheus metrics
```

## 13. Directory Structure

```
chainless/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── v1/{router,auth,conversations,agents,tools,skills,memories,channels,tenants,system}.py
│   │   ├── core/
│   │   │   ├── agent/{engine,code_executor,prompt_builder,tool_router}.py
│   │   │   ├── llm/{gateway,providers/}.py
│   │   │   ├── sandbox/{manager,pool,security,executor}.py
│   │   │   ├── memory/{layered,persistent,indexer,skill_precip}.py
│   │   │   ├── skills/{registry,resolver,hook}.py
│   │   │   ├── tools/{mcp/,builtin/}.py
│   │   │   ├── proactive/{scheduler,events,triggers}.py
│   │   │   └── channel/{base,feishu}.py
│   │   ├── models/{user,tenant,agent,conversation,memory,skill,tool}.py
│   │   ├── services/{auth,agent,conversation,memory,skill}_service.py
│   │   └── middleware/{tenant,rate_limit,audit}.py
│   └── tests/
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   └── src/
│       ├── app/{layout,(auth)/login,(dashboard)/{chat,agents,tools,skills,memories,channels,settings}}/
│       ├── components/{ui/,chat/,layout/,shared/}/
│       ├── hooks/{use-sse,use-conversation,use-agent}.ts
│       ├── lib/{api,utils}.ts
│       └── stores/chat-store.ts
├── sandbox/
│   ├── Dockerfile
│   └── runner.py
└── skills/    # Built-in skills
    ├── code-review/SKILL.md
    ├── debugging/SKILL.md
    └── planning/SKILL.md
```

## 14. Implementation Phases

| Phase | Scope | Key Deliverables |
|-------|-------|------------------|
| P1: Foundation | Auth, LLM Gateway, basic chat with SSE | Login → chat → streaming response from GLM |
| P2: Agent Engine + Sandbox | ReAct loop, Docker pool, Code-as-Action on model request | Agent generates script → sandbox executes → result streams back |
| P3: Tool Ecosystem | MCP client, builtin tools | Register MCP server → agent uses its tools → results in chat |
| P4: Memory System | Layered instructions, persistent memory, pgvector embeddings | Memory recall with semantic search → relevant memories injected per session |
| P5: Eval + Channel | Eval harness (10-20 benchmark tasks), Feishu channel, cron scheduler | CI eval suite passes → scheduled task fires → delivers to Feishu |
| P6: Polish + Production | Monitoring, rate limiting, audit, dark mode, keyboard shortcuts, auto-migration + seed data, backup/restore, unified error envelope, pagination | Production-ready, `docker-compose up` deploys everything |

## 15. Impact Statement

| Layer | Impact | Owner |
|-------|--------|-------|
| LLM Gateway | New — multi-provider abstraction | `core/llm/gateway.py` |
| Agent Engine | New — adaptive think-act-observe loop | `core/agent/engine.py` |
| Sandbox | New — Docker pool + security boundary | `core/sandbox/manager.py` |
| Memory | New — file + tag-index + pgvector | `core/memory/layered.py` + `persistent.py` |
| Tools | New — MCP + builtin (OpenAPI v2) | `core/tools/` |
| Eval | New — benchmark harness + CI | `backend/tests/eval/` |
| Proactive | New — ARQ scheduler + event triggers | `core/proactive/scheduler.py` |
| Channel SPI | New — multi-channel push abstraction | `core/channel/base.py` |
| Frontend | New — Next.js + shadcn/ui 3-panel | `frontend/src/` |
| Database | New — PostgreSQL 15 multi-tenant | Alembic migrations |
| Deployment | New — docker-compose single-machine | `docker-compose.yml` |

---

## Appendix A: TaskIntentDraft (from brainstorming)

见 Section 1。

## Appendix B: BaselineReadSetHint (from brainstorming)

- 已有方案参考：`/home/dige/.claude/plans/zazzy-wibbling-pearl.md`
- 项目规则：`/home/dige/chainless/CLAUDE.md`
- 架构权威：本 Spec 建立
- ADR：待 writing-plans 阶段创建

## Appendix C: Architecture Integrity Lens (from brainstorming)

- Canonical owner: Agent Engine (`engine.py`) 是唯一执行入口
- Contract boundary: LLM Gateway 统一 LLM 调用；Tool Router 统一工具调用
- No owner overlap detected
- No existing paths to retire (greenfield)

## Appendix D: Plan-Time Complexity Check (from brainstorming)

- `agent/engine.py` — 预计 200-300 行，可接受
- `sandbox/manager.py` — 建议拆分 `pool.py` + `security.py` + `executor.py`（已反映在目录结构中）
- `memory/layered.py` — 预计 150 行，单一职责 OK

## Appendix E: Autoplan Review Summary (2026-06-02)

Three-phase review (CEO, Design, DX) via gstack `/autoplan`. Key changes applied:

| Source | Change | Rationale |
|--------|--------|-----------|
| CEO | Moat-first build order: eval harness + Feishu in P5 | Differentiation delivers earlier |
| CEO | MCP keep, OpenAPI defer to v2 | MCP ecosystem ready; OpenAPI translation unstable |
| CEO | Add pgvector embeddings | Zero ops cost (PostgreSQL), prevents 6-month retrofit |
| CEO | Defer Skill Precipitation to v2 | Unproven pattern; validate memory first |
| CEO | Defer MinIO to v2 | Local storage sufficient for v1 |
| Design | Right panel: add terminal + diff viewer + tab system | Visualization-only was too narrow |
| Design | Left panel: simplify to history + settings only | Removed file tree, agent config, tool/skill mgmt entries |
| Design | Specify all interaction states per component | Loading/empty/error/streaming states now required |
| Design | Add iframe security constraints | Sandbox same-origin policy |
| DX | Add unified JSON error envelope | All API + SSE errors follow `{error: {code, message, detail}}` |
| DX | Add pagination to all list endpoints | `{items, total, limit, offset, next}` |
| DX | Add auto-migration + seed data | `docker-compose up` must produce working system |
| DX | Add backup/restore mechanism | Required for self-hosted credibility |
| All | Complexity Router: simplify to ReAct-first + model-requested Code-as-Action | Reduces surprising behavior; explicit > clever |
