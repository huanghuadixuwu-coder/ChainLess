import { create } from "zustand";
import { api } from "@/lib/api";

export interface UserInfo {
  user_id: string;
  tenant_id: string;
  username: string;
  role: string;
}

export interface SecretMetadata {
  configured: boolean;
  mask: string | null;
  fingerprint: string | null;
}

export interface LlmProvider {
  id: string;
  name: string;
  api_base: string;
  model: string;
  embedding_model: string | null;
  is_default: boolean;
  api_key: SecretMetadata;
}

export interface ChannelConfiguration {
  id: string;
  channel_type: string;
  enabled: boolean;
  config: {
    label?: string;
  };
  secrets: Record<string, SecretMetadata>;
}

export interface Skill {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  trigger_terms: string[];
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillMatch {
  skill: Skill;
  matched_terms: string[];
}

export interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  llm_provider: string;
  is_active: boolean;
  created_at: string;
}

export interface ToolDefinition {
  function?: {
    name?: string;
    description?: string;
    parameters?: unknown;
  };
  risk: string;
  tool_type: string;
  enabled: boolean;
  risk_override: string | null;
}

export interface ToolTestResult {
  tool_name: string;
  result: unknown;
}

export interface Memory {
  id: string;
  type: string;
  name: string;
  content: string | null;
  description: string | null;
  tags: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryMergeResult {
  context: string;
  memories: Memory[];
  has_instructions: boolean;
}

export interface ProactiveTask {
  task_id: string;
  tenant_id: string | null;
  cron_expr: string;
  agent_id: string;
  prompt: string;
  channel_type: string;
  enabled: boolean;
  created_at: string;
}

export interface ProactiveRun {
  task_id?: string;
  tenant_id?: string | null;
  status?: string;
  delivered?: boolean;
  error?: string | null;
  created_at?: string;
  prompt?: string;
  tool_calls?: string[];
  response_length?: number;
}

export interface EvalSuite {
  name: string;
  task_count: number;
  tasks: Array<{
    id: string;
    criteria?: unknown;
    judge?: unknown;
  }>;
}

export interface EvalStatus {
  suite: string;
  status: string;
  summary: Record<string, unknown> | null;
  updated_at: string | null;
}

export interface EvalRunResult {
  suite: string;
  dry_run: boolean;
  executed: boolean;
  status: string;
  message: string;
  exit_code?: number | null;
  summary?: Record<string, unknown> | null;
}

export interface SystemHealth {
  status: string;
  db: string;
  redis: string;
  worker: string;
  sandbox_pool: number;
  checks: Record<string, Record<string, unknown>>;
}

interface Page<T> {
  items: T[];
  total: number;
}

interface PlatformState {
  currentUser: UserInfo | null;
  providers: LlmProvider[];
  channels: ChannelConfiguration[];
  agents: Agent[];
  tools: ToolDefinition[];
  memories: Memory[];
  memorySearchResults: Memory[];
  memoryMergeResult: MemoryMergeResult | null;
  proactiveTasks: ProactiveTask[];
  proactiveRuns: ProactiveRun[];
  skills: Skill[];
  skillMatches: SkillMatch[];
  evalSuites: EvalSuite[];
  evalStatuses: EvalStatus[];
  lastEvalRun: EvalRunResult | null;
  systemHealth: SystemHealth | null;
  systemMetrics: string;
  isLoadingUser: boolean;
  isLoadingSettings: boolean;
  isMutating: boolean;
  error: string | null;
  notice: string | null;

