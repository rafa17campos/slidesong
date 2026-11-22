// Thin fetch wrapper: JSON in/out, FastAPI's {"detail": ...} turned into an ApiError the UI can show. Every call
// says the interface language (Accept-Language), so the server answers its messages in it.
import i18n, { lang } from "@/i18n";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const FIELDS = ["title", "title_overlay", "theme", "lyrics", "date_from", "date_to", "people"] as const;

/** FastAPI's validation error (technical) as a sentence naming the field. */
function validation(d: { loc?: unknown[]; type?: string; ctx?: { max_length?: number } }): string {
  const key = String(d.loc?.at(-1) ?? "");
  const what = i18n.t(
    `common:fields.${(FIELDS as readonly string[]).includes(key) ? (key as (typeof FIELDS)[number]) : "other"}`,
  );
  if (d.type === "string_too_long")
    return i18n.t("common:errors.tooLong", { what, max: d.ctx?.max_length ?? "?" });
  if (d.type === "too_long") return i18n.t("common:errors.tooMany", { what });
  if (d.type === "string_pattern_mismatch") return i18n.t("common:errors.badFormat", { what });
  return i18n.t("common:errors.invalid", { what });
}

async function detail(r: Response): Promise<string> {
  try {
    const body = await r.json();
    const d = body?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]) return validation(d[0]);
  } catch {
    /* not JSON */
  }
  return r.status >= 500
    ? i18n.t("common:errors.server")
    : i18n.t("common:errors.status", { status: r.status });
}

async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { "Accept-Language": lang() };
  const init: RequestInit = { method, cache: "no-store", signal, headers };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, i18n.t("common:errors.offline"));
  }
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  const type = r.headers.get("content-type") ?? "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  get: <T>(url: string, signal?: AbortSignal) => request<T>("GET", url, undefined, signal),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  patch: <T>(url: string, body: unknown) => request<T>("PATCH", url, body),
  put: <T>(url: string, body: unknown) => request<T>("PUT", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

export const assetUrl = (id: string, kind: "thumbnail" | "preview" | "video" = "thumbnail") =>
  `/api/assets/${id}/${kind}`;
