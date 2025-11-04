import {
  listDocuments,
  uploadDocument,
  parseDocument,
  fetchHeaders,
  fetchSectionText,
  fetchSpecifications,
  compareSpecifications,
  downloadBlob,
  fetchSpecRecord,
  approveSpecRecord,
  downloadSpecExport,
  deleteSpecsBuckets,
  runSpecsBucketsAgain,
} from './api.js';
import {
  initDropZone,
  createUploadTracker,
  renderDocumentList,
  setDocumentMeta,
  setPanelLoading,
  setPanelError,
  renderParseSummary,
  renderHeaderRawResponse,
  renderHeaderOutline,
  renderSpecsBuckets,
  renderRiskPanel,
  showToast,
  formatDate,
} from './ui.js';

const state = {
  documents: [],
  selectedId: null,
  parse: null,
  headers: null,
  specs: null,
  risk: null,
  approvedLines: new Set(),
  specRecord: null,
  approvalLoading: false,
  headerSearchAttempted: false,
  specsSearchAttempted: false,
  headerMatches: [],
};

const elements = {
  dropZone: document.querySelector('#drop-zone'),
  fileInput: document.querySelector('#file-input'),
  browseButton: document.querySelector('#browse-button'),
  uploadProgress: document.querySelector('#upload-progress'),
  documentsStatus: document.querySelector('#documents-status'),
  documentsList: document.querySelector('#documents-list'),
  refreshDocuments: document.querySelector('#refresh-documents'),
  documentMeta: document.querySelector('#document-meta'),
  workspaceSubtitle: document.querySelector('#workspace-subtitle'),
  parseContent: document.querySelector('#parse-content'),
  headersContent: document.querySelector('#headers-content'),
  headersRawContent: document.querySelector('#headers-raw-content'),
  specsContent: document.querySelector('#specs-content'),
  riskContent: document.querySelector('#risk-content'),
  approveSpecs: document.querySelector('#approve-specs'),
  approvalStatus: document.querySelector('#approval-status'),
  reviewerInput: document.querySelector('#reviewer-name'),
  headerModeTag: document.querySelector('#header-mode-tag'),
  refreshHeaders: document.querySelector('#refresh-headers'),
  startSpecs: document.querySelector('#start-specs'),
  rerunSpecs: document.querySelector('#rerun-specs'),
};

function renderPanelStartPrompt(container, { message, buttonLabel, onStart }) {
  if (!container) {
    return;
  }

  container.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'panel-status panel-status--actionable';

  const text = document.createElement('p');
  text.className = 'panel-status__message';
  text.textContent = message;
  wrapper.append(text);

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'primary-button';
  button.textContent = buttonLabel;
  button.addEventListener('click', () => {
    if (typeof onStart === 'function') {
      onStart();
    }
  });
  wrapper.append(button);

  container.append(wrapper);
}

function deriveHeaderMatches(payload) {
  if (!payload || typeof payload !== 'object') {
    return [];
  }

  // Use canonical field from backend payload
  const headers = Array.isArray(payload.headers) ? payload.headers : [];
  return headers
    .map((header) => {
      const text = typeof header.text === 'string' ? header.text : '';
      const number = header.number != null && String(header.number).trim() !== ''
        ? String(header.number)
        : null;
      const page = Number(header.page);
      const line = Number(header.line_idx);
      const globalIdx = Number(header.global_idx);

      return {
        text,
        number,
        page: Number.isFinite(page) ? page : null,
        line: Number.isFinite(line) ? line : null,
        globalIdx: Number.isFinite(globalIdx) ? globalIdx : null,
      };
    })
    .filter((entry) => entry.text);
}


function updateHeaderModeTag(mode) {
  const tag = elements.headerModeTag;
  if (!tag) return;

  if (!mode) {
    tag.hidden = true;
    tag.textContent = '';
    tag.removeAttribute('data-variant');
    tag.removeAttribute('aria-label');
    tag.removeAttribute('title');
    return;
  }

  const m = String(mode).toLowerCase();
  let label = 'LLM';
  let variant = 'llm';
  let description = 'Headers derived via LLM extraction.';

  if (m === 'llm_full_error') {
    description = 'LLM header extraction failed; see logs for details.';
  } else if (m === 'llm_disabled') {
    label = 'Off';
    variant = 'openrouter';
    description = 'LLM header extraction is disabled.';
  } else if (m === 'llm_strict') {
    label = 'LLM (strict)';
    description = 'LLM headers aligned with strict anchor matching.';
  } else if (m === 'llm_vector') {
    label = 'LLM (vector)';
    description = 'LLM headers aligned with vector embeddings.';
  } else if (m === 'cache') {
    label = 'Cached';
    variant = 'llm';
    description = 'Using cached header outline.';
  }

  tag.textContent = label;
  tag.dataset.variant = variant;
  tag.setAttribute('aria-label', description);
  tag.setAttribute('title', description);
  tag.hidden = false;
}


