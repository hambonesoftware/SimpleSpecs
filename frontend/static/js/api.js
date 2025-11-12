const SAME_ORIGIN_KEYS = new Set(["", "/", ".", "auto", "same-origin"]);

function apiDebug(message, payload) {
  if (payload !== undefined) {
    console.debug(`[API] ${message}`, payload);
  } else {
    console.debug(`[API] ${message}`);
  }
}

function normaliseBase(value) {
  apiDebug('normaliseBase invoked', { value });
  if (typeof value !== "string") {
    apiDebug('normaliseBase returning null (non-string input)', { value });
    return null;
  }

  const trimmed = value.trim();
  const lower = trimmed.toLowerCase();
  if (SAME_ORIGIN_KEYS.has(lower)) {
    apiDebug('normaliseBase resolved same-origin', { trimmed });
    return "";
  }

  if (trimmed.startsWith(":")) {
    // Allow port-only overrides (e.g. ":7600") by inferring the current host.
    if (typeof window !== "undefined") {
      const { protocol } = window.location;
      let host = window.location.hostname;
      if (!host) {
        const locationHost = window.location.host;
        if (locationHost.startsWith("[")) {
          const endIndex = locationHost.indexOf("]");
          host = endIndex >= 0 ? locationHost.slice(0, endIndex + 1) : locationHost;
        } else {
          host = locationHost.split(":")[0];
        }
      }

      if (!host) {
        host = "localhost";
      }

      const needsBrackets = host.includes(":") && !(host.startsWith("[") && host.endsWith("]"));
      const safeHost = needsBrackets ? `[${host}]` : host;
      const computed = `${protocol}//${safeHost}${trimmed}`.replace(/\/+$/, "");
      apiDebug('normaliseBase port-only override with window', { computed, host: safeHost });
      return computed;
    }
    const fallback = trimmed.replace(/\/+$/, "");
    apiDebug('normaliseBase port-only override without window', { fallback });
    return fallback;
  }

  if (trimmed.startsWith("//")) {
    const computed = `${window.location.protocol}${trimmed}`.replace(/\/+$/, "");
    apiDebug('normaliseBase protocol-relative URL', { computed });
    return computed;
  }

  if (/^https?:\/\//i.test(trimmed)) {
    const cleaned = trimmed.replace(/\/+$/, "");
    apiDebug('normaliseBase absolute URL', { cleaned });
    return cleaned;
  }

  if (trimmed.startsWith("/")) {
    const combined = `${window.location.origin}${trimmed}`.replace(/\/+$/, "");
    apiDebug('normaliseBase origin-relative URL', { combined });
    return combined;
  }

  const cleaned = trimmed.replace(/\/+$/, "");
  apiDebug('normaliseBase fallback URL', { cleaned });
  return cleaned;
}

function resolveApiBase() {
  apiDebug('resolveApiBase invoked');
  if (typeof window === "undefined") {
    apiDebug('resolveApiBase returning empty (no window)');
    return "";
  }

  const candidates = [
    typeof window.API_BASE === "string" ? window.API_BASE : null,
    document?.querySelector?.('meta[name="api-base"]')?.getAttribute("content") ?? null,
  ];

  for (const candidate of candidates) {
    const normalised = normaliseBase(candidate);
    if (typeof normalised === "string") {
      apiDebug('resolveApiBase selected candidate', { candidate, normalised });
      return normalised;
    }
  }

  apiDebug('resolveApiBase using empty default');
  return "";
}

export const API_BASE = resolveApiBase();

function buildUrl(path) {
  apiDebug('buildUrl invoked', { path, API_BASE });
  if (/^https?:\/\//i.test(path)) {
    apiDebug('buildUrl returning absolute path', { path });
    return path;
  }

  const normalisedPath = path.startsWith("/") ? path : `/${path}`;
  apiDebug('buildUrl normalised path', { normalisedPath });

  if (!API_BASE) {
    apiDebug('buildUrl using normalised path without base', { normalisedPath });
    return normalisedPath;
  }

  const base = API_BASE.replace(/\/+$/, "");
  apiDebug('buildUrl computed base', { base });

  if (/^https?:\/\//i.test(base)) {
    if (normalisedPath.startsWith("/api/") && base.endsWith("/api")) {
      const combined = `${base}${normalisedPath.slice(4)}`;
      apiDebug('buildUrl combining with base ending in /api', { combined });
      return combined;
    }
    const combined = `${base}${normalisedPath}`;
    apiDebug('buildUrl combining with absolute base', { combined });
    return combined;
  }

  const combined = `${base}${normalisedPath}`;
  apiDebug('buildUrl combining with relative base', { combined });
  return combined;
}

