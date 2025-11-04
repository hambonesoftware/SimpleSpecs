// Updated Specs Patch for re-running specs from scratch
// This script attaches to the "Rerun specs" button in the Specification buckets
// panel.  It wipes any previously cached/extracted specification buckets on the
// server and then re-invokes the LLM-driven extraction workflow.  When
// completed, it fires a `specs:buckets:updated` event so that the main app
// (app.js) can re-render the view.

;(function () {
  /**
   * Perform a fetch request against the API.  Prepends the API base URL from
   * the page meta tag or window.API_BASE if set.  JSON bodies are stringified
   * and appropriate headers are applied.
   *
   * @param {string} url The API path (e.g. `/api/specs/1/buckets`)
   * @param {Object} opts Options passed to fetch (method, headers, body)
   * @returns {Promise<any>} Parsed JSON result
   */
  async function apiRequest(url, opts = {}) {
    const base = (window.API_BASE) ||
      (document.querySelector('meta[name="api-base"]')?.getAttribute('content')) || '';
    const res = await fetch(base + url, {
      method: opts.method || 'GET',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const text = await res.text().catch(() => '');
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${text}`.trim());
    }
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  /**
   * Delete existing specification buckets and re-run extraction for the given document.
   * Disables the triggering button and updates its text while in progress.  When
   * finished, re-enables the button and dispatches a `specs:buckets:updated`
   * event containing the updated bucket payload.
   *
   * @param {number|string} docId The ID of the document whose specs to re-run
   */
  async function runAgainBuckets(docId) {
    const btn = document.getElementById('run-again-buckets')
      || document.getElementById('rerun-specs');
    if (!docId) {
      alert('No document selected.');
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.dataset.loading = 'true';
      btn.textContent = 'Re-running…';
      btn.setAttribute('aria-busy', 'true');
    }
    try {
      // First, wipe any stored bucket results for this document
      await apiRequest(`/api/specs/${docId}/buckets`, { method: 'DELETE' });
      // Next, re-run the extraction from scratch
      const json = await apiRequest(`/api/specs/${docId}/buckets/run-again`, { method: 'POST' });
      console.debug('[Specs] Buckets wipe + re-run result:', json);
      // Fire an event so the main app can re-render the buckets
      window.dispatchEvent(new CustomEvent('specs:buckets:updated', { detail: json }));
      alert('Buckets wiped and re-extracted.  Check the Specs panel for updates.');
    } catch (err) {
      console.error('[Specs] Specs rerun failed:', err);
      alert('Rerunning specs failed: ' + (err && err.message || err));
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.dataset.loading = '';
        btn.removeAttribute('aria-busy');
        btn.textContent = 'Rerun specs';
      }
    }
  }

  // Expose the function globally so app.js or other scripts can call it
  window.SpecsPatch = { runAgainBuckets };

  // Auto-wire the button on DOMContentLoaded.  If the button has a data-doc-id
  // attribute at page load, this will run once; otherwise app.js may call
  // SpecsPatch.runAgainBuckets(docId) directly.
  window.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('run-again-buckets')
      || document.getElementById('rerun-specs');
    const docIdAttr = btn?.dataset?.docId;
    if (btn && docIdAttr) {
      btn.addEventListener('click', (event) => {
        event.preventDefault();
        const id = Number(docIdAttr);
        if (Number.isFinite(id)) {
          runAgainBuckets(id);
        } else {
          alert('Invalid document id');
        }
      });
    }
  });
})();