initDropZone({
  zone: elements.dropZone,
  input: elements.fileInput,
  browseButton: elements.browseButton,
  onFiles: async (files) => {
    for (const file of files) {
      const tracker = createUploadTracker(elements.uploadProgress, file.name);
      try {
        await uploadDocument(file, (progress) => tracker.updateProgress(progress));
        tracker.markComplete('Uploaded');
        showToast(`${file.name} uploaded successfully.`);
      } catch (error) {
        tracker.markError(error.message);
        showToast(error.message, 'error');
      }
    }
    await refreshDocuments();
  },
});

elements.refreshDocuments?.addEventListener('click', () => {
  void refreshDocuments();
});
elements.rerunSpecs?.addEventListener('click', () => {
  void rerunSpecsNow();
});

elements.refreshHeaders?.addEventListener('click', () => {
  void refreshHeaders();
});

elements.startSpecs?.addEventListener('click', () => {
  void runSpecsSearch();
});

elements.documentsList?.addEventListener('click', (event) => {
  const target = event.target.closest('[data-document-id]');
  if (!target) return;
  const documentId = Number(target.dataset.documentId);
  if (Number.isFinite(documentId)) {
    void selectDocument(documentId);
  }
});

elements.documentsList?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return;
  }
  const target = event.target.closest('[data-document-id]');
  if (!target) return;
  event.preventDefault();
  const documentId = Number(target.dataset.documentId);
  if (Number.isFinite(documentId)) {
    void selectDocument(documentId);
  }
});

document.querySelectorAll('[data-export]').forEach((button) => {
  button.addEventListener('click', () => handleExport(button.dataset.export));
});

document.querySelectorAll('[data-server-export]').forEach((button) => {
  button.addEventListener('click', () => handleServerExport(button.dataset.serverExport));
});

elements.approveSpecs?.addEventListener('click', () => {
  void approveCurrentSpecs();
});

async function refreshDocuments() {
  try {
    elements.documentsStatus.textContent = 'Loading documents…';
    const documents = await listDocuments();
    state.documents = documents;
    renderDocumentList(elements.documentsList, documents, state.selectedId);
    if (!documents.length) {
      elements.documentsStatus.textContent = 'No documents uploaded yet.';
    } else {
      elements.documentsStatus.textContent = `Showing ${documents.length} document${
        documents.length === 1 ? '' : 's'
      }.`;
    }
  } catch (error) {
    console.error(error);
    elements.documentsStatus.textContent = error instanceof Error ? error.message : 'Unable to fetch documents.';
    showToast('Unable to fetch documents.', 'error');
  }
}

async function selectDocument(documentId) {
  if (state.selectedId === documentId) {
    return;
  }
  state.selectedId = documentId;
  state.approvedLines.clear();
  state.specRecord = null;
  state.approvalLoading = true;
  renderDocumentList(elements.documentsList, state.documents, documentId);
  elements.documentsList?.setAttribute('aria-activedescendant', `document-${documentId}`);

  const documentRecord = state.documents.find((doc) => doc.id === documentId);
  setDocumentMeta(elements.documentMeta, documentRecord);

  state.parse = null;
  state.headers = null;
  state.specs = null;
  state.risk = null;
  state.headerSearchAttempted = false;
  state.specsSearchAttempted = false;
  state.headerMatches = [];

  if (elements.workspaceSubtitle) {
    elements.workspaceSubtitle.textContent = 'Loading analysis results…';
  }

  setPanelLoading(elements.parseContent, 'Parsing document…');
  showHeaderSearchPrompt();
  showSpecsSearchPrompt();
  setPanelLoading(elements.riskContent, 'Computing risk score…');
  updateHeaderModeTag(null);
  setHeaderRefreshBusy(false);
  setSpecsSearchBusy(false);
  // NEW:
  setSpecsRerunBusy(false);

  setApprovalStatus('Loading approval status…', 'muted');
  updateApprovalUI({ busy: true });

  try {
    const [parseResult, riskResult, recordResult] = await Promise.allSettled([
      parseDocument(documentId),
      compareSpecifications(documentId),
      fetchSpecRecord(documentId),
    ]);

    if (parseResult.status === 'fulfilled') {
      state.parse = parseResult.value;
      renderParseSummary(elements.parseContent, state.parse);
    } else {
      state.parse = null;
      setPanelError(elements.parseContent, parseResult.reason?.message ?? 'Unable to parse document.');
    }

    if (riskResult.status === 'fulfilled') {
      state.risk = riskResult.value;
      renderRiskPanel(elements.riskContent, state.risk);
    } else {
      state.risk = null;
      setPanelError(elements.riskContent, riskResult.reason?.message ?? 'Unable to compute risk score.');
    }

    if (recordResult.status === 'fulfilled') {
      state.specRecord = recordResult.value;
      state.approvalLoading = false;
      updateApprovalUI();
      renderSpecsView();
    } else {
      state.specRecord = null;
      state.approvalLoading = false;
      setApprovalStatus('Unable to load approval status.', 'error');
      updateApprovalUI({ preserveStatus: true });
    }
  } finally {
    if (elements.workspaceSubtitle) {
      elements.workspaceSubtitle.textContent = `Document ${documentId} ready.`;
    }
  }
}


