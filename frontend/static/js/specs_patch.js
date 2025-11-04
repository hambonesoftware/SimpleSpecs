
// Lightweight helper you can load after app.js to wire a "Run again" button.
// Usage: add a button with id="run-again-buckets" and data-doc-id="123".

(function () {
  async function apiRequest(url, opts = {}) {
    const base = (window.API_BASE) || (document.querySelector('meta[name="api-base"]')?.getAttribute('content')) || '';
    const res = await fetch(base + url, {
      method: opts.method || 'GET',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return res.json();
  }

  async function runAgainBuckets(docId) {
    const btn = document.getElementById('run-again-buckets');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Running...';
    }
    try {
      const json = await apiRequest(`/api/specs/${docId}/buckets/run-again`, { method: 'POST' });
      console.log('[Specs] Buckets re-run result:', json);
      // Fire a custom event so your app.js can refresh any views
      window.dispatchEvent(new CustomEvent('specs:buckets:updated', { detail: json }));
      alert('Buckets updated. Check the console or your Specs pane.');
    } catch (err) {
      console.error('[Specs] run again failed:', err);
      alert('Run again failed: ' + err.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Run again';
      }
    }
  }

  window.SpecsPatch = { runAgainBuckets };

  // Auto-wire if a button with id exists
  window.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('run-again-buckets');
    if (btn && btn.dataset.docId) {
      btn.addEventListener('click', () => runAgainBuckets(btn.dataset.docId));
    }
  });
})();
