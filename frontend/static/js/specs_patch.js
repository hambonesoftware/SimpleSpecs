// Updated Specs Patch for re-running specs from scratch
// This module attaches to the "Rerun specs" button in the Specification buckets
// panel. It wipes any previously cached/extracted specification buckets on the
// server and then re-invokes the LLM-driven extraction workflow. When
// completed, it fires a `specs:buckets:updated` event so that the main app
// (app.js) can re-render the view.

import { deleteSpecsBuckets, runSpecsBucketsAgain } from './api.js';

function debugLog(message, payload) {
  if (payload !== undefined) {
    console.debug(`[SpecsPatch] ${message}`, payload);
  } else {
    console.debug(`[SpecsPatch] ${message}`);
  }
}

function findRerunButton() {
  const button = document.getElementById('run-again-buckets')
    || document.getElementById('rerun-specs');
  debugLog('findRerunButton invoked', {
    found: Boolean(button),
    id: button?.id ?? null,
  });
  return button;
}

function coerceDocumentId(docId) {
  debugLog('coerceDocumentId invoked', { raw: docId });
  if (docId == null || docId === '') {
    debugLog('coerceDocumentId returning null (empty input)');
    return null;
  }

  const numeric = Number(docId);
  if (Number.isFinite(numeric) && numeric > 0) {
    debugLog('coerceDocumentId returning numeric value', { numeric });
    return numeric;
  }

  debugLog('coerceDocumentId returning null (non-numeric input)', { coerced: numeric });
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
  debugLog('runAgainBuckets invoked', { docId, typeofDocId: typeof docId });
  const button = findRerunButton();
  const normalisedId = coerceDocumentId(docId);
  debugLog('runAgainBuckets normalised document id', { normalisedId });

  if (!normalisedId) {
    debugLog('runAgainBuckets aborting due to missing/invalid id');
    alert('No document selected.');
    return;
  }

  if (button) {
    debugLog('runAgainBuckets disabling rerun button', { buttonId: button.id });
    button.disabled = true;
    button.dataset.loading = 'true';
    button.textContent = 'Re-running…';
    button.setAttribute('aria-busy', 'true');
  }

  try {
    debugLog('runAgainBuckets initiating deleteSpecsBuckets call');
    await deleteSpecsBuckets(normalisedId);
    debugLog('runAgainBuckets deleteSpecsBuckets resolved');
    const json = await runSpecsBucketsAgain(normalisedId);
    debugLog('runAgainBuckets runSpecsBucketsAgain resolved', json);
    window.dispatchEvent(new CustomEvent('specs:buckets:updated', { detail: json }));
    debugLog('runAgainBuckets dispatched specs:buckets:updated event', { detailKeys: Object.keys(json ?? {}) });
    alert('Buckets wiped and re-extracted. Check the Specs panel for updates.');
  } catch (err) {
    console.error('[SpecsPatch] Specs rerun failed:', err);
    const message = err && err.message ? err.message : String(err);
    debugLog('runAgainBuckets encountered error', { message });
    alert('Rerunning specs failed: ' + message);
  } finally {
    if (button) {
      debugLog('runAgainBuckets restoring button to idle state', { buttonId: button.id });
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
    debugLog('DOMContentLoaded handler for SpecsPatch executing');
    const button = findRerunButton();
    if (button) {
      debugLog('Attaching click listener to rerun button', {
        buttonId: button.id,
        dataset: { ...button.dataset },
      });
      button.addEventListener('click', (event) => {
        debugLog('Rerun button click handler invoked', {
          buttonId: button.id,
          dataset: { ...button.dataset },
        });
        event.preventDefault();
        const currentId = coerceDocumentId(button.dataset?.docId ?? null);
        if (!currentId) {
          debugLog('Click handler aborting due to invalid coerceDocumentId result', {
            raw: button.dataset?.docId ?? null,
          });
          alert('Invalid document id');
          return;
        }
        debugLog('Click handler calling runAgainBuckets', { currentId });
        void runAgainBuckets(currentId);
      });
    } else {
      debugLog('DOMContentLoaded handler did not find rerun button');
    }
  });
}