function setSpecsRerunBusy(busy) {
  const button = elements.rerunSpecs;
  if (!button) return;

  if (busy) {
    button.disabled = true;
    button.dataset.loading = 'true';
    button.textContent = 'Re-running…';
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-label', 'Re-running specifications (fresh LLM)');
    return;
  }

  button.textContent = 'Rerun specs';
  delete button.dataset.loading;
  button.removeAttribute('aria-busy');
  button.setAttribute('aria-label', 'Wipe and re-run specifications from the LLM');
  button.disabled = !state.selectedId;
}


async function rerunSpecsNow() {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }

  // Don’t allow reruns on frozen records
  const isApproved = state.specRecord?.record?.state === 'approved';
  if (isApproved) {
    showToast('Specifications are frozen (approved). Unfreeze in the backend to rerun.', 'error');
    return;
  }

  setSpecsRerunBusy(true);
  setPanelLoading(elements.specsContent, 'Re-running specifications (fresh LLM)…');

  try {
    // 1) Wipe any server-side stored buckets
    try {
      await deleteSpecsBuckets(documentId);
    } catch (wipeErr) {
      // Non-fatal; proceed even if nothing existed.
      console.warn('[Specs] delete buckets failed/ignored', wipeErr);
    }

    // 2) Trigger a clean re-extraction that bypasses caches on the server
    const fresh = await runSpecsBucketsAgain(documentId);

    // 3) Update UI
    state.specs = fresh;
    renderSpecsView();
    showToast('Specifications re-extracted from the LLM.');
    updateApprovalUI();
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to rerun specifications.';
    setPanelError(elements.specsContent, message);
    showToast(message, 'error');
    // keep prior state.specs if it existed; render if so
    if (state.specs) renderSpecsView();
  } finally {
    setSpecsRerunBusy(false);
  }
}

function setHeaderRefreshBusy(busy) {
  const button = elements.refreshHeaders;
  if (!button) {
    return;
  }

  delete button.dataset.defaultLabel;

  if (busy) {
    button.disabled = true;
    button.dataset.loading = 'true';
    button.textContent = 'Running…';
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-label', 'Running header search');
    return;
  }

  const defaultLabel = state.headerSearchAttempted ? 'Run again' : 'Start search';
  const ariaLabel = state.headerSearchAttempted
    ? 'Run the header search again'
    : 'Start the header search';

  button.textContent = defaultLabel;
  delete button.dataset.loading;
  button.removeAttribute('aria-busy');
  button.setAttribute('aria-label', ariaLabel);
  button.disabled = !state.selectedId;
}
// Add this small helper anywhere above refreshHeaders (e.g., near other helpers)
function buildHeaderUIPayload(headersResult) {
  // The UI expects `simpleheaders` + `sections`. Backend returns `headers` + `sections`.
  // Create a backward-compatible alias so the SimpleHeaders view renders.
  if (!headersResult || typeof headersResult !== 'object') return headersResult;
  if (!Array.isArray(headersResult.simpleheaders) && Array.isArray(headersResult.headers)) {
    return { ...headersResult, simpleheaders: headersResult.headers };
  }
  return headersResult;
}

