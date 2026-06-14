interface StreamConfirmation {
  tool_call_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  risk: string;
  timeout_s: number;
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
};
