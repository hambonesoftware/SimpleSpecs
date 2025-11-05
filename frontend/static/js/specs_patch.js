// Updated Specs Patch for re-running specs from scratch
// This module attaches to the "Rerun specs" button in the Specification buckets
// panel. It wipes any previously cached/extracted specification buckets on the
// server and then re-invokes the LLM-driven extraction workflow. When
// completed, it fires a `specs:buckets:updated` event so that the main app
// (app.js) can re-render the view.

import { deleteSpecsBuckets, runSpecsBucketsAgain } from './api.js';

function findRerunButton() {
  return document.getElementById('run-again-buckets')
    || document.getElementById('rerun-specs');
}

function coerceDocumentId(docId) {
  if (docId == null || docId === '') {
    return null;
  }

  const numeric = Number(docId);
  if (Number.isFinite(numeric) && numeric > 0) {
    return numeric;
  }

  return null;
}

/**
 * Delete existing specification buckets and re-run extraction for the given document.
 * Disables the triggering button and updates its text while in progress. When
 * finished, re-enables the button and dispatches a `specs:buckets:updated`
 * event containing the updated bucket payload.
 *
 * @param {number|string} docId The ID of the document whose specs to re-run
 */
export async function runAgainBuckets(docId) {
  const button = findRerunButton();
  const normalisedId = coerceDocumentId(docId);

  if (!normalisedId) {
    alert('No document selected.');
    return;
  }

  if (button) {
    button.disabled = true;
    button.dataset.loading = 'true';
    button.textContent = 'Re-running…';
    button.setAttribute('aria-busy', 'true');
  }

  try {
    await deleteSpecsBuckets(normalisedId);
    const json = await runSpecsBucketsAgain(normalisedId);
    console.debug('[Specs] Buckets wipe + re-run result:', json);
    window.dispatchEvent(new CustomEvent('specs:buckets:updated', { detail: json }));
    alert('Buckets wiped and re-extracted. Check the Specs panel for updates.');
  } catch (err) {
    console.error('[Specs] Specs rerun failed:', err);
    const message = err && err.message ? err.message : String(err);
    alert('Rerunning specs failed: ' + message);
  } finally {
    if (button) {
      button.disabled = false;
      button.dataset.loading = '';
      button.removeAttribute('aria-busy');
      button.textContent = 'Rerun specs';
    }
  }
}

if (typeof window !== 'undefined') {
  window.SpecsPatch = { ...(window.SpecsPatch ?? {}), runAgainBuckets };

  window.addEventListener('DOMContentLoaded', () => {
    const button = findRerunButton();
    if (button) {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        const currentId = coerceDocumentId(button.dataset?.docId ?? null);
        if (!currentId) {
          alert('Invalid document id');
          return;
        }
        void runAgainBuckets(currentId);
      });
    }
  });
}