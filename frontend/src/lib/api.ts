interface StreamConfirmation {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  risk: string;
  timeout_s: number;
  worker_policy_context?: Record<string, unknown> | null;
}

interface ConfirmToolRequest {
  tool_call_id: string;
  approved: boolean;
  decision?: "approve" | "deny" | "timeout";
  tool_name?: string;
  args?: Record<string, unknown>;
}

interface StreamHandlers {
  onDelta: (delta: string) => void;
  onContext?: (context: StreamContext) => void;
  onToolCallStart?: (
    toolCallId: string,
    name: string,
    args: Record<string, unknown>,
    risk: string
  ) => void;
  onToolResult?: (
    toolCallId: string,
    name: string,
    result: string,
    artifacts?: StreamArtifact[]
  ) => void;
  onToolError?: (
    toolCallId: string,
    name: string,
    error: string
  ) => void;
  onConfirmationRequired?: (confirmation: StreamConfirmation) => void;
  onCapabilityCandidate?: (candidate: CapabilityCandidateHint) => void;
  onWorkerNotice?: (notice: WorkerNotice) => void;
  onAcquisitionNotice?: (notice: AcquisitionNotice) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

interface ChatStreamOptions {
  attachmentArtifactIds?: string[];
}

interface StreamArtifact {
  id: string;
  conversation_id: string;
  run_id?: string | null;
  tool_call_id?: string | null;
  type: string;
  operation: string;
  path: string;
  state: string;
  mime_type?: string | null;
  size_bytes: number;
  content_bytes_stored: number;
  diff_bytes_stored: number;
  has_content: boolean;
  has_diff: boolean;
  download_url?: string | null;
  preview?: {
    mode: string;
    allowed: boolean;
    reason?: string;
    url?: string;
  };
  created_at?: string;
  updated_at?: string;
  expires_at?: string | null;
}

interface ToolOption {
  name: string;
  description?: string | null;
  risk?: string | null;
  enabled?: boolean;
  tool_type?: string | null;
}

interface UploadedArtifact extends Partial<StreamArtifact> {
  id: string;
  size?: number;
  [key: string]: unknown;
}

interface MessageAttachment extends Partial<StreamArtifact> {
  id: string;
  path: string;
  state?: string;
  size_bytes?: number;
  mime_type?: string | null;
  download_url?: string | null;
}

interface StreamContext {
  memory_count?: number;
  memory_names?: string[];
  has_layered_instructions?: boolean;
  instruction_preview?: string;
  agent?: {
    id?: string | null;
    name?: string;
    provider?: string;
  };
}

interface Page<T> {
  items: T[];
  total?: number;
  limit?: number;
  offset?: number;
}

type CandidateType = "memory" | "skill" | "worker";

type CandidateStatus =
  | "new"
  | "seen"
  | "accepted"
  | "edited_accepted"
  | "dismissed"
  | "snoozed"
  | "muted_pattern"
  | "merged"
  | "archived";

interface CapabilityCandidateHint {
  id: string;
  candidate_type: CandidateType | string;
  status: CandidateStatus | string;
  active?: boolean;
  title: string;
  message?: string;
}

interface CapabilityCandidate extends CapabilityCandidateHint {
  tenant_id: string;
  user_id: string;
  body?: string | null;
  source_run_id?: string | null;
  source_event_id?: string | null;
  source_message_id?: string | null;
  source_uri?: string | null;
  source_kind?: string | null;
  dedupe_key?: string | null;
  merge_target_candidate_id?: string | null;
  merge_reason?: string | null;
  merged_at?: string | null;
  snoozed_until?: string | null;
  mute_pattern?: string | null;
  muted_at?: string | null;
  worker_id?: string | null;
  accepted_at?: string | null;
  accepted_by?: string | null;
  dismissed_at?: string | null;
  archived_at?: string | null;
  evidence: Record<string, unknown>;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface Worker {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  description?: string | null;
  status: string;
  enabled: boolean;
  trigger: Record<string, unknown>;
  policy: Record<string, unknown>;
  active_version_id?: string | null;
  activation_confirmed_by?: string | null;
  activation_evidence: Record<string, unknown>;
  rollback_reason?: string | null;
  soft_deleted_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface WorkerVersion {
  id: string;
  tenant_id: string;
  user_id: string;
  worker_id: string;
  version: number;
  status: string;
  definition: Record<string, unknown>;
  verification_plan: Record<string, unknown>;
  verification_evidence: Record<string, unknown>;
  verified_at?: string | null;
  verified_by?: string | null;
  activated_at?: string | null;
  archived_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface WorkerRun {
  id: string;
  tenant_id: string;
  user_id: string;
  worker_id: string;
  version_id?: string | null;
  source_run_id?: string | null;
  status: string;
  input_payload: Record<string, unknown>;
  output_payload: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  confirmation_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface WorkerNotice {
  status: string;
  worker_id?: string;
  version_id?: string;
  worker_run_id?: string;
  worker_name?: string;
  decision?: string;
  score?: number;
  message?: string;
  reason?: string | null;
  code?: string | null;
  reasons?: string[];
}

interface AcquisitionNotice {
  type: string;
  title?: string;
  message?: string;
  status?: string;
  severity?: string;
  risk_level?: string;
  problem?: string;
  cause?: string;
  next_step?: string;
  recovery?: string;
  gap_id?: string;
  proposal_id?: string;
  permission_id?: string;
  trace_id?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export const TOKEN_CHANGE_EVENT = "chainless-token-change";

class ApiClient {
  private token: string | null = null;

  private normalizeBaseUrl(raw: string) {
    return raw.replace(/\/+$/, "").replace(/\/api\/v1$/, "");
  }

  private getBaseUrl() {
    const configured = process.env.NEXT_PUBLIC_API_URL?.trim();

    if (configured) {
      try {
        const configuredUrl = new URL(configured);
        if (
          typeof window !== "undefined" &&
          configuredUrl.hostname === "localhost" &&
          !["localhost", "127.0.0.1"].includes(window.location.hostname)
        ) {
          return this.normalizeBaseUrl(window.location.origin);
        }
      } catch {
        return this.normalizeBaseUrl(configured);
      }

      return this.normalizeBaseUrl(configured);
    }

    if (typeof window !== "undefined") {
      return this.normalizeBaseUrl(window.location.origin);
    }

    return "http://localhost:8000";
  }

  setToken(t: string) {
    this.token = t;
    if (typeof window !== "undefined") {
      localStorage.setItem("token", t);
      window.dispatchEvent(new Event(TOKEN_CHANGE_EVENT));
    }
  }

  getToken() {
    if (typeof window === "undefined") {
      return this.token;
    }
    return this.token || localStorage.getItem("token");
  }

  clearToken() {
    this.token = null;
    if (typeof window !== "undefined") {
      localStorage.removeItem("token");
      window.dispatchEvent(new Event(TOKEN_CHANGE_EVENT));
    }
  }

  async fetch(path: string, opts: RequestInit = {}) {
    const headers = new Headers(opts.headers);
    if (!(opts.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const token = this.getToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    const res = await fetch(`${this.getBaseUrl()}${path}`, {
      ...opts,
      headers,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${res.status}`);
    }
    return res;
  }

  async post(path: string, body: unknown) {
    return this.fetch(path, { method: "POST", body: JSON.stringify(body) });
  }

  async patch(path: string, body: unknown) {
    return this.fetch(path, { method: "PATCH", body: JSON.stringify(body) });
  }

  async put(path: string, body: unknown) {
    return this.fetch(path, { method: "PUT", body: JSON.stringify(body) });
  }

  async delete(path: string) {
    return this.fetch(path, { method: "DELETE" });
  }

  async get(path: string) {
    return this.fetch(path);
  }

  async streamChat(
    convId: string,
    content: string,
    handlers: StreamHandlers,
    options: ChatStreamOptions = {}
  ) {
    const res = await this.fetch(`/api/v1/conversations/${convId}/chat`, {
      method: "POST",
      body: JSON.stringify({
        content,
        ...(options.attachmentArtifactIds?.length
          ? { attachment_artifact_ids: options.attachmentArtifactIds }
          : {}),
      }),
    });
    await this.consumeStream(res, handlers);
  }

  async listCapabilityCandidates(params: { limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 100),
      offset: String(params.offset ?? 0),
    });
    const res = await this.get(`/api/v1/capability-candidates?${query}`);
    return (await res.json()) as Page<CapabilityCandidate>;
  }

  async getCapabilityCandidate(candidateId: string) {
    const res = await this.get(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}`
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async acceptCapabilityCandidate(
    candidateId: string,
    editedProposal?: Record<string, unknown>
  ) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/accept`,
      editedProposal ? { edited_proposal: editedProposal } : {}
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async dismissCapabilityCandidate(candidateId: string) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/dismiss`,
      {}
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async archiveCapabilityCandidate(candidateId: string) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/archive`,
      {}
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async snoozeCapabilityCandidate(candidateId: string, snoozedUntil: string) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/snooze`,
      { snoozed_until: snoozedUntil }
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async muteCapabilityCandidatePattern(candidateId: string, mutePattern: string) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/mute-pattern`,
      { mute_pattern: mutePattern }
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async mergeCapabilityCandidate(
    candidateId: string,
    targetCandidateId: string,
    mergeReason?: string
  ) {
    const res = await this.post(
      `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/merge`,
      {
        target_candidate_id: targetCandidateId,
        ...(mergeReason ? { merge_reason: mergeReason } : {}),
      }
    );
    return (await res.json()) as CapabilityCandidate;
  }

  async listWorkers(params: { limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 100),
      offset: String(params.offset ?? 0),
    });
    const res = await this.get(`/api/v1/workers?${query}`);
    return (await res.json()) as Page<Worker>;
  }

  async getWorker(workerId: string) {
    const res = await this.get(`/api/v1/workers/${encodeURIComponent(workerId)}`);
    return (await res.json()) as Worker;
  }

  async enableWorker(workerId: string) {
    const res = await this.post(
      `/api/v1/workers/${encodeURIComponent(workerId)}/enable`,
      {}
    );
    return (await res.json()) as Worker;
  }

  async disableWorker(workerId: string) {
    const res = await this.post(
      `/api/v1/workers/${encodeURIComponent(workerId)}/disable`,
      {}
    );
    return (await res.json()) as Worker;
  }

  async deleteWorker(workerId: string) {
    const res = await this.delete(`/api/v1/workers/${encodeURIComponent(workerId)}`);
    return (await res.json()) as Worker;
  }

  async listWorkerRuns(workerId: string, params: { limit?: number } = {}) {
    const query = new URLSearchParams({ limit: String(params.limit ?? 20) });
    const res = await this.get(
      `/api/v1/workers/${encodeURIComponent(workerId)}/runs?${query}`
    );
    return (await res.json()) as { items: WorkerRun[] };
  }

  async listWorkerVersions(workerId: string) {
    const res = await this.get(
      `/api/v1/workers/${encodeURIComponent(workerId)}/versions`
    );
    return (await res.json()) as { items: WorkerVersion[] };
  }

  async rollbackWorker(
    workerId: string,
    body: {
      version_id: string;
      activation_token?: string | null;
      reason?: string | null;
      confirmation_evidence?: Record<string, unknown> | null;
    }
  ) {
    const res = await this.post(
      `/api/v1/workers/${encodeURIComponent(workerId)}/rollback`,
      body
    );
    return (await res.json()) as Worker;
  }

  async sendWorkerFeedback(
    workerId: string,
    body: {
      feedback: string;
      source_run_id?: string | null;
      reason?: string | null;
      metadata?: Record<string, unknown>;
    }
  ) {
    const res = await this.post(
      `/api/v1/workers/${encodeURIComponent(workerId)}/feedback`,
      body
    );
    return (await res.json()) as Record<string, unknown>;
  }

  async getAvailableTools() {
    try {
      const res = await this.get("/api/v1/tools/available");
      const data = await res.json();
      return this.normalizeTools(data);
    } catch {
      const res = await this.get("/api/v1/tools/?limit=200");
      const data = await res.json();
      return this.normalizeTools(data);
    }
  }

  async uploadFile(conversationId: string, file: File) {
    const formData = new FormData();
    formData.append("conversation_id", conversationId);
    formData.append("file", file);
    const res = await this.fetch("/api/v1/uploads/", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (
      data &&
      typeof data === "object" &&
      "artifact" in data &&
      (data as { artifact?: unknown }).artifact
    ) {
      return (data as { artifact: UploadedArtifact }).artifact;
    }
    return data as UploadedArtifact;
  }

  async downloadArtifact(artifact: Pick<StreamArtifact, "id" | "path"> & {
    download_url?: string | null;
  }) {
    const url = artifact.download_url || `/api/v1/artifacts/${artifact.id}/download`;
    const res = await this.fetchDownloadUrl(url);
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = artifact.path.split(/[\\/]/).pop() || "artifact";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  private async fetchDownloadUrl(url: string) {
    if (!/^https?:\/\//i.test(url)) {
      return this.fetch(url);
    }

    const headers = new Headers();
    const token = this.getToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    const res = await fetch(url, { headers });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${res.status}`);
    }
    return res;
  }

  private normalizeTools(data: unknown): ToolOption[] {
    const items = Array.isArray(data)
      ? data
      : data && typeof data === "object" && "items" in data
        ? (data as { items?: unknown[] }).items || []
        : [];

    const normalized: ToolOption[] = [];
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      const record = item as Record<string, unknown>;
      const fn =
        record.function && typeof record.function === "object"
          ? (record.function as Record<string, unknown>)
          : {};
      const name = String(record.name || fn.name || "");
      if (!name) continue;
      normalized.push({
        name,
        description:
          typeof record.description === "string"
            ? record.description
            : typeof fn.description === "string"
              ? fn.description
              : null,
        risk: typeof record.risk === "string" ? record.risk : null,
        enabled:
          typeof record.enabled === "boolean" ? record.enabled : undefined,
        tool_type:
          typeof record.tool_type === "string" ? record.tool_type : null,
      });
    }
    return normalized;
  }

  async streamConfirmation(
    convId: string,
    body: ConfirmToolRequest,
    handlers: StreamHandlers
  ) {
    const res = await this.fetch(`/api/v1/conversations/${convId}/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    await this.consumeStream(res, handlers);
  }

  private async consumeStream(res: Response, handlers: StreamHandlers) {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      let eventType = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
          continue;
        }
        if (!line.startsWith("data: ")) {
          continue;
        }

        try {
          const data = JSON.parse(line.slice(6));
          if (eventType === "context") {
            handlers.onContext?.(data as StreamContext);
          } else if (eventType === "text") {
            handlers.onDelta(data.delta || "");
          } else if (eventType === "tool_call") {
            handlers.onToolCallStart?.(
              data.id || "",
              data.name || "",
              data.args || {},
              data.risk || "risky"
            );
          } else if (eventType === "tool_result") {
            if (data.status === "error" || data.error) {
              handlers.onToolError?.(
                data.id || "",
                data.name || "",
                data.error || "Tool error"
              );
            } else {
              handlers.onToolResult?.(
                data.id || "",
                data.name || "",
                data.result || "",
                Array.isArray(data.artifacts) ? data.artifacts : []
              );
            }
          } else if (eventType === "confirmation_required") {
            handlers.onConfirmationRequired?.({
              tool_call_id: data.tool_call_id || "",
              tool_name: data.tool_name || "",
              args: data.args || {},
              risk: data.risk || "destructive",
              timeout_s: data.timeout_s || 30,
              worker_policy_context: data.worker_policy_context || null,
            });
          } else if (eventType === "capability_candidate") {
            handlers.onCapabilityCandidate?.(data as CapabilityCandidateHint);
          } else if (eventType === "worker_notice") {
            handlers.onWorkerNotice?.(data as WorkerNotice);
          } else if (eventType.startsWith("acquisition_")) {
            handlers.onAcquisitionNotice?.({
              type: eventType,
              ...(data as Record<string, unknown>),
            });
          } else if (eventType === "error") {
            handlers.onError(data.error?.message || "Stream error");
          } else if (eventType === "done") {
            handlers.onDone();
          }
        } catch {
          // ignore parse errors
        }

        eventType = "";
      }
    }
  }
}

export const api = new ApiClient();
export type {
  StreamArtifact,
  StreamConfirmation,
  ConfirmToolRequest,
  StreamHandlers,
  StreamContext,
  ChatStreamOptions,
  ToolOption,
  UploadedArtifact,
  MessageAttachment,
  Page,
  CapabilityCandidate,
  CapabilityCandidateHint,
  CandidateStatus,
  CandidateType,
  Worker,
  WorkerVersion,
  WorkerRun,
  WorkerNotice,
  AcquisitionNotice,
};