  loadCurrentUser: () => Promise<UserInfo | null>;
  loadSettings: () => Promise<void>;
  clearMessages: () => void;
  reportSettingsError: (message: string) => void;
  createProvider: (body: ProviderCreateInput) => Promise<boolean>;
  updateProvider: (name: string, body: ProviderUpdateInput) => Promise<boolean>;
  testProvider: (name: string) => Promise<void>;
  setDefaultProvider: (name: string) => Promise<void>;
  deleteProvider: (name: string) => Promise<void>;
  createAgent: (body: AgentInput) => Promise<boolean>;
  updateAgent: (id: string, body: Partial<AgentInput>) => Promise<void>;
  deleteAgent: (id: string) => Promise<void>;
  registerMcpTool: (body: RegisterMcpToolInput) => Promise<boolean>;
  configureTool: (name: string, body: ToolConfigurationInput) => Promise<void>;
  testTool: (serverName: string, body: TestToolInput) => Promise<void>;
  deleteMcpServer: (name: string) => Promise<void>;
  createMemory: (body: MemoryInput) => Promise<boolean>;
  updateMemory: (id: string, body: Partial<MemoryInput>) => Promise<void>;
  searchMemories: (query: string) => Promise<void>;
  mergeMemories: (task: string) => Promise<void>;
  deleteMemory: (id: string) => Promise<void>;
  createProactiveTask: (body: ProactiveTaskInput) => Promise<boolean>;
  deleteProactiveTask: (id: string) => Promise<void>;
  configureFeishu: (body: FeishuConfigInput) => Promise<boolean>;
  testFeishu: () => Promise<void>;
  createSkill: (body: SkillInput) => Promise<void>;
  updateSkill: (id: string, body: Partial<SkillInput>) => Promise<void>;
  deleteSkill: (id: string) => Promise<void>;
  matchSkills: (text: string) => Promise<void>;
  runEvalSuite: (suite: string) => Promise<void>;
  refreshSystem: () => Promise<void>;
}

export interface ProviderCreateInput {
  name: string;
  api_base: string;
  api_key: string;
  model: string;
  embedding_model?: string | null;
  is_default?: boolean;
}

export interface ProviderUpdateInput {
  api_base?: string;
  api_key?: string;
  model?: string;
  embedding_model?: string | null;
  is_default?: boolean;
}

export interface FeishuConfigInput {
  label?: string;
  webhook_url?: string;
  secret?: string;
  enabled: boolean;
}

export interface AgentInput {
  name: string;
  system_prompt: string;
  llm_provider: string;
  is_active: boolean;
}

export interface RegisterMcpToolInput {
  name: string;
  tool_type: "mcp";
  config: {
    command: string;
    args: string[];
    env: Record<string, string>;
  };
}

export interface TestToolInput {
  tool_name: string;
  args: Record<string, unknown>;
}

export interface ToolConfigurationInput {
  enabled?: boolean;
  risk_override?: "safe" | "risky" | "destructive" | null;
}

export interface MemoryInput {
  type: string;
  name: string;
  content: string;
  tags: string[] | null;
  description: string | null;
}

export interface ProactiveTaskInput {
  cron_expr: string;
  agent_id: string;
  prompt: string;
  channel_type: string;
}

export interface SkillInput {
  name: string;
  description: string | null;
  trigger_terms: string[];
  enabled: boolean;
}

const readJson = async <T>(response: Response): Promise<T> => response.json();

const pageItems = <T>(page: Page<T>): T[] => page.items || [];

const loadProviders = async () =>
  pageItems(
    await readJson<Page<LlmProvider>>(
      await api.get("/api/v1/llm-providers/?limit=100")
    )
  );

const loadChannels = async () =>
  pageItems(
    await readJson<Page<ChannelConfiguration>>(
      await api.get("/api/v1/channels?limit=100")
    )
  );

const loadAgents = async () =>
  pageItems(
    await readJson<Page<Agent>>(await api.get("/api/v1/agents/?limit=100"))
  );

const loadTools = async () =>
  pageItems(
    await readJson<Page<ToolDefinition>>(
      await api.get("/api/v1/tools/?limit=200")
    )
  );

const loadMemories = async () =>
  pageItems(
    await readJson<Page<Memory>>(await api.get("/api/v1/memories/?limit=100"))
  );

const loadProactive = async () => {
  const [tasks, runs] = await Promise.all([
    readJson<Page<ProactiveTask>>(
      await api.get("/api/v1/proactive-tasks?limit=100")
    ),
    readJson<Page<ProactiveRun>>(
      await api.get("/api/v1/proactive-tasks/runs?limit=100")
    ),
  ]);
  return { tasks: pageItems(tasks), runs: pageItems(runs) };
};

const loadSkills = async () =>
  pageItems(
    await readJson<Page<Skill>>(await api.get("/api/v1/skills/?limit=100"))
  );

const providerPath = (name: string) =>
  `/api/v1/llm-providers/${encodeURIComponent(name)}`;

const agentPath = (id: string) => `/api/v1/agents/${encodeURIComponent(id)}`;

const memoryPath = (id: string) => `/api/v1/memories/${encodeURIComponent(id)}`;

export const usePlatformStore = create<PlatformState>((set, get) => ({
  currentUser: null,
  providers: [],
  channels: [],
  agents: [],
  tools: [],
  memories: [],
  memorySearchResults: [],
  memoryMergeResult: null,
  proactiveTasks: [],
  proactiveRuns: [],
  skills: [],
  skillMatches: [],
  evalSuites: [],
  evalStatuses: [],
  lastEvalRun: null,
  systemHealth: null,
  systemMetrics: "",
  isLoadingUser: false,
  isLoadingSettings: false,
  isMutating: false,
  error: null,
  notice: null,

  loadCurrentUser: async () => {
    set({ isLoadingUser: true, error: null });
    try {
      const user = await readJson<UserInfo>(await api.get("/api/v1/auth/me"));
      set({ currentUser: user, isLoadingUser: false });
      return user;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load current user";
      set({ currentUser: null, isLoadingUser: false, error: message });
      return null;
    }
  },

  loadSettings: async () => {
    set({ isLoadingSettings: true, error: null });
    try {
      const [
        providers,
        channels,
        agents,
        tools,
        memories,
        proactiveTasks,
        proactiveRuns,
        skills,
        evalSuites,
        evalStatuses,
        systemHealth,
        metricsResponse,
      ] = await Promise.all([
        readJson<Page<LlmProvider>>(
          await api.get("/api/v1/llm-providers/?limit=100")
        ),
        readJson<Page<ChannelConfiguration>>(
          await api.get("/api/v1/channels?limit=100")
        ),
        readJson<Page<Agent>>(await api.get("/api/v1/agents/?limit=100")),
        readJson<Page<ToolDefinition>>(await api.get("/api/v1/tools/?limit=200")),
        readJson<Page<Memory>>(await api.get("/api/v1/memories/?limit=100")),
        readJson<Page<ProactiveTask>>(
          await api.get("/api/v1/proactive-tasks?limit=100")
        ),
        readJson<Page<ProactiveRun>>(
          await api.get("/api/v1/proactive-tasks/runs?limit=100")
        ),
        readJson<Page<Skill>>(await api.get("/api/v1/skills/?limit=100")),
        readJson<Page<EvalSuite>>(await api.get("/api/v1/eval/suites?limit=100")),
        readJson<Page<EvalStatus>>(await api.get("/api/v1/eval/status?limit=100")),
        readJson<SystemHealth>(await api.get("/api/v1/system/health")),
        api.get("/api/v1/system/metrics"),
      ]);

      set({
        providers: pageItems(providers),
        channels: pageItems(channels),
        agents: pageItems(agents),
        tools: pageItems(tools),
        memories: pageItems(memories),
        proactiveTasks: pageItems(proactiveTasks),
        proactiveRuns: pageItems(proactiveRuns),
        skills: pageItems(skills),
        evalSuites: pageItems(evalSuites),
        evalStatuses: pageItems(evalStatuses),
        systemHealth,
        systemMetrics: await metricsResponse.text(),
        isLoadingSettings: false,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to load settings";
      set({ isLoadingSettings: false, error: message });
    }
  },

  clearMessages: () => set({ error: null, notice: null }),

  reportSettingsError: (message) => set({ error: message, notice: null }),

  createProvider: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/llm-providers/", body);
      set({
        providers: await loadProviders(),
        isMutating: false,
        notice: "Provider saved.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save provider";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  updateProvider: async (name, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.put(providerPath(name), body);
      set({
        providers: await loadProviders(),
        isMutating: false,
        notice: "Provider updated.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update provider";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  testProvider: async (name) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post(`${providerPath(name)}/test`, {});
      set({ isMutating: false, notice: "Provider test completed." });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Provider test failed";
      set({ isMutating: false, error: message });
    }
  },

  setDefaultProvider: async (name) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post(`${providerPath(name)}/default`, {});
      set({
        providers: await loadProviders(),
        isMutating: false,
        notice: "Default provider updated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to set default provider";
      set({ isMutating: false, error: message });
    }
  },

  deleteProvider: async (name) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(providerPath(name));
      set({
        providers: await loadProviders(),
        isMutating: false,
        notice: "Provider deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete provider";
      set({ isMutating: false, error: message });
    }
  },

  createAgent: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/agents/", body);
      set({
        agents: await loadAgents(),
        isMutating: false,
        notice: "Agent saved.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save agent";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  updateAgent: async (id, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.put(agentPath(id), body);
      set({
        agents: await loadAgents(),
        isMutating: false,
        notice: "Agent updated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update agent";
      set({ isMutating: false, error: message });
    }
  },

  deleteAgent: async (id) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(agentPath(id));
      set({
        agents: await loadAgents(),
        isMutating: false,
        notice: "Agent deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete agent";
      set({ isMutating: false, error: message });
    }
  },

  registerMcpTool: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/tools/", body);
      set({
        tools: await loadTools(),
        isMutating: false,
        notice: "MCP server registered.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to register MCP server";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  configureTool: async (name, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.patch(
        `/api/v1/tools/${encodeURIComponent(name)}/configuration`,
        body
      );
      set({
        tools: await loadTools(),
        isMutating: false,
        notice: "Tool configuration updated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to configure tool";
      set({ isMutating: false, error: message });
    }
  },

  testTool: async (serverName, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await readJson<ToolTestResult>(
        await api.post(
          `/api/v1/tools/${encodeURIComponent(serverName)}/test`,
          body
        )
      );
      set({ isMutating: false, notice: "Tool test completed." });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Tool test failed";
      set({ isMutating: false, error: message });
    }
  },

  deleteMcpServer: async (name) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(`/api/v1/tools/${encodeURIComponent(name)}`);
      set({
        tools: await loadTools(),
        isMutating: false,
        notice: "MCP server deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete MCP server";
      set({ isMutating: false, error: message });
    }
  },

  createMemory: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/memories/", body);
      set({
        memories: await loadMemories(),
        isMutating: false,
        notice: "Memory saved.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save memory";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  updateMemory: async (id, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.put(memoryPath(id), body);
      set({
        memories: await loadMemories(),
        isMutating: false,
        notice: "Memory updated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update memory";
      set({ isMutating: false, error: message });
    }
  },

  searchMemories: async (query) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const result = await readJson<Page<Memory>>(
        await api.get(`/api/v1/memories/search?q=${encodeURIComponent(query)}&limit=20`)
      );
      set({
        memorySearchResults: pageItems(result),
        isMutating: false,
        notice: `${result.total || 0} memory match(es) found.`,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to search memories";
      set({ isMutating: false, error: message });
    }
  },

  mergeMemories: async (task) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const result = await readJson<MemoryMergeResult>(
        await api.post("/api/v1/memories/merge", { task })
      );
      set({
        memoryMergeResult: result,
        isMutating: false,
        notice: "Memory context merged.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to merge memories";
      set({ isMutating: false, error: message });
    }
  },

  deleteMemory: async (id) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(memoryPath(id));
      set({
        memories: await loadMemories(),
        memorySearchResults: get().memorySearchResults.filter(
          (memory) => memory.id !== id
        ),
        isMutating: false,
        notice: "Memory deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete memory";
      set({ isMutating: false, error: message });
    }
  },

  createProactiveTask: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/proactive-tasks", body);
      const proactive = await loadProactive();
      set({
        proactiveTasks: proactive.tasks,
        proactiveRuns: proactive.runs,
        isMutating: false,
        notice: "Proactive task saved.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save proactive task";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  deleteProactiveTask: async (id) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(`/api/v1/proactive-tasks/${encodeURIComponent(id)}`);
      const proactive = await loadProactive();
      set({
        proactiveTasks: proactive.tasks,
        proactiveRuns: proactive.runs,
        isMutating: false,
        notice: "Proactive task deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete proactive task";
      set({ isMutating: false, error: message });
    }
  },

  configureFeishu: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/channels", {
        channel_type: "feishu",
        enabled: body.enabled,
        config: {
          label: body.label,
          webhook_url: body.webhook_url,
          secret: body.secret,
        },
      });
      set({
        channels: await loadChannels(),
        isMutating: false,
        notice: "Feishu channel saved.",
      });
      return true;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save Feishu channel";
      set({ isMutating: false, error: message });
      return false;
    }
  },

  testFeishu: async () => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/channels/feishu/test", {});
      set({ isMutating: false, notice: "Feishu test completed." });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Feishu test failed";
      set({ isMutating: false, error: message });
    }
  },

  createSkill: async (body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.post("/api/v1/skills/", body);
      set({
        skills: await loadSkills(),
        isMutating: false,
        notice: "Skill saved.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to save skill";
      set({ isMutating: false, error: message });
    }
  },

  updateSkill: async (id, body) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.put(`/api/v1/skills/${id}`, body);
      set({
        skills: await loadSkills(),
        isMutating: false,
        notice: "Skill updated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to update skill";
      set({ isMutating: false, error: message });
    }
  },

  deleteSkill: async (id) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      await api.delete(`/api/v1/skills/${id}`);
      set({
        skills: await loadSkills(),
        isMutating: false,
        notice: "Skill deleted.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to delete skill";
      set({ isMutating: false, error: message });
    }
  },

  matchSkills: async (text) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const result = await readJson<{ items: SkillMatch[]; total: number }>(
        await api.post("/api/v1/skills/match", { text })
      );
      set({
        skillMatches: result.items || [],
        isMutating: false,
        notice: `${result.total || 0} skill match(es) found.`,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to match skills";
      set({ isMutating: false, error: message });
    }
  },

  runEvalSuite: async (suite) => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const result = await readJson<EvalRunResult>(
        await api.post("/api/v1/eval/run", {
          suite,
          dry_run: true,
          timeout_s: 5,
          min_pass_rate: 0.7,
        })
      );
      const statuses = await readJson<Page<EvalStatus>>(
        await api.get("/api/v1/eval/status?limit=100")
      );
      set({
        evalStatuses: pageItems(statuses),
        lastEvalRun: result,
        isMutating: false,
        notice: "Eval dry-run validated.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to run eval dry-run";
      set({ isMutating: false, error: message });
    }
  },

  refreshSystem: async () => {
    set({ isMutating: true, error: null, notice: null });
    try {
      const health = await readJson<SystemHealth>(
        await api.get("/api/v1/system/health")
      );
      const metrics = await api.get("/api/v1/system/metrics");
      set({
        systemHealth: health,
        systemMetrics: await metrics.text(),
        isMutating: false,
        notice: "System summary refreshed.",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to refresh system";
      set({ isMutating: false, error: message });
    }
  },
}));
