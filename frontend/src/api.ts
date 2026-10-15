export type Session = {
  token: string;
  userId: string;
  organizationId: string;
  role: string;
  email: string;
};

export type DocumentRow = {
  documentId: string;
  title: string;
  status: string;
  currentVersionId: string | null;
  audienceLabels: string[];
  restrictedLabels: string[];
  mimeType?: string;
};

export type VersionRow = {
  id: string;
  versionNumber: number;
  createdAt: string | null;
  sourceVersionId: string | null;
};

function readErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object" || !("detail" in body)) return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item && typeof (item as { msg?: unknown }).msg === "string") {
          return (item as { msg: string }).msg;
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length > 0) return messages.join(" ");
  }
  return fallback;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, session: Session | null, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (session?.token) headers.set("Authorization", `Bearer ${session.token}`);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = readErrorDetail(await response.json(), response.statusText);
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function tokenExpiry(token: string): number {
  const segment = token.split(".")[1] ?? "";
  const padded = segment.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (segment.length % 4)) % 4);
  const payload = JSON.parse(atob(padded)) as { exp?: number };
  return (payload.exp ?? 0) * 1000;
}

const viewKey = (documentId: string) => `databox:view:${documentId}`;

export function readViewToken(documentId: string): string | null {
  const token = sessionStorage.getItem(viewKey(documentId));
  if (!token) return null;
  if (tokenExpiry(token) <= Date.now() + 15_000) {
    sessionStorage.removeItem(viewKey(documentId));
    return null;
  }
  return token;
}

export function writeViewToken(documentId: string, token: string): void {
  sessionStorage.setItem(viewKey(documentId), token);
}

export function clearViewTokens(): void {
  const keys: string[] = [];
  for (let index = 0; index < sessionStorage.length; index += 1) {
    const key = sessionStorage.key(index);
    if (key?.startsWith("databox:view:")) keys.push(key);
  }
  for (const key of keys) sessionStorage.removeItem(key);
}

export async function issueViewToken(session: Session, documentId: string, force = false): Promise<string> {
  if (!force) {
    const cached = readViewToken(documentId);
    if (cached) return cached;
  }
  const data = await api<{ token: string }>(`/api/v1/documents/${documentId}/view-token`, session, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  writeViewToken(documentId, data.token);
  return data.token;
}