function serialiseQuery(params = {}) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    // Treat booleans as 1/0 to make server-side parsing trivial
    if (typeof v === "boolean") {
      sp.set(k, v ? "1" : "0");
    } else {
      sp.set(k, String(v));
    }
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function request(path, options = {}) {
  const url = buildUrl(path);
  const config = {
    headers: { Accept: "application/json", ...(options.headers ?? {}) },
    ...options,
  };

  apiDebug('request starting', { path, url, config });
  const response = await fetch(url, config);
  apiDebug('request response received', {
    url,
    status: response.status,
    statusText: response.statusText,
  });
  const text = await response.text();
  apiDebug('request response text snippet', { url, snippet: text.slice(0, 200) });

  if (!response.ok) {
    const snippet = text.slice(0, 500);
    apiDebug('request throwing due to non-ok response', {
      url,
      status: response.status,
      statusText: response.statusText,
      snippet,
    });
    throw new Error(`${response.status} ${response.statusText}: ${snippet}`.trim());
  }

  if (response.status === 204 || text.length === 0) {
    apiDebug('request returning null payload', { url, status: response.status });
    return null;
  }

  const contentType = response.headers.get("content-type") ?? "";
  apiDebug('request evaluating content type', { url, contentType });
  if (contentType.includes("application/json")) {
    try {
      const parsed = JSON.parse(text);
      apiDebug('request returning parsed JSON', { url, keys: Object.keys(parsed ?? {}) });
      return parsed;
    } catch (error) {
      console.warn("[API] Failed to parse JSON response", { url, text, error });
      return text;
    }
  }

  apiDebug('request returning raw text', { url, length: text.length });
  return text;
}

export async function listDocuments() {
  return request("/api/files");
}

export function uploadDocument(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", buildUrl("/api/upload"));
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === "function") {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(xhr.response);
      } else {
        const text = typeof xhr.response === "string" ? xhr.response : JSON.stringify(xhr.response ?? {});
        reject(new Error(`${xhr.status} ${xhr.statusText}: ${text.slice(0, 500)}`));
      }
    };

    xhr.onerror = () => {
      reject(new Error("Network error during upload"));
    };

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

export async function parseDocument(documentId) {
  return request(`/api/parse/${documentId}`, { method: "POST" });
}

export async function fetchDocumentStatus(documentId) {
  return request(`/api/documents/${documentId}/status`);
}

/**
 * Fetch headers for a document.
 * Options:
 *   - force (boolean): if true, appends ?force=1 to bypass caches and fetch fresh LLM headers.
 *   - trace (boolean|number): if truthy, appends ?trace=1 to enable server-side tracing.
 *   - extra (object): additional query params to include (e.g., { align: "sequential" }).
 */
export async function fetchHeaders(documentId, opts = {}) {
  const params = new URLSearchParams();
  const bodyPayload = {};
  if (opts.force) bodyPayload.force = true;

  const hasAlign = Object.prototype.hasOwnProperty.call(opts, 'align');
  const alignValue = hasAlign ? opts.align : 'sequential';
  if (alignValue) params.set('align', String(alignValue));

  const hasTrace = Object.prototype.hasOwnProperty.call(opts, 'trace');
  const traceValue = hasTrace ? opts.trace : true;
  if (traceValue) params.set('trace', '1');

  const qs = params.toString();
  const path = qs ? `/api/headers/${documentId}?${qs}` : `/api/headers/${documentId}`;
  const init = { method: "POST" };
  if (Object.keys(bodyPayload).length) {
    init.body = JSON.stringify(bodyPayload);
    init.headers = { 'Content-Type': 'application/json' };
  }
  return request(path, init);
}

