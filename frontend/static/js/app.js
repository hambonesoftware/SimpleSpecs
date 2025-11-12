// Patched app.js to support "Rerun specs" functionality.
// This version augments the original SimpleSpecs UI to listen for
// `specs:buckets:updated` events (dispatched by specs_patch.js) and
// refresh the specification buckets when a re-run completes.  It
// preserves all existing functionality and state management.  Only
// additions and minimal non-breaking modifications have been made.

import {
  listDocuments,
  uploadDocument,
  parseDocument,
  fetchHeaders,
  fetchCachedHeaders,
  fetchDocumentStatus,
  fetchSectionText,
  fetchSpecifications,
  dispatchSpecAgents,
  fetchSpecAgentSections,
  fetchSpecAgentStatus,
  compareSpecifications,
  downloadBlob,
  fetchSpecRecord,
  approveSpecRecord,
  downloadSpecExport,
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
  renderSpecAnalysis,
  renderSpecAnalysisStatus,
  showToast,
  formatDate,
} from './ui.js';

// Application state.  This mirrors the upstream SimpleSpecs app.js state
// with the addition of tracking a fresh rerun in progress.
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
  specAnalysis: {
    sections: [],
    agentFilter: 'all',
    levelFilter: 'all',
    pollingHandle: null,
  },
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
  analyzeSpecs: document.querySelector('#analyze-specs'),
  specsAnalysis: document.querySelector('#specs-analysis'),
  specsAnalysisStatus: document.querySelector('#specs-analysis-status'),
  specsAnalysisResults: document.querySelector('#specs-analysis-results'),
  specsAgentFilter: document.querySelector('#specs-agent-filter'),
  specsLevelFilter: document.querySelector('#specs-level-filter'),
  specsContent: document.querySelector('#specs-content'),
  riskContent: document.querySelector('#risk-content'),
  approveSpecs: document.querySelector('#approve-specs'),
  approvalStatus: document.querySelector('#approval-status'),
  reviewerInput: document.querySelector('#reviewer-name'),
  headerModeTag: document.querySelector('#header-mode-tag'),
  refreshHeaders: document.querySelector('#refresh-headers'),
  startSpecs: document.querySelector('#start-specs'),
  // Accept both id variations for the rerun button
  rerunSpecs: document.querySelector('#run-again-buckets') || document.querySelector('#rerun-specs'),
};

