# Chainless Agent Platform — Design Spec

**Status**: Draft  
**Type**: Design Spec  
**Created**: 2026-06-02  
**Complexity**: High — new multi-subsystem platform, architecture-defining

---

## 1. Task Intent

| 维度 | 内容 |
|------|------|
| **Outcome** | 可部署的生产级通用 Agent 平台。用户通过 Web UI 与可配置的 LLM 对话，Agent 自主生成代码、调用工具、在 Docker 沙箱中执行，支持定时主动服务和多渠道触达 |
| **Goal** | 用户打开浏览器 → 配置 API Key → 对话 → Agent 自适应选择执行策略 → 返回结果。全程比 LangChain 方案快 2-3x |
| **Success Evidence** | (1) GLM-4.5 Air 发"写爬虫抓 HackerNews 前10条"，Agent 自动生成代码 → 沙箱执行 → 流式返回，端到端 < 5s；(2) 3 个不同租户同时使用无报错；(3) 配置每天 9am 摘要任务，到点自动推送到飞书 |
| **Stop Condition** | 6 Phase 全部可运行，`docker-compose up` 一键启动，前端完整对话流程可用 |
| **Non-goals** | 不做模型训练/微调；不做 RAG/向量数据库；不实现 LDAP/SAML SSO (v1 用 JWT)；不做计费系统；不做移动端 App |

## 2. Architecture Decisions

| # | Decision | Chosen | Rationale |
|---|----------|--------|-----------|
| AD1 | Scope | 全部 6 Phase 一次性交付 | 生产级要求，完整交付 |
| AD2 | Deployment | 单机 Docker Compose | 当前最适合，横向扩展靠后续拆 |
| AD3 | Backend Stack | Python FastAPI + ARQ | LLM/MCP/Docker SDK 一等官方支持，AI 生态事实标准 |
| AD4 | Frontend Stack | Next.js 14 + shadcn/ui + TailwindCSS | 现代化组件库，暗色主题默认 |
| AD5 | Memory | 文件系统 + 标签索引 | 不用 RAG/向量DB，按 MEMORY.md 标签筛选注入 |
| AD6 | Code-as-Action | 自适应模式 | 简单任务 ReAct + function calling；复杂多工具编排走 Python 脚本 + 沙箱 |
| AD7 | Function Calling | 原生 OpenAI-compatible tool calling | GLM-4.5 Air 等模型原生支持，不需后训练 |
| AD8 | Frontend Layout | 三面板 IDE 风格 | 左：文件树 + Agent 配置；中：聊天；右：可视化预览（可折叠） |

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

### 4.3 Streaming Protocol

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

### 5.4 Session Injection Logic

1. Parse MEMORY.md → build tag → file mapping
2. Match current task keywords/tags against index
3. Inject matched files' content into system prompt
4. Max injection budget: configurable (default 3 files, 2000 words total)

### 5.5 Skill Precipitation (Bidirectional)

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

### 7.3 OpenAPI Bridge

- Parse OpenAPI 3.x spec (JSON/YAML) → extract endpoints → generate OpenAI function definitions
- Execute: httpx async HTTP call with parameter mapping
- Auth support: Bearer token, API key header, OAuth2 client credentials
- Cache parsed spec for 1 hour

## 8. Proactive Services & Channel SPI

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

| Channel | Format | Notes |
|---------|--------|-------|
| Webhook | HTTP POST JSON | Generic, any receiver |
| DingTalk | 消息卡片 (ActionCard) | Markdown body + buttons |
| Feishu | 交互式消息 (Interactive Card) | Rich layout + actions |
| WeCom | Markdown 消息 | Simpler format |

## 9. Frontend Layout

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
- 文件树：当前 workspace 目录结构，点击预览文件到右侧面板
- Agent 选择器：下拉切换已配置的 Agent
- 历史对话列表（最近 20 条）
- 工具/Skills 管理入口
- 设置入口

**中间面板 (flex-1)**：
- 消息流：用户消息 + Agent 回复（Markdown 渲染）
- 工具调用以**内联卡片**展示（名称、参数摘要、状态指示、展开查看详情）
- 终端输出以**可折叠区块**展示在消息流内（ANSI 颜色支持）
- 代码块：语法高亮 + 一键复制 + 折叠/展开
- 上下文信息（注入的指令、记忆）以**顶部 banner / tooltip** 可选查看
- 底部输入区：多行 textarea + 文件拖拽上传 + `@tool` mention

**右侧面板 (可折叠)**：
- **仅展示可视化内容**：网页渲染（iframe）、文件预览（代码/图片/PDF）、HTML/SVG 输出
- 折叠按钮在面板左边缘，点击收起/展开
- 左侧或中间面板中的文件点击 → 右侧面板预览
- 不展示文本型的上下文、日志、指标（这些在聊天流内处理）

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

## 10. Database Schema (Key Entities)

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

## 11. API Design (Key Endpoints)

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

## 12. Directory Structure

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
│   │   │   ├── tools/{mcp/,openapi/,builtin/}.py
│   │   │   ├── proactive/{scheduler,events,triggers}.py
│   │   │   └── channel/{base,webhook,dingtalk,feishu,wecom}.py
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

## 13. Implementation Phases

| Phase | Scope | Key Deliverables |
|-------|-------|------------------|
| P1: Foundation | Auth, LLM Gateway, basic chat with SSE | Login → chat → streaming response from GLM |
| P2: Agent Engine + Sandbox | Adaptive loop, Docker pool, Code-as-Action | Agent generates script → sandbox executes → result streams back |
| P3: Tool Ecosystem | MCP client, OpenAPI parser, builtin tools | Register external tools → agent uses them → results in chat |
| P4: Memory System | Layered instructions, persistent memory, skill precipitation | Memory recall works → experience → SKILL conversion |
| P5: Proactive + Channels | Cron scheduler, event callbacks, DingTalk/Feishu/WeCom/Webhook | Scheduled task fires → delivers to configured channel |
| P6: Polish + Production | Monitoring, rate limiting, audit, dark mode, keyboard shortcuts | Production-ready, `docker-compose up` deploys everything |

## 14. Impact Statement

| Layer | Impact | Owner |
|-------|--------|-------|
| LLM Gateway | New — multi-provider abstraction | `core/llm/gateway.py` |
| Agent Engine | New — adaptive think-act-observe loop | `core/agent/engine.py` |
| Sandbox | New — Docker pool + security boundary | `core/sandbox/manager.py` |
| Memory | New — file + tag-index system | `core/memory/layered.py` + `persistent.py` |
| Tools | New — MCP + OpenAPI + builtin | `core/tools/` |
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
