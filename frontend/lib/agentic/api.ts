export class AgenticApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Calls the Agentic QA FastAPI service through the Next.js proxy at /api/agentic. */
export async function agenticApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/agentic${path}`, { ...init, headers });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : text || `Request failed (${response.status})`;
    throw new AgenticApiError(response.status, detail);
  }
  return payload as T;
}