// Utility: derive header matches from a headers payload
function deriveHeaderMatches(payload) {
  if (!payload || typeof payload !== 'object') {
    return [];
  }
  const headers = Array.isArray(payload.simpleheaders)
    ? payload.simpleheaders
    : Array.isArray(payload.headers)
      ? payload.headers
      : [];
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

function normaliseHeadersForUi(payload) {
  if (!payload || typeof payload !== 'object') {
    return payload;
  }
  if (!Array.isArray(payload.simpleheaders) && Array.isArray(payload.headers)) {
    return { ...payload, simpleheaders: payload.headers };
  }
  return payload;
}

function stopSpecPolling() {
  if (state.specAnalysis.pollingHandle) {
    clearTimeout(state.specAnalysis.pollingHandle);
    state.specAnalysis.pollingHandle = null;
  }
}

function resetSpecAnalysis() {
  stopSpecPolling();
  state.specAnalysis.sections = [];
  state.specAnalysis.agentFilter = 'all';
  state.specAnalysis.levelFilter = 'all';
  if (elements.specsAnalysis) {
    elements.specsAnalysis.hidden = true;
  }
  if (elements.specsAnalysisResults) {
    elements.specsAnalysisResults.innerHTML = '';
  }
  renderSpecAnalysisStatus(elements.specsAnalysisStatus, '');
  if (elements.specsAgentFilter) {
    elements.specsAgentFilter.value = 'all';
  }
  if (elements.specsLevelFilter) {
    elements.specsLevelFilter.value = 'all';
  }
}

function renderSpecAnalysisView() {
  renderSpecAnalysis(elements.specsAnalysisResults, state.specAnalysis.sections, {
    agent: state.specAnalysis.agentFilter,
    level: state.specAnalysis.levelFilter,
  });
}

async function loadSpecSections(documentId) {
  try {
    const response = await fetchSpecAgentSections(documentId);
    if (response?.ok && Array.isArray(response.sections)) {
      state.specAnalysis.sections = response.sections;
      renderSpecAnalysisView();
    }
  } catch (error) {
    console.error('Failed to load spec agent sections', error);
  }
}

async function pollSpecStatus(documentId) {
  try {
    const statusResponse = await fetchSpecAgentStatus(documentId);
    const counts = statusResponse?.counts ?? {};
    const sectionsTotal = counts.sections ?? 0;
    const running = counts.running ?? 0;
    const complete = counts.complete ?? 0;
    const failed = counts.failed ?? 0;
    const statusText = sectionsTotal
      ? `Sections: ${sectionsTotal} • Complete: ${complete} • Running: ${running}${
          failed ? ` • Failed: ${failed}` : ''
        }`
      : 'Awaiting sections…';
    renderSpecAnalysisStatus(
      elements.specsAnalysisStatus,
      statusText,
      failed ? 'warning' : running ? 'info' : 'success',
    );
    if (sectionsTotal) {
      await loadSpecSections(documentId);
    }
    if (sectionsTotal && running === 0) {
      stopSpecPolling();
      const toastMessage = failed
        ? `Spec agents finished with ${failed} section${failed === 1 ? '' : 's'} failing.`
        : 'Spec agents finished successfully.';
      showToast(toastMessage, failed ? 'warning' : 'info');
      return;
    }
  } catch (error) {
    console.error('Spec status poll failed', error);
    renderSpecAnalysisStatus(
      elements.specsAnalysisStatus,
      'Waiting for agent jobs to report status…',
      'warning',
    );
  }
  state.specAnalysis.pollingHandle = setTimeout(() => {
    void pollSpecStatus(documentId);
  }, 3000);
}

async function dispatchSpecAnalysis() {
  const documentId = state.selectedId;
  if (!documentId) {
    showToast('Select a document first.', 'error');
    return;
  }
  if (elements.specsAnalysis) {
    elements.specsAnalysis.hidden = false;
  }
  state.specAnalysis.agentFilter = 'all';
  state.specAnalysis.levelFilter = 'all';
  if (elements.specsAgentFilter) {
    elements.specsAgentFilter.value = 'all';
  }
  if (elements.specsLevelFilter) {
    elements.specsLevelFilter.value = 'all';
  }
  renderSpecAnalysisStatus(elements.specsAnalysisStatus, 'Dispatching agent jobs…', 'info');
  elements.specsAnalysisResults.innerHTML = '';
  stopSpecPolling();
  try {
    await dispatchSpecAgents(documentId);
    showToast('Spec extraction jobs queued.');
  } catch (error) {
    console.error(error);
    renderSpecAnalysisStatus(
      elements.specsAnalysisStatus,
      error instanceof Error ? error.message : 'Failed to dispatch spec jobs.',
      'error',
    );
    return;
  }
  await loadSpecSections(documentId);
  state.specAnalysis.pollingHandle = setTimeout(() => {
    void pollSpecStatus(documentId);
  }, 1000);
}

// Helper: update the header mode tag based on a mode string
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

// Drop zone initialization
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

// Wire up top-level actions
elements.refreshDocuments?.addEventListener('click', () => {
  void refreshDocuments();
});

elements.refreshHeaders?.addEventListener('click', () => {
  void refreshHeaders();
});

elements.startSpecs?.addEventListener('click', () => {
  void runSpecsSearch();
});

elements.analyzeSpecs?.addEventListener('click', () => {
  void dispatchSpecAnalysis();
});

elements.specsAgentFilter?.addEventListener('change', (event) => {
  state.specAnalysis.agentFilter = event.target.value || 'all';
  renderSpecAnalysisView();
});

elements.specsLevelFilter?.addEventListener('change', (event) => {
  state.specAnalysis.levelFilter = (event.target.value || 'all').toUpperCase();
  renderSpecAnalysisView();
});

// Wire the rerun specs button, if present.  We call our global SpecsPatch
// helper directly so the API deletion + rerun occurs from scratch.  If the
// button is missing, this silently does nothing.
elements.rerunSpecs?.addEventListener('click', () => {
  if (!state.selectedId) {
    showToast('Select a document first.', 'error');
    return;
  }
  // Use the globally exposed SpecsPatch helper to handle the UI updates on its own.
  if (window.SpecsPatch && typeof window.SpecsPatch.runAgainBuckets === 'function') {
    window.SpecsPatch.runAgainBuckets(state.selectedId);
  } else {
    showToast('Rerun function unavailable.', 'error');
  }
});

// Click handling for document list (select document)
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

// Export buttons
document.querySelectorAll('[data-export]').forEach((button) => {
  button.addEventListener('click', () => handleExport(button.dataset.export));
});

document.querySelectorAll('[data-server-export]').forEach((button) => {
  button.addEventListener('click', () => handleServerExport(button.dataset.serverExport));
});

elements.approveSpecs?.addEventListener('click', () => {
  void approveCurrentSpecs();
});

// Listen for custom event from specs_patch.js to update the UI when buckets are re-run.
window.addEventListener('specs:buckets:updated', (event) => {
  // Reset approval state and update specs
  const detail = event.detail ?? {};
  state.approvedLines.clear();
  state.specRecord = null;
  state.specs = detail;
  state.specsSearchAttempted = true;
  state.approvalLoading = false;
  renderSpecsView();
  updateApprovalUI();
  showToast('Specification buckets reloaded from scratch.');
  setSpecsSearchBusy(false);
  if (state.selectedId) {
    void (async () => {
      try {
        const refreshedRecord = await fetchSpecRecord(state.selectedId);
        state.specRecord = refreshedRecord;
        const refreshedPayload = refreshedRecord?.record?.payload ?? null;
        if (refreshedPayload && typeof refreshedPayload === 'object') {
          state.specs = refreshedPayload;
          renderSpecsView();
        }
      } catch (error) {
        console.error('[Specs] Unable to refresh spec record after rerun:', error);
      } finally {
        updateApprovalUI();
      }
    })();
  }
});

// Busy state helpers for header search & specs search
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
  const defaultLabel = state.headerSearchAttempted ? 'Run again' : 'Run header search';
  const ariaLabel = state.headerSearchAttempted
    ? 'Run the header search again'
    : 'Run the header search';
  button.textContent = defaultLabel;
  delete button.dataset.loading;
  button.removeAttribute('aria-busy');
  button.setAttribute('aria-label', ariaLabel);
  button.disabled = !state.selectedId;
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
// --- Add this helper to app.js (above showHeaderSearchPrompt) ---
function renderPanelStartPrompt(container, { message, buttonLabel, onStart }) {
  if (!container) return;

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
    if (typeof onStart === 'function') onStart();
  });

  wrapper.append(button);
  container.append(wrapper);
}
// --- end helper ---

