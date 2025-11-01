const SAME_ORIGIN_KEYS = new Set(["", "/", ".", "auto", "same-origin"]);

function normaliseBase(value) {
  if (typeof value !== "string") {
    return null;
  }

  const trimmed = value.trim();
  const lower = trimmed.toLowerCase();
  if (SAME_ORIGIN_KEYS.has(lower)) {
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
      return `${protocol}//${safeHost}${trimmed}`.replace(/\/+$/, "");
    }
    return trimmed.replace(/\/+$/, "");
  }

  if (trimmed.startsWith("//")) {
    return `${window.location.protocol}${trimmed}`.replace(/\/+$/, "");
  }

  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed.replace(/\/+$/, "");
  }

  if (trimmed.startsWith("/")) {
    return `${window.location.origin}${trimmed}`.replace(/\/+$/, "");
  }

  return trimmed.replace(/\/+$/, "");
}

function resolveApiBase() {
  if (typeof window === "undefined") {
    return "";
  }

  const candidates = [
    typeof window.API_BASE === "string" ? window.API_BASE : null,
    document?.querySelector?.('meta[name="api-base"]')?.getAttribute("content") ?? null,
  ];

  for (const candidate of candidates) {
    const normalised = normaliseBase(candidate);
    if (typeof normalised === "string") {
      return normalised;
    }
  }

  return "";
}

export const API_BASE = resolveApiBase();

function buildUrl(path) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const normalisedPath = path.startsWith("/") ? path : `/${path}`;

  if (!API_BASE) {
    return normalisedPath;
  }

  const base = API_BASE.replace(/\/+$/, "");

  if (/^https?:\/\//i.test(base)) {
    if (normalisedPath.startsWith("/api/") && base.endsWith("/api")) {
      return `${base}${normalisedPath.slice(4)}`;
    }
    return `${base}${normalisedPath}`;
  }

  return `${base}${normalisedPath}`;
}

async function request(path, options = {}) {
  const url = buildUrl(path);
  const config = {
    headers: { Accept: "application/json", ...(options.headers ?? {}) },
    ...options,
  };

  const response = await fetch(url, config);
  const text = await response.text();

  if (!response.ok) {
    const snippet = text.slice(0, 500);
    throw new Error(`${response.status} ${response.statusText}: ${snippet}`.trim());
  }

  if (response.status === 204 || text.length === 0) {
    return null;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(text);
    } catch (error) {
      console.warn("[API] Failed to parse JSON response", { url, text, error });
      return text;
    }
  }

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

export async function fetchHeaders(documentId) {
  return request(`/api/headers/${documentId}`, { method: "POST" });
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

export async function compareSpecifications(documentId) {
  return request(`/api/specs/compare/${documentId}`, { method: "POST" });
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
