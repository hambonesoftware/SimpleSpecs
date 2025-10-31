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

function updateHeaderModeTag(mode) {
  const tag = elements.headerModeTag;
  if (!tag) {
    return;
  }

  if (!mode) {
    tag.hidden = true;
    tag.textContent = '';
    tag.removeAttribute('data-variant');
    tag.removeAttribute('aria-label');
    tag.removeAttribute('title');
    return;
  }

  const normalised = String(mode).toLowerCase();
  let label = 'LLM';
  let variant = 'openrouter';
  let description = 'Headers derived from the OpenRouter LLM.';

  if (normalised === 'llm_full') {
    label = 'LLM';
    variant = 'llm';
    description = 'Headers derived via LLM extraction.';
  } else if (normalised === 'llm_full_error') {
    label = 'LLM';
    variant = 'llm';
    description = 'LLM header extraction failed; see logs for details.';
  } else if (normalised === 'llm_disabled') {
    label = 'Off';
    variant = 'openrouter';
    description = 'LLM header extraction is disabled.';
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
    const headersResult = await fetchHeaders(documentId);
    state.headers = headersResult;
    renderHeaderRawResponse(elements.headersRawContent, state.headers?.fenced_text ?? '');
    renderHeaderOutline(elements.headersContent, state.headers, {
      documentId,
      fetchSection: fetchSectionText,
    });
    updateHeaderModeTag(state.headers?.mode ?? null);
    if (Array.isArray(state.headers?.messages)) {
      state.headers.messages.forEach((message) => {
        if (!message) {
          return;
        }
        showToast(message, 'warning', 6000);
      });
    }
    showToast('Header search completed.');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unable to run header search.';
    showToast(message, 'error');
    if (previousHeaders) {
      state.headers = previousHeaders;
      renderHeaderRawResponse(
        elements.headersRawContent,
        previousHeaders?.fenced_text ?? '',
      );
      renderHeaderOutline(elements.headersContent, previousHeaders, {
        documentId,
        fetchSection: fetchSectionText,
      });
      updateHeaderModeTag(previousHeaders?.mode ?? null);
    } else {
      setPanelError(elements.headersRawContent, message);
      setPanelError(elements.headersContent, message);
      updateHeaderModeTag(null);
    }
  } finally {
    setHeaderRefreshBusy(false);
  }
}

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
      '<p class="panel-status">Run the header search to view the raw response.</p>';
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

  if (elements.reviewerInput) {
    if (record?.reviewer) {
      elements.reviewerInput.value = record.reviewer;
    }
    elements.reviewerInput.disabled = loading || isApproved;
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

void refreshDocuments();