// Display initial prompts for header and specs searches
function showHeaderSearchPrompt() {
  renderPanelStartPrompt(elements.headersContent, {
    message: 'No headers saved yet. Click Run header search to discover headers.',
    buttonLabel: 'Run header search',
    onStart: () => {
      void refreshHeaders();
    },
  });
  if (elements.headersRawContent) {
    elements.headersRawContent.innerHTML =
      '<p class="panel-status">Run the header search to view the persisted outline and trace.</p>';
  }
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

// API call wrappers
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
    if (!state.selectedId && elements.analyzeSpecs) {
      elements.analyzeSpecs.disabled = documents.length === 0;
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
  if (elements.analyzeSpecs) {
    elements.analyzeSpecs.disabled = false;
  }

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
  state.headerMatches = [];
  state.headerSearchAttempted = false;
  state.specsSearchAttempted = false;
  resetSpecAnalysis();
  showSpecsSearchPrompt();

  if (elements.workspaceSubtitle) {
    elements.workspaceSubtitle.textContent = 'Loading analysis results…';
  }

  setPanelLoading(elements.parseContent, 'Parsing document…');
  setPanelLoading(elements.headersContent, 'Checking saved headers…');
  if (elements.headersRawContent) {
    elements.headersRawContent.innerHTML = '<p class="panel-status">Checking header cache…</p>';
  }
  setPanelLoading(elements.riskContent, 'Computing risk score…');
  updateHeaderModeTag(null);
  setHeaderRefreshBusy(false);
  if (elements.refreshHeaders) {
    elements.refreshHeaders.disabled = true;
  }
  setSpecsSearchBusy(false);
  setApprovalStatus('Loading approval status…', 'muted');
  updateApprovalUI({ busy: true });

  let status = { parsed: false, headers: false };
  try {
    const statusResponse = await fetchDocumentStatus(documentId);
    if (statusResponse && typeof statusResponse === 'object') {
      status = { ...status, ...statusResponse };
    }
  } catch (error) {
    console.error('Failed to fetch document status', error);
    showToast('Unable to fetch document status.', 'error');
  }

  try {
    const parseResult = await parseDocument(documentId);
    state.parse = parseResult;
    renderParseSummary(elements.parseContent, state.parse);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to parse document.';
    state.parse = null;
    setPanelError(elements.parseContent, message);
  }

  if (!status.parsed || !status.headers) {
    try {
      const refreshedStatus = await fetchDocumentStatus(documentId);
      if (refreshedStatus && typeof refreshedStatus === 'object') {
        status = { ...status, ...refreshedStatus };
      }
    } catch (error) {
      console.warn('Unable to refresh document status after parsing', error);
    }
  }

  let headersLoaded = false;
  if (status.headers) {
    try {
      const cachedHeaders = await fetchCachedHeaders(documentId);
      state.headers = cachedHeaders;
      state.headerMatches = deriveHeaderMatches(state.headers);
      const uiPayload = normaliseHeadersForUi(state.headers);
      renderHeaderRawResponse(elements.headersRawContent, uiPayload);
      renderHeaderOutline(elements.headersContent, uiPayload, {
        documentId,
        fetchSection: fetchSectionText,
      });
      const modeHint = state.headers?.mode
        ?? state.headers?.meta?.mode
        ?? state.headers?.meta?.headers_mode
        ?? null;
      updateHeaderModeTag(modeHint);
      state.headerSearchAttempted = true;
      headersLoaded = true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to load saved headers.';
      setPanelError(elements.headersRawContent, message);
      setPanelError(elements.headersContent, message);
    }
  }

  if (!headersLoaded) {
    showHeaderSearchPrompt();
    if (elements.headersRawContent) {
      elements.headersRawContent.innerHTML =
        '<p class="panel-status">No headers saved yet. Run the header search to populate this panel.</p>';
    }
    state.headers = null;
    state.headerMatches = [];
    updateHeaderModeTag(null);
  }

  const [riskResult, recordResult] = await Promise.allSettled([
    compareSpecifications(documentId),
    fetchSpecRecord(documentId),
  ]);

  if (riskResult.status === 'fulfilled') {
    state.risk = riskResult.value;
    renderRiskPanel(elements.riskContent, state.risk);
  } else {
    state.risk = null;
    const message = riskResult.reason?.message ?? 'Unable to compute risk score.';
    setPanelError(elements.riskContent, message);
  }

  if (recordResult.status === 'fulfilled') {
    state.specRecord = recordResult.value;
    const payload = recordResult.value?.record?.payload ?? null;
    if (payload && typeof payload === 'object') {
      state.specs = payload;
      state.specsSearchAttempted = true;
      renderSpecsView();
    } else {
      state.specs = null;
    }
    state.approvalLoading = false;
    updateApprovalUI();
  } else {
    state.specRecord = null;
    state.approvalLoading = false;
    setApprovalStatus('Unable to load approval status.', 'error');
    updateApprovalUI({ preserveStatus: true });
  }

  setSpecsSearchBusy(false);
  setHeaderRefreshBusy(false);

  if (elements.workspaceSubtitle) {
    elements.workspaceSubtitle.textContent = `Document ${documentId} ready.`;
  }
}

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
    await fetchHeaders(documentId, { force: true });
    const latest = await fetchCachedHeaders(documentId);
    state.headers = latest;
    state.headerMatches = deriveHeaderMatches(state.headers);
    const uiPayload = normaliseHeadersForUi(state.headers);
    renderHeaderRawResponse(elements.headersRawContent, uiPayload);
    renderHeaderOutline(elements.headersContent, uiPayload, {
      documentId,
      fetchSection: fetchSectionText,
    });
    const modeHint = state.headers?.mode
      ?? state.headers?.meta?.mode
      ?? state.headers?.meta?.headers_mode
      ?? null;
    updateHeaderModeTag(modeHint);
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
      state.headers = previousHeaders;
      state.headerMatches = deriveHeaderMatches(previousHeaders);
      const uiPayload = normaliseHeadersForUi(previousHeaders);
      renderHeaderRawResponse(elements.headersRawContent, uiPayload);
      renderHeaderOutline(elements.headersContent, uiPayload, {
        documentId,
        fetchSection: fetchSectionText,
      });
      const modeHint = previousHeaders?.mode
        ?? previousHeaders?.meta?.mode
        ?? previousHeaders?.meta?.headers_mode
        ?? null;
      updateHeaderModeTag(modeHint);
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
    const message = error instanceof Error ? error.message : 'Unable to run specifications search.';
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

// Render the specs buckets panel
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
  if (elements.reviewerInput) {
    if (record?.reviewer) {
      elements.reviewerInput.value = record.reviewer;
    }
    elements.reviewerInput.disabled = loading || isApproved;
  }
  if (elements.startSpecs) {
    elements.startSpecs.disabled = loading || isApproved || !state.selectedId;
  }
  if (elements.rerunSpecs) {
    elements.rerunSpecs.disabled = loading || isApproved || !state.selectedId;
  }
  if (loading) {
    return;
  }
  if (isApproved) {
    const approvedDate = record?.approved_at ? formatDate(record.approved_at) : '—';
    const reviewer = record?.reviewer || '—';
    setApprovalStatus(`Approved by ${reviewer} on ${approvedDate}.`, 'success');
  } else if (!preserveStatus) {
    setApprovalStatus('Awaiting approval.', 'muted');
  }
}

async function handleExport(kind) {
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

// Initial load
void refreshDocuments();