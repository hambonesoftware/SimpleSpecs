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
    let detail;
    if (contentType.includes("application/json")) {
      const data = await response.json().catch(() => null);
      if (data && Object.prototype.hasOwnProperty.call(data, "detail")) {
        detail = data.detail;
        if (Array.isArray(detail)) {
          message = detail.map((item) => item.msg || item).join(", ");
        } else if (typeof detail === "string") {
          message = detail;
        } else if (detail && typeof detail === "object") {
          message = detail.message || message;
        }
      }
    } else {
      const text = await response.text().catch(() => "");
      if (text) message = text;
    }
    const error = new Error(message);
    if (detail !== undefined) {
      error.detail = detail;
    }
    error.status = response.status;
    throw error;
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

function buildPayload({ uploadId, provider, model, params, apiKey, baseUrl }, options = {}) {
  const includeProvider = options.includeProvider !== false;
  const normalizedProvider = provider || "openrouter";
  const sanitizedApiKey = typeof apiKey === "string" ? apiKey.trim() : "";
  const sanitizedBaseUrl = typeof baseUrl === "string" ? baseUrl.trim() : "";
  const payload = {
    upload_id: uploadId,
    model,
    params: params || {},
  };
  if (includeProvider) {
    payload.provider = normalizedProvider;
  }
  if (normalizedProvider === "openrouter") {
    if (sanitizedApiKey) {
      payload.api_key = sanitizedApiKey;
    }
  }
  if (normalizedProvider === "llamacpp" && sanitizedBaseUrl) {
    payload.base_url = sanitizedBaseUrl;
  }
  return payload;
}

export async function requestHeaders(config) {
  const endpoint =
    (config.provider || "openrouter") === "llamacpp"
      ? "/api/ollama/headers"
      : "/api/openrouter/headers";
  return request(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(buildPayload(config, { includeProvider: false })),
  });
}

export async function requestSpecs(config) {
  return request("/api/specs", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(buildPayload(config)),
  });
}

export async function* streamSpecs(config, { signal } = {}) {
  const endpoint = "/api/specs/stream";
  const resolvedUrl = resolveUrl(endpoint);
  const response = await fetch(resolvedUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...JSON_HEADERS },
    body: JSON.stringify(buildPayload(config)),
    signal,
  });

  if (!response.ok) {
    await handleResponse(response);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) {
        yield JSON.parse(line);
      }
      newlineIndex = buffer.indexOf("\n");
    }
  }

  const remaining = buffer + decoder.decode();
  const finalLine = remaining.trim();
  if (finalLine) {
    yield JSON.parse(finalLine);
  }
}

export async function exportSpecs(uploadId) {
  const response = await request(`/api/export/specs.csv?upload_id=${encodeURIComponent(uploadId)}`);
  const blob = await response.blob();
  return blob;
}
