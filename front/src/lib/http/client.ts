export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

async function buildApiError(resp: Response): Promise<ApiError> {
  let message = `API error ${resp.status}`;
  try {
    const body = (await resp.json()) as { detail?: string; message?: string };
    if (body.detail) {
      message = body.detail;
    } else if (body.message) {
      message = body.message;
    }
  } catch {
    // Ignore non-JSON error payloads.
  }
  return new ApiError(resp.status, message);
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!resp.ok) {
    if (resp.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    throw await buildApiError(resp);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  const contentType = resp.headers?.get?.("content-type");
  if (!contentType || !contentType.includes("application/json")) {
    try {
      return (await resp.json()) as T;
    } catch {
      return undefined as T;
    }
  }
  return resp.json() as Promise<T>;
}