export async function fetchSectionText(documentId, start, end, sectionKey) {
  const params = new URLSearchParams({ start: String(start), end: String(end) });
  if (sectionKey) {
    params.set("section_key", String(sectionKey));
  }
  const response = await fetch(
    buildUrl(`/api/headers/${documentId}/section-text?${params}`)
  );
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 500)}`.trim());
  }

  return text;
}

export async function fetchSpecifications(documentId) {
  return request(`/api/specs/extract/${documentId}`, { method: "POST" });
}

export async function dispatchSpecAgents(documentId) {
  return request(`/api/specs/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documentId: String(documentId) }),
  });
}

export async function fetchSpecAgentSections(documentId) {
  return request(`/api/specs?documentId=${encodeURIComponent(documentId)}`);
}

export async function fetchSpecAgentSection(sectionId) {
  return request(`/api/specs/${encodeURIComponent(sectionId)}`);
}

export async function fetchSpecAgentStatus(documentId) {
  return request(`/api/specs/status?documentId=${encodeURIComponent(documentId)}`);
}

export async function compareSpecifications(documentId) {
  return request(`/api/specs/compare/${documentId}`, { method: "POST" });
}

export async function fetchCachedHeaders(documentId) {
  return request(`/api/headers/${documentId}`);
}
// Wipe all stored/spec-cached buckets for a document on the server
export async function deleteSpecsBuckets(documentId) {
  apiDebug('deleteSpecsBuckets invoked', { documentId });
  if (!Number.isFinite(Number(documentId))) {
    apiDebug('deleteSpecsBuckets invalid document id', { documentId });
    throw new Error('deleteSpecsBuckets: invalid documentId');
  }
  const result = await request(`/api/specs/${documentId}/buckets`, { method: 'DELETE' });
  apiDebug('deleteSpecsBuckets completed', { documentId, result });
  return result;
}

// Re-run extraction fresh (bypass caches) and return new buckets payload
export async function runSpecsBucketsAgain(documentId) {
  apiDebug('runSpecsBucketsAgain invoked', { documentId });
  if (!Number.isFinite(Number(documentId))) {
    apiDebug('runSpecsBucketsAgain invalid document id', { documentId });
    throw new Error('runSpecsBucketsAgain: invalid documentId');
  }
  // This endpoint should trigger a full re-extract on the server
  const result = await request(`/api/specs/${documentId}/buckets/run-again`, { method: 'POST' });
  apiDebug('runSpecsBucketsAgain completed', {
    documentId,
    resultType: result == null ? 'null' : typeof result,
    resultKeys: result && typeof result === 'object' ? Object.keys(result) : null,
  });
  return result;
}


export async function deleteDocument(documentId) {
  return request(`/api/files/${documentId}`, { method: "DELETE" });
}

export async function fetchSpecRecord(documentId) {
  return request(`/api/specs/${documentId}`);
}

export async function approveSpecRecord(documentId, body) {
  return request(`/api/specs/${documentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function downloadSpecExport(documentId, format) {
  const response = await fetch(
    buildUrl(`/api/specs/${documentId}/export?fmt=${encodeURIComponent(format)}`)
  );
  const clone = response.clone();
  const text = await clone.text();

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 500)}`.trim());
  }

  const blob = await response.blob();

  const disposition = response.headers.get("content-disposition") ?? "";
  let filename = `spec-${documentId}.${format === "csv" ? "zip" : "docx"}`;
  const match = disposition.match(/filename="?([^";]+)"?/i);
  if (match?.[1]) {
    filename = decodeURIComponent(match[1]);
  }

  return {
    blob,
    filename,
    mediaType: response.headers.get("content-type") ?? "application/octet-stream",
  };
}

/* --------------------------
 *  NEW: Buckets rerun API
 * -------------------------- */


export function toCsv(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return "";
  }
  const escape = (value) => {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes('"') || /[\n\r]/.test(text)) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  };
  const headers = Object.keys(rows[0]);
  const lines = [headers.map(escape).join(",")];
  for (const row of rows) {
    lines.push(headers.map((key) => escape(row[key])).join(","));
  }
  return lines.join("\n");
}

export function downloadBlob(filename, contents, type = "application/json") {
  const blob = contents instanceof Blob ? contents : new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