// Replace the entire refreshHeaders function with this version
async function refreshHeaders() {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }

  const previousHeaders = state.headers;
  state.headerSearchAttempted = true;
  setHeaderRefreshBusy(true);
  setPanelLoading(elements.headersContent, 'Running header search…');
  setPanelLoading(elements.headersRawContent, 'Fetching raw response…');
  updateHeaderModeTag(null);

  try {
    // Force fresh run (purges cache server-side if available) so "Run again" really re-does work.
    const headersResult = await fetchHeaders(documentId, { force: true });

    // Keep canonical payload in state, but pass a UI-friendly alias to renderers
    state.headers = headersResult;
    state.headerMatches = deriveHeaderMatches(state.headers);

    const uiPayload = buildHeaderUIPayload(state.headers);

    // Raw & outline panes
    renderHeaderRawResponse(elements.headersRawContent, uiPayload);
    renderHeaderOutline(elements.headersContent, uiPayload, {
      documentId,
      fetchSection: fetchSectionText,
    });

    // Mode tag + any backend messages
    updateHeaderModeTag(state.headers?.mode ?? null);
    if (Array.isArray(state.headers?.messages)) {
      for (const message of state.headers.messages) {
        if (message) showToast(message, 'warning', 6000);
      }
    }

    showToast('Header search completed.');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to run header search.';
    showToast(message, 'error');

    if (previousHeaders) {
      // Fall back to the last known-good outline on failure
      state.headers = previousHeaders;
      state.headerMatches = deriveHeaderMatches(previousHeaders);

      const uiPayload = buildHeaderUIPayload(previousHeaders);

      renderHeaderRawResponse(elements.headersRawContent, uiPayload);
      renderHeaderOutline(elements.headersContent, uiPayload, {
        documentId,
        fetchSection: fetchSectionText,
      });
      updateHeaderModeTag(previousHeaders?.mode ?? null);
    } else {
      state.headerMatches = [];
      setPanelError(elements.headersRawContent, message);
      setPanelError(elements.headersContent, message);
      updateHeaderModeTag(null);
    }
  } finally {
    setHeaderRefreshBusy(false);
  }
}



// (Optional but recommended) tweak showHeaderSearchPrompt to ensure the raw pane hints at the trace panel too
function showHeaderSearchPrompt() {
  renderPanelStartPrompt(elements.headersContent, {
    message: 'Press Start to generate the header outline.',
    buttonLabel: 'Start search',
    onStart: () => {
      void refreshHeaders();
    },
  });
  if (elements.headersRawContent) {
    elements.headersRawContent.innerHTML =
      '<p class="panel-status">Run the header search to view the raw response and trace.</p>';
  }
}


function setSpecsSearchBusy(busy) {
  const button = elements.startSpecs;
  if (!button) {
    return;
  }

  if (busy) {
    button.disabled = true;
    button.dataset.loading = 'true';
    button.textContent = 'Running…';
    button.setAttribute('aria-busy', 'true');
    button.setAttribute('aria-label', 'Running specifications search');
    return;
  }

  const defaultLabel = state.specsSearchAttempted ? 'Run again' : 'Start search';
  const ariaLabel = state.specsSearchAttempted
    ? 'Run the specifications search again'
    : 'Start the specifications search';

  button.textContent = defaultLabel;
  delete button.dataset.loading;
  button.removeAttribute('aria-busy');
  button.setAttribute('aria-label', ariaLabel);
  button.disabled = !state.selectedId;
}

function showSpecsSearchPrompt() {
  renderPanelStartPrompt(elements.specsContent, {
    message: 'Press Start to classify specification lines into buckets.',
    buttonLabel: 'Start search',
    onStart: () => {
      void runSpecsSearch();
    },
  });
}

async function runSpecsSearch() {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }

  const previousSpecs = state.specs;
  let success = false;
  state.specsSearchAttempted = true;
  setSpecsSearchBusy(true);
  setPanelLoading(elements.specsContent, 'Classifying specification lines…');

  try {
    const specsResult = await fetchSpecifications(documentId);
    state.specs = specsResult;
    renderSpecsView();
    showToast('Specifications search completed.');
    success = true;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'Unable to run specifications search.';
    showToast(message, 'error');
    if (previousSpecs) {
      state.specs = previousSpecs;
      renderSpecsView();
    } else {
      state.specs = null;
      setPanelError(elements.specsContent, message);
    }
    updateApprovalUI({ preserveStatus: true });
  } finally {
    setSpecsSearchBusy(false);
    if (success) {
      updateApprovalUI();
    }
  }
}

