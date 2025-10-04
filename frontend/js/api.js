const JSON_HEADERS = { Accept: "application/json" };

const BACKEND_ORIGIN = (() => {
  if (typeof window === "undefined") return "";
  if (window.__SIMPLESPECS_BACKEND_ORIGIN__) {
    return String(window.__SIMPLESPECS_BACKEND_ORIGIN__);
  }
  const { protocol, hostname, port } = window.location;
  if (!port || port === "8000") {
    return "";
  }
  return `${protocol}//${hostname}:8000`;
})();

function resolveUrl(pathOrUrl) {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    return pathOrUrl;
  }
  if (!BACKEND_ORIGIN) {
    return pathOrUrl;
  }
  return new URL(pathOrUrl, BACKEND_ORIGIN).toString();
}

async function handleResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    if (contentType.includes("application/json")) {
      const data = await response.json().catch(() => null);
      if (data?.detail) {
        message = Array.isArray(data.detail)
          ? data.detail.map((item) => item.msg || item).join(", ")
          : data.detail;
      }
    } else {
      const text = await response.text().catch(() => "");
      if (text) message = text;
    }
    throw new Error(message);
  }
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

async function request(url, options = {}) {
  const resolvedUrl = resolveUrl(url);
  const response = await fetch(resolvedUrl, options);
  return handleResponse(response);
}

export async function checkHealth() {
  return request("/healthz", { headers: JSON_HEADERS });
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request("/api/upload", {
    method: "POST",
    body: formData,
  });
}

export async function fetchObjects(uploadId, page = 1, pageSize = 500) {
  const params = new URLSearchParams({ upload_id: uploadId, page: String(page), page_size: String(pageSize) });
  return request(`/api/objects?${params.toString()}`, { headers: JSON_HEADERS });
}

export async function fetchModelSettings() {
  return request("/api/settings", { headers: JSON_HEADERS });
}

export async function updateModelSettings(payload) {
  return request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(payload),
  });
}

function buildPayload({ uploadId, provider, model, params, apiKey, baseUrl }) {
  const payload = {
    upload_id: uploadId,
    provider,
    model,
    params: params || {},
  };
  if (provider === "openrouter" && apiKey) {
    payload.api_key = apiKey;
  }
  if (provider === "llamacpp" && baseUrl) {
    payload.base_url = baseUrl;
  }
  return payload;
}

export async function requestHeaders(config) {
  return request("/api/headers", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(buildPayload(config)),
  });
}

export async function requestSpecs(config) {
  return request("/api/specs", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(buildPayload(config)),
  });
}

export async function exportSpecs(uploadId) {
  const response = await request(`/api/export/specs.csv?upload_id=${encodeURIComponent(uploadId)}`);
  const blob = await response.blob();
  return blob;
}
