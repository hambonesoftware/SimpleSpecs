const apiBase = (() => {
  const configured = document.querySelector('meta[name="api-base"]')?.content?.trim();
  const normalised = configured && configured.length > 0 ? configured : '/api';

  if (/^https?:\/\//i.test(normalised)) {
    return normalised;
  }

  if (normalised.startsWith('/')) {
    const url = new URL(window.location.href);
    if (url.port === '3600' && normalised === '/api') {
      url.port = '7600';
    }
    return `${url.origin}${normalised}`;
  }

  return normalised;
})();

async function request(path, options = {}) {
  const url = `${apiBase}${path}`;
  const config = {
    headers: { 'Accept': 'application/json', ...(options.headers ?? {}) },
    ...options,
  };

  const requestLog = {
    url,
    method: config.method ?? 'GET',
    headers: config.headers,
  };
  if (config.body && typeof config.body === 'string') {
    requestLog.body = config.body;
  }
  console.debug('[API] Request', requestLog);

  const response = await fetch(url, config);
  const raw = await response.clone().text();

  console.debug('[API] Response', {
    url,
    status: response.status,
    ok: response.ok,
    raw,
  });

  if (!response.ok) {
    let detail;
    if (raw) {
      try {
        const payload = JSON.parse(raw);
        detail = payload?.detail ?? payload?.message;
      } catch (error) {
        detail = undefined;
      }
    }
    const message = detail || `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (error) {
      console.warn('[API] Failed to parse JSON response', { url, raw, error });
      return JSON.parse(await response.text());
    }
  }
  return raw;
}

export async function listDocuments() {
  return request('/files');
}

export function uploadDocument(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBase}/upload`);
    xhr.responseType = 'json';

    console.debug('[API] Request', {
      url: `${apiBase}/upload`,
      method: 'POST',
      body: file?.name,
    });

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === 'function') {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      console.debug('[API] Response', {
        url: `${apiBase}/upload`,
        status: xhr.status,
        ok: xhr.status >= 200 && xhr.status < 300,
        raw: typeof xhr.response === 'string' ? xhr.response : JSON.stringify(xhr.response),
      });
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(xhr.response);
      } else {
        const detail = xhr.response?.detail || `Upload failed (${xhr.status})`;
        reject(new Error(detail));
      }
    };

    xhr.onerror = () => {
      reject(new Error('Network error during upload'));
    };

    const formData = new FormData();
    formData.append('file', file);
    xhr.send(formData);
  });
}

export async function parseDocument(documentId) {
  return request(`/parse/${documentId}`, { method: 'POST' });
}

export async function fetchHeaders(documentId) {
  return request(`/headers/${documentId}`, { method: 'POST' });
}

export async function fetchSectionText(documentId, start, end) {
  const params = new URLSearchParams({ start: String(start), end: String(end) });
  const url = `${apiBase}/headers/${documentId}/section-text?${params}`;
  console.debug('[API] Request', { url, method: 'GET' });
  const response = await fetch(url);
  const raw = await response.clone().text();
  console.debug('[API] Response', {
    url,
    status: response.status,
    ok: response.ok,
    raw,
  });
  if (!response.ok) {
    const message = `Section fetch failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return raw;
}

export async function fetchSpecifications(documentId) {
  return request(`/specs/extract/${documentId}`, { method: 'POST' });
}

export async function compareSpecifications(documentId) {
  return request(`/specs/compare/${documentId}`, { method: 'POST' });
}

export async function deleteDocument(documentId) {
  return request(`/files/${documentId}`, { method: 'DELETE' });
}

export async function fetchSpecRecord(documentId) {
  return request(`/specs/${documentId}`);
}

export async function approveSpecRecord(documentId, body) {
  return request(`/specs/${documentId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function downloadSpecExport(documentId, format) {
  const url = `${apiBase}/specs/${documentId}/export?fmt=${encodeURIComponent(format)}`;
  console.debug('[API] Request', { url, method: 'GET' });
  const response = await fetch(url);
  const raw = await response.clone().text();
  console.debug('[API] Response', {
    url,
    status: response.status,
    ok: response.ok,
    raw,
  });
  if (!response.ok) {
    let detail;
    try {
      const payload = JSON.parse(raw);
      detail = payload?.detail ?? payload?.message;
    } catch (error) {
      detail = undefined;
    }
    const message = detail || `Export failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') ?? '';
  let filename = `spec-${documentId}.${format === 'csv' ? 'zip' : 'docx'}`;
  const match = disposition.match(/filename="?([^";]+)"?/i);
  if (match?.[1]) {
    filename = decodeURIComponent(match[1]);
  }
  return {
    blob,
    filename,
    mediaType: response.headers.get('content-type') ?? 'application/octet-stream',
  };
}

export function toCsv(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return '';
  }
  const escape = (value) => {
    const text = String(value ?? '');
    if (text.includes(',') || text.includes('\"') || /[\n\r]/.test(text)) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  };
  const headers = Object.keys(rows[0]);
  const lines = [headers.map(escape).join(',')];
  for (const row of rows) {
    lines.push(headers.map((key) => escape(row[key])).join(','));
  }
  return lines.join('\n');
}

export function downloadBlob(filename, contents, type = 'application/json') {
  const blob = contents instanceof Blob ? contents : new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
