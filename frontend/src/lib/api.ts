class ApiClient {
  private token: string | null = null;

  setToken(t: string) {
    this.token = t;
    localStorage.setItem("token", t);
  }

  getToken() {
    return this.token || localStorage.getItem("token");
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem("token");
  }

  async fetch(path: string, opts: RequestInit = {}) {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = this.getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}${path}`,
      { ...opts, headers }
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error?.message || `HTTP ${res.status}`);
    }
    return res;
  }

  async post(path: string, body: unknown) {
    return this.fetch(path, { method: "POST", body: JSON.stringify(body) });
  }

  async get(path: string) {
    return this.fetch(path);
  }

  async streamChat(
    convId: string,
    content: string,
    onDelta: (d: string) => void,
    onError: (e: string) => void,
    onDone: () => void
  ) {
    const res = await this.fetch(
      `/api/v1/conversations/${convId}/chat`,
      { method: "POST", body: JSON.stringify({ content }) }
    );
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
        if (line.startsWith("data: ")) {
          try {
            const d = JSON.parse(line.slice(6));
            if (eventType === "text") onDelta(d.delta);
            if (eventType === "error")
              onError(d.error?.message || "Stream error");
            if (eventType === "done") onDone();
          } catch {
            // ignore parse errors
          }
          eventType = "";
        }
      }
    }
  }
}

export const api = new ApiClient();
