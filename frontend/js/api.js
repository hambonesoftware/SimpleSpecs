const API_BASE = "";

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
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
    xhr.open("POST", `${API_BASE}/api/upload`);
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

export async function fetchSectionText(documentId, start, end) {
  const params = new URLSearchParams({ start: String(start), end: String(end) });
  const response = await fetch(`${API_BASE}/api/headers/${documentId}/section-text?${params}`);
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
    `${API_BASE}/api/specs/${documentId}/export?fmt=${encodeURIComponent(format)}`
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
