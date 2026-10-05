const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  } catch {
    // The request never got an answer (server restarting, network cut): say so,
    // instead of a generic "failed" that hides the cause.
    throw new ApiError(0, "Le serveur ne répond pas pour le moment : réessayez dans un instant.");
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      // body wasn't JSON — keep the status text
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return undefined as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };
}

export const api = {
  get: <T>(path: string): Promise<T> => request<T>(path),
  post: <T>(path: string, body?: unknown): Promise<T> => request<T>(path, jsonInit("POST", body)),
  put: <T>(path: string, body?: unknown): Promise<T> => request<T>(path, jsonInit("PUT", body)),
  patch: <T>(path: string, body?: unknown): Promise<T> => request<T>(path, jsonInit("PATCH", body)),
  del: <T>(path: string): Promise<T> => request<T>(path, { method: "DELETE" }),
  postForm: <T>(path: string, form: FormData): Promise<T> =>
    request<T>(path, { method: "POST", body: form }),
};
