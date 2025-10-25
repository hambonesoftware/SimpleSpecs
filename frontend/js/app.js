import {
  listDocuments,
  uploadDocument,
  parseDocument,
  fetchHeaders,
  fetchSpecifications,
  compareSpecifications,
  toCsv,
  downloadBlob,
} from './api.js';
import {
  initDropZone,
  createUploadTracker,
  renderDocumentList,
  setDocumentMeta,
  setPanelLoading,
  setPanelError,
  renderParseSummary,
  renderHeaderOutline,
  renderSpecsBuckets,
  renderRiskPanel,
  showToast,
} from './ui.js';

const state = {
  documents: [],
  selectedId: null,
  parse: null,
  headers: null,
  specs: null,
  risk: null,
  approvedLines: new Set(),
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
  specsContent: document.querySelector('#specs-content'),
  riskContent: document.querySelector('#risk-content'),
};

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
  renderDocumentList(elements.documentsList, state.documents, documentId);
  elements.documentsList?.setAttribute('aria-activedescendant', `document-${documentId}`);

  const documentRecord = state.documents.find((doc) => doc.id === documentId);
  setDocumentMeta(elements.documentMeta, documentRecord);

  if (elements.workspaceSubtitle) {
    elements.workspaceSubtitle.textContent = 'Loading analysis results…';
  }

  setPanelLoading(elements.parseContent, 'Parsing document…');
  setPanelLoading(elements.headersContent, 'Generating outline…');
  setPanelLoading(elements.specsContent, 'Classifying specification lines…');
  setPanelLoading(elements.riskContent, 'Computing risk score…');

  try {
    const [parseResult, headersResult, specsResult, riskResult] = await Promise.allSettled([
      parseDocument(documentId),
      fetchHeaders(documentId),
      fetchSpecifications(documentId),
      compareSpecifications(documentId),
    ]);

    if (parseResult.status === 'fulfilled') {
      state.parse = parseResult.value;
      renderParseSummary(elements.parseContent, state.parse);
    } else {
      state.parse = null;
      setPanelError(elements.parseContent, parseResult.reason?.message ?? 'Unable to parse document.');
    }

    if (headersResult.status === 'fulfilled') {
      state.headers = headersResult.value;
      renderHeaderOutline(elements.headersContent, state.headers);
    } else {
      state.headers = null;
      setPanelError(elements.headersContent, headersResult.reason?.message ?? 'Unable to load headers.');
    }

    if (specsResult.status === 'fulfilled') {
      state.specs = specsResult.value;
      renderSpecsBuckets(elements.specsContent, state.specs?.buckets ?? {}, {
        documentId,
        approvedLines: state.approvedLines,
        onApproveToggle: ({ approved }) => {
          if (approved) {
            showToast('Specification approved.');
          }
        },
      });
    } else {
      state.specs = null;
      setPanelError(elements.specsContent, specsResult.reason?.message ?? 'Unable to classify specifications.');
    }

    if (riskResult.status === 'fulfilled') {
      state.risk = riskResult.value;
      renderRiskPanel(elements.riskContent, state.risk);
    } else {
      state.risk = null;
      setPanelError(elements.riskContent, riskResult.reason?.message ?? 'Unable to compute risk score.');
    }
  } finally {
    if (elements.workspaceSubtitle) {
      elements.workspaceSubtitle.textContent = `Document ${documentId} ready.`;
    }
  }
}

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
      case 'specs-csv': {
        if (!state.specs?.buckets) throw new Error('No specification buckets to export.');
        const rows = [];
        for (const [discipline, lines] of Object.entries(state.specs.buckets)) {
          lines.forEach((line) => {
            rows.push({
              discipline,
              text: line.text,
              page: typeof line.page === 'number' ? line.page + 1 : '',
              header: Array.isArray(line.header_path) ? line.header_path.join(' > ') : '',
              source: line.source ?? 'rule',
            });
          });
        }
        const csv = toCsv(rows);
        downloadBlob(`specs-${documentId}.csv`, csv, 'text/csv');
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

void refreshDocuments();
