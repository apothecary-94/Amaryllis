export class AmaryllisOpenAICompatClient {
  constructor({ endpoint = "http://127.0.0.1:8000", token = "dev-token" } = {}) {
    const normalized = String(endpoint || "").trim().replace(/\/+$/, "");
    if (!normalized) {
      throw new Error("endpoint is required");
    }
    this.endpoint = normalized;
    this.token = String(token || "").trim();
  }

  async chatCompletions({ messages, model = null, stream = false, extra = null } = {}) {
    if (!Array.isArray(messages) || messages.length === 0) {
      throw new Error("messages must be a non-empty array");
    }
    const payload = {
      messages,
      stream: Boolean(stream)
    };
    if (typeof model === "string" && model.trim()) {
      payload.model = model.trim();
    }
    if (extra && typeof extra === "object") {
      Object.assign(payload, extra);
    }

    const headers = { "Content-Type": "application/json" };
    if (this.token) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const response = await fetch(`${this.endpoint}/v1/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`request failed status=${response.status} detail=${text}`);
    }
    const data = await response.json();
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      throw new Error("response must be a JSON object");
    }
    return data;
  }

  static assistantContent(payload) {
    return payload?.choices?.[0]?.message?.content ?? "";
  }
}