setHeaderRefreshBusy(false);
setSpecsSearchBusy(false);

function handleExport(kind) {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }

  try {
    switch (kind) {
      case 'parse': {
        if (!state.parse) throw new Error('Parse data unavailable.');
        downloadBlob(`parse-${documentId}.json`, JSON.stringify(state.parse, null, 2));
        break;
      }
      case 'headers': {
        if (!state.headers) throw new Error('Header outline unavailable.');
        downloadBlob(`headers-${documentId}.json`, JSON.stringify(state.headers, null, 2));
        break;
      }
      case 'specs-json': {
        if (!state.specs?.buckets) throw new Error('No specification buckets to export.');
        downloadBlob(`specs-${documentId}.json`, JSON.stringify(state.specs, null, 2));
        break;
      }
      case 'risk': {
        if (!state.risk) throw new Error('Risk report unavailable.');
        downloadBlob(`risk-${documentId}.json`, JSON.stringify(state.risk, null, 2));
        break;
      }
      default:
        throw new Error('Unsupported export type.');
    }
    showToast('Export started.');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to export data.';
    showToast(message, 'error');
  }
}

async function handleServerExport(format) {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }
  try {
    const { blob, filename } = await downloadSpecExport(documentId, format);
    downloadBlob(filename, blob);
    showToast('Export ready for download.');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to export specifications.';
    showToast(message, 'error');
  }
}

async function approveCurrentSpecs() {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }
  if (!state.specs) {
    showToast('Specifications not ready for approval.', 'error');
    return;
  }

  const reviewer = elements.reviewerInput?.value?.trim() || 'web-user';
  state.approvalLoading = true;
  updateApprovalUI({ busy: true });
  setApprovalStatus('Submitting approval…', 'muted');

  try {
    const response = await approveSpecRecord(documentId, {
      reviewer,
      payload: state.specs,
    });
    state.specRecord = response;
    state.approvalLoading = false;
    updateApprovalUI();
    renderSpecsView();
    showToast('Specifications approved.');
  } catch (error) {
    state.approvalLoading = false;
    updateApprovalUI();
    const message = error instanceof Error ? error.message : 'Unable to approve specifications.';
    setApprovalStatus(message, 'error');
    showToast(message, 'error');
  }
}

function renderSpecsView() {
  if (!elements.specsContent) {
    return;
  }
  if (!state.specs) {
    return;
  }
  const buckets = state.specs?.buckets ?? {};
  const readOnly = state.specRecord?.record?.state === 'approved';
  renderSpecsBuckets(elements.specsContent, buckets, {
    documentId: state.selectedId,
    approvedLines: state.approvedLines,
    readOnly,
    onApproveToggle: ({ approved }) => {
      if (approved) {
        showToast('Specification approved.');
      }
    },
  });
}

function setApprovalStatus(message, tone = 'muted') {
  if (!elements.approvalStatus) {
    return;
  }
  elements.approvalStatus.textContent = message;
  elements.approvalStatus.dataset.tone = tone;
}

function updateApprovalUI({ busy = false, preserveStatus = false } = {}) {
  const record = state.specRecord?.record ?? null;
  const isApproved = record?.state === 'approved';
  const loading = busy || state.approvalLoading;

  if (elements.approveSpecs) {
    elements.approveSpecs.disabled = loading || isApproved || !state.specs;
    if (loading) {
      elements.approveSpecs.textContent = 'Working…';
    } else if (isApproved) {
      elements.approveSpecs.textContent = 'Approved';
    } else {
      elements.approveSpecs.textContent = 'Approve & Freeze';
    }
  }

  // NEW: keep Start/Rerun buttons coherent with state
  if (elements.startSpecs) {
    elements.startSpecs.disabled = loading || isApproved || !state.selectedId;
  }
  if (elements.rerunSpecs) {
    elements.rerunSpecs.disabled = loading || isApproved || !state.selectedId;
  }

  if (elements.reviewerInput) {
    if (record?.reviewer) {
      elements.reviewerInput.value = record.reviewer;
    }
    elements.reviewerInput.disabled = loading || isApproved;
  }

  if (loading) return;

  if (isApproved) {
    const approvedDate = record?.approved_at ? formatDate(record.approved_at) : '—';
    const reviewer = record?.reviewer || '—';
    setApprovalStatus(`Approved by ${reviewer} on ${approvedDate}.`, 'success');
  } else if (!preserveStatus) {
    setApprovalStatus('Awaiting approval.', 'muted');
  }
}


void refreshDocuments();
