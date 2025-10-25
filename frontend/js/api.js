const apiBase = document.querySelector('meta[name="api-base"]')?.content ?? '/api';

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { 'Accept': 'application/json', ...(options.headers ?? {}) },
    ...options,
  });

  if (!response.ok) {
    let detail;
    try {
      const payload = await response.json();
      detail = payload?.detail ?? payload?.message;
    } catch (error) {
      detail = undefined;
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
    return response.json();
  }
  return response.text();
}

export async function listDocuments() {
  return request('/files');
}

export function uploadDocument(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${apiBase}/upload`);
    xhr.responseType = 'json';

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === 'function') {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
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
  const response = await fetch(`${apiBase}/specs/${documentId}/export?fmt=${encodeURIComponent(format)}`);
  if (!response.ok) {
    let detail;
    try {
      const payload = await response.json();
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
