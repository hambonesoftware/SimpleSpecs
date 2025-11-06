const textarea = document.getElementById('spec-text');
const runButton = document.getElementById('run-search');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const telemetryBody = document.getElementById('telemetry-body');
const warningsEl = document.getElementById('warnings');

const levelColors = {
  MUST: '#dc2626',
  SHOULD: '#d97706',
  MAY: '#059669',
};

function currentBuckets() {
  return Array.from(document.querySelectorAll('.bucket-list input[type="checkbox"]:checked')).map(
    (input) => input.value,
  );
}

function normalizeBuckets(data) {
  if (!data) return {};
  if (data.buckets) return data.buckets;
  if (data.root) return data.root;
  return data;
}

function renderBuckets(data) {
  const buckets = normalizeBuckets(data);
  resultsEl.innerHTML = '';
  Object.entries(buckets).forEach(([bucket, payload]) => {
    const card = document.createElement('article');
    card.className = 'bucket-card';
    const title = document.createElement('h3');
    title.textContent = bucket.charAt(0).toUpperCase() + bucket.slice(1);
    const count = document.createElement('span');
    count.textContent = `${payload.requirements.length} reqs`;
    title.appendChild(count);
    card.appendChild(title);

    if (!payload.requirements.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = 'No requirements extracted for this bucket.';
      card.appendChild(empty);
    } else {
      const list = document.createElement('ul');
      list.className = 'requirements-list';
      payload.requirements.forEach((req) => {
        const item = document.createElement('li');
        item.className = 'requirement';

        const header = document.createElement('div');
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.style.background = levelColors[req.level] || '#e0e7ff';
        badge.textContent = req.level;
        header.appendChild(badge);

        if (req.id) {
          const id = document.createElement('span');
          id.textContent = req.id;
          id.className = 'req-id';
          header.appendChild(id);
        }

        if (req.page_hint !== null && req.page_hint !== undefined) {
          const page = document.createElement('span');
          page.textContent = `page ${req.page_hint}`;
          page.className = 'page-hint';
          header.appendChild(page);
        }

        item.appendChild(header);

        const body = document.createElement('pre');
        body.textContent = req.text;
        item.appendChild(body);
        list.appendChild(item);
      });
      card.appendChild(list);
    }

    resultsEl.appendChild(card);
  });
}

function renderTelemetry(meta) {
  telemetryBody.innerHTML = '';
  warningsEl.textContent = '';
  if (!meta) return;
  meta.attempts.forEach((attempt) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${attempt.rung}</td>
      <td>${attempt.model}</td>
      <td>${attempt.parsed ? 'yes' : 'no'}</td>
      <td>${attempt.reason}</td>
      <td>${attempt.input_tokens_est}</td>
      <td>${attempt.response_bytes}</td>
    `;
    telemetryBody.appendChild(row);
  });
  if (meta.warnings && meta.warnings.length) {
    warningsEl.textContent = meta.warnings.join(' \u2022 ');
  }
}

async function runSearch() {
  const text = textarea.value.trim();
  if (!text) {
    statusEl.textContent = 'Paste specification text to run the search.';
    return;
  }
  const buckets = currentBuckets();
  if (!buckets.length) {
    statusEl.textContent = 'Select at least one bucket.';
    return;
  }

  const payload = {
    document_id: document.getElementById('document-id').value || null,
    text,
    buckets,
  };

  statusEl.textContent = 'Running…';
  runButton.disabled = true;

  try {
    const response = await fetch('/api/spec-search', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    renderTelemetry(result.meta);
    if (result.ok) {
      renderBuckets(result.data);
      statusEl.textContent = 'Extraction complete.';
    } else {
      resultsEl.innerHTML = '';
      statusEl.textContent = result.error || 'Extraction failed.';
    }
  } catch (error) {
    console.error(error);
    statusEl.textContent = 'Network error when calling /api/spec-search.';
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener('click', runSearch);
