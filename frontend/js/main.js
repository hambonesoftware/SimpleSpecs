import {
  checkHealth,
  uploadFile,
  fetchObjects,
  fetchModelSettings,
  requestHeaders,
  requestSpecs,
  exportSpecs,
  updateModelSettings,
} from "./api.js";
import {
  state,
  setUpload,
  setObjects,
  setHeaders,
  setSpecs,
  setSectionText,
  updateSettings,
  addLog,
  resetLogs,
  markHeaderProcessed,
} from "./state.js";
import { MAX_TOKENS_LIMIT } from "./constants.js";
import {
  renderHeadersTree,
  renderSidebarHeadersList,
  updateSectionPreview,
  renderSpecsTable,
  setActiveTab,
  updateHealthStatus,
  updateProgress,
  appendLog,
  toggleSettings,
} from "./ui.js";

const fileInput = document.getElementById("file-input");
const dropZone = document.getElementById("drop-zone");
const uploadButton = document.getElementById("upload-button");
const headersTreeEl = document.getElementById("headers-tree");
const sectionPreviewEl = document.getElementById("section-preview");
const sidebarHeadersEl = document.getElementById("sidebar-headers");
const headersCountEl = document.getElementById("headers-count");
const specsTableBody = document.querySelector("#specs-table tbody");
const specsSearch = document.getElementById("specs-search");
const sortSelect = document.getElementById("sort-select");
const tabs = Array.from(document.querySelectorAll(".tab"));
const tabContents = Array.from(document.querySelectorAll(".tab-content"));
const healthIndicator = document.getElementById("health-indicator");
const healthLabel = document.getElementById("health-label");
const progressFill = document.getElementById("progress-fill");
const logConsole = document.getElementById("log-console");
const findHeadersBtn = document.getElementById("find-headers");
const findSpecsBtn = document.getElementById("find-specs");
const exportCsvBtn = document.getElementById("export-csv");
const toggleSettingsBtn = document.getElementById("toggle-settings");
const settingsPanel = document.getElementById("settings-panel");
const settingsForm = document.getElementById("settings-form");

let selectedFile = null;
let activeTab = "headers";
let activeSection = null;
let settingsSaveTimer = null;
let allowSettingsAutosave = false;
let lastPersistedSettings = null;
const reportedInvalidHeaderMatches = new Set();

const TOC_PATTERNS = [
  /(?:\. ?){4,}/,
  /(?:[_\-·•]\s?){3,}/,
  /(?:[._\-·•]\s?){4,}(?:\d{1,4}|[IVXLCDM]{1,6})\s*$/i,
];

function log(message) {
  addLog(message);
  appendLog(logConsole, message);
}

function clearLog() {
  resetLogs();
  logConsole.textContent = "";
}

function getDocumentLines() {
  const lines = [];
  (state.objects || []).forEach((obj) => {
    if (obj.type === "text") {
      const text = (obj.content || "").trim();
      if (text) lines.push(text);
    } else if (obj.type === "table") {
      const text = (obj.content || "").split(/\r?\n/).map((line) => line.trim());
      text.filter(Boolean).forEach((line) => lines.push(line));
    }
  });
  return lines;
}

function normalize(value) {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function isLikelyTableOfContentsLine(line) {
  if (!line) return false;
  const trimmed = line.trim();
  if (!trimmed) return false;
  return TOC_PATTERNS.some((pattern) => pattern.test(trimmed));
}

function findLineIndex(lines, header, { reportMismatch = false } = {}) {
  const combo = normalize(`${header.section_number} ${header.section_name}`);
  const number = normalize(header.section_number);
  const name = normalize(header.section_name);
  const invalidMatches = [];

  const checks = [
    (current) => current.startsWith(combo),
    (current) => number && current.startsWith(number) && current.includes(name),
    (current) => name && current.includes(name),
  ];

  for (const check of checks) {
    for (let i = 0; i < lines.length; i += 1) {
      const original = lines[i];
      const current = normalize(original);
      if (!check(current)) continue;
      if (isLikelyTableOfContentsLine(original)) {
        invalidMatches.push({ index: i, line: original });
        continue;
      }
      return i;
    }
  }

  if (reportMismatch && invalidMatches.length > 0) {
    const key = `${header.section_number} ${header.section_name}`.trim();
    if (!reportedInvalidHeaderMatches.has(key)) {
      reportedInvalidHeaderMatches.add(key);
      log(
        `Skipping match for "${header.section_number} ${header.section_name}" because the line in the document contains too many periods and appears to be from a table of contents.`,
      );
    }
  }

  return -1;
}

function computeSectionText(header) {
  const lines = getDocumentLines();
  if (!lines.length) return "";
  const headers = state.headers || [];
  const start = findLineIndex(lines, header, { reportMismatch: true });
  if (start < 0) {
    return "Unable to match this header to the document text because the closest line contains too many periods (likely a table of contents entry).";
  }
  let end = lines.length;
  headers.forEach((candidate) => {
    if (candidate.section_number === header.section_number) return;
    const candidateIndex = findLineIndex(lines, candidate);
    if (candidateIndex >= 0 && candidateIndex > start && candidateIndex < end) {
      end = candidateIndex;
    }
  });
  return lines.slice(start, end).join("\n").trim();
}

function getProcessedSections() {
  const processed = new Set();
  state.headerProgress?.forEach((isComplete, section) => {
    if (isComplete) processed.add(section);
  });
  return processed;
}

function selectHeader(header, { refresh = true } = {}) {
  if (!header) return;
  activeSection = header.section_number;
  let preview = header.chunk_text;
  if (preview == null) {
    preview = state.sectionTexts.get(header.section_number);
  }
  if (preview == null) {
    preview = computeSectionText(header);
  }
  const text = preview ?? "";
  setSectionText(header.section_number, text);
  updateSectionPreview(sectionPreviewEl, { header, text });
  if (refresh) {
    refreshHeaders();
  }
}

function refreshHeaders() {
  const processedSections = getProcessedSections();
  if (!state.headers?.length) {
    activeSection = null;
  }

  renderHeadersTree(headersTreeEl, state.headers, {
    activeSection,
    processedSections,
    onSelect: (header) => selectHeader(header),
  });

  renderSidebarHeadersList(sidebarHeadersEl, state.headers, {
    activeSection,
    processedSections,
    onSelect: (header) => selectHeader(header),
  });

  if (!activeSection) {
    updateSectionPreview(sectionPreviewEl, "Select a header to preview text.");
  }

  headersCountEl.textContent = String(state.headers?.length || 0);
}

function refreshSpecs() {
  renderSpecsTable(specsTableBody, state.specs, {
    searchTerm: specsSearch.value,
    sortKey: sortSelect.value,
  });
}

async function loadObjects(uploadId) {
  const { items } = await fetchObjects(uploadId, 1, 1000);
  setObjects(items);
}

async function handleUpload() {
  if (!selectedFile) {
    log("Please select a file before uploading.");
    return;
  }
  clearLog();
  log(`Uploading ${selectedFile.name}…`);
  updateProgress(progressFill, 10);
  try {
    const response = await uploadFile(selectedFile);
    log(`Parsed ${response.object_count} objects (upload ${response.upload_id}).`);
    await loadObjects(response.upload_id);
    setUpload({ uploadId: response.upload_id, objects: state.objects });
    reportedInvalidHeaderMatches.clear();
    refreshHeaders();
    updateProgress(progressFill, 40);
    log("Document ready. Proceed with header extraction.");
    updateProgress(progressFill, 50);
  } catch (error) {
    log(`Upload failed: ${error.message}`);
    updateProgress(progressFill, 0);
    throw error;
  }
}

async function handleHeaders() {
  if (!state.uploadId) {
    log("Upload a document before extracting headers.");
    return;
  }
  if (!state.model) {
    log("Please configure a model name in settings.");
    return;
  }
  log("Requesting headers from LLM…");
  reportedInvalidHeaderMatches.clear();
  updateProgress(progressFill, 60);
  const config = {
    uploadId: state.uploadId,
    provider: state.provider,
    model: state.model,
    params: state.params,
    apiKey: state.apiKey,
    baseUrl: state.baseUrl,
  };
  const startTime = performance.now();
  try {
    const headers = await requestHeaders(config);
    setHeaders(headers);
    headers.forEach((header) => {
      const text = header.chunk_text || computeSectionText(header);
      if (text !== undefined && text !== null) {
        setSectionText(header.section_number, text);
      }
    });
    if (headers.length > 0) {
      selectHeader(headers[0], { refresh: false });
    }
    refreshHeaders();
    updateProgress(progressFill, 75);
    const duration = ((performance.now() - startTime) / 1000).toFixed(1);
    log(`Headers extracted (${headers.length}) in ${duration}s.`);
  } catch (error) {
	const rawResponse = error?.detail?.response_text;
    log(`Header extraction failed: ${rawResponse}`);
    if (rawResponse) {
      log("Raw LLM response:");
      log(rawResponse);
    }
    updateProgress(progressFill, 50);
  }
}

async function handleSpecs() {
  if (!state.uploadId) {
    log("Upload a document before extracting specifications.");
    return;
  }
  if (!state.headers.length) {
    log("Please run header extraction first.");
    return;
  }
  if (!state.model) {
    log("Please configure a model name in settings.");
    return;
  }
  log("Requesting specifications from LLM…");
  updateProgress(progressFill, 80);
  const config = {
    uploadId: state.uploadId,
    provider: state.provider,
    model: state.model,
    params: state.params,
    apiKey: state.apiKey,
    baseUrl: state.baseUrl,
  };
  const startTime = performance.now();
  try {
    const specs = await requestSpecs(config);
    setSpecs(specs);
    refreshSpecs();
    const processed = new Set();
    specs.forEach((spec) => {
      const sectionNumber = spec.section_number || spec.section;
      const key = sectionNumber ? String(sectionNumber) : null;
      if (key && !processed.has(key)) {
        processed.add(key);
        markHeaderProcessed(key);
      }
    });
    refreshHeaders();
    updateProgress(progressFill, 100);
    const duration = ((performance.now() - startTime) / 1000).toFixed(1);
    log(`Specifications extracted (${specs.length}) in ${duration}s.`);
  } catch (error) {
    log(`Specification extraction failed: ${error.message}`);
    updateProgress(progressFill, 80);
  }
}

async function handleExport() {
  if (!state.uploadId) {
    log("Upload a document before exporting.");
    return;
  }
  try {
    const blob = await exportSpecs(state.uploadId);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "specs.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    log("Specifications CSV downloaded.");
  } catch (error) {
    log(`Export failed: ${error.message}`);
  }
}

function handleFileSelection(file) {
  if (!file) return;
  const allowed = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"];
  if (!allowed.some((type) => file.type === type || file.name.endsWith(".pdf") || file.name.endsWith(".docx") || file.name.endsWith(".txt"))) {
    log("Unsupported file type. Please upload PDF, DOCX, or TXT.");
    return;
  }
  selectedFile = file;
  log(`Selected file: ${file.name}`);
}

function setupDragAndDrop() {
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });
  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  });
  dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      handleFileSelection(file);
    }
  });
}

function setupTabs() {
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      activeTab = tab.dataset.tab;
      setActiveTab(tabs, tabContents, activeTab);
      if (activeTab === "specs") {
        refreshSpecs();
      }
    });
  });
}

function setupSettingsForm() {
  const toNumber = (value, fallback) => {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  const syncProviderFields = (provider) => {
    document
      .querySelectorAll(".provider-group")
      .forEach((group) => group.classList.toggle("hidden", group.dataset.provider !== provider));
  };

  const readSettingsForm = () => {
    const formData = new FormData(settingsForm);
    const provider = (formData.get("provider") || "openrouter").toString();
    return {
      provider,
      model: (formData.get("model") || "").toString(),
      temperature: toNumber(formData.get("temperature"), 0.2),
      maxTokens: toNumber(formData.get("max_tokens"), MAX_TOKENS_LIMIT),
      apiKey: (formData.get("api_key") || "").toString(),
      baseUrl: (formData.get("base_url") || "").toString(),
    };
  };

  const toPayload = (settingsData) => ({
    provider: settingsData.provider,
    model: settingsData.model,
    temperature: settingsData.temperature,
    max_tokens: settingsData.maxTokens,
    api_key: settingsData.apiKey || null,
    base_url: settingsData.baseUrl || null,
  });

  const normalizeResponse = (response) => ({
    provider: (response.provider || "openrouter").toString(),
    model: (response.model || "").toString(),
    temperature: typeof response.temperature === "number" ? response.temperature : 0.2,
    maxTokens: typeof response.max_tokens === "number" ? response.max_tokens : MAX_TOKENS_LIMIT,
    apiKey: (response.api_key || "").toString(),
    baseUrl: (response.base_url || "").toString(),
  });

  const schedulePersist = (settingsData) => {
    if (!allowSettingsAutosave) return;
    if (settingsSaveTimer) clearTimeout(settingsSaveTimer);
    const payload = toPayload(settingsData);
    settingsSaveTimer = setTimeout(async () => {
      if (lastPersistedSettings && JSON.stringify(lastPersistedSettings) === JSON.stringify(payload)) {
        return;
      }
      try {
        const saved = await updateModelSettings(payload);
        lastPersistedSettings = toPayload(normalizeResponse(saved));
      } catch (error) {
        log(`Failed to save model settings: ${error.message}`);
      }
    }, 500);
  };

  const applySettingsToForm = (settingsData) => {
    allowSettingsAutosave = false;
    const provider = settingsData.provider || "openrouter";
    settingsForm
      .querySelectorAll('input[name="provider"]')
      .forEach((input) => {
        input.checked = input.value === provider;
      });
    settingsForm.querySelector('input[name="model"]').value = settingsData.model || "";
    settingsForm.querySelector('input[name="temperature"]').value = settingsData.temperature ?? 0.2;
    settingsForm.querySelector('input[name="max_tokens"]').value = settingsData.maxTokens ?? MAX_TOKENS_LIMIT;
    settingsForm.querySelector('input[name="api_key"]').value = settingsData.apiKey || "";
    settingsForm.querySelector('input[name="base_url"]').value = settingsData.baseUrl || "";
    syncProviderFields(provider);
    updateSettings(settingsData);
    allowSettingsAutosave = true;
  };

  const handleChange = (persist = true) => {
    const currentSettings = readSettingsForm();
    updateSettings(currentSettings);
    syncProviderFields(currentSettings.provider);
    if (persist) {
      schedulePersist(currentSettings);
    }
    return currentSettings;
  };

  settingsForm.addEventListener("input", () => {
    handleChange(true);
  });
  settingsForm.addEventListener("change", () => {
    handleChange(true);
  });
  settingsForm.addEventListener("submit", (event) => event.preventDefault());

  settingsForm.querySelector('input[name="max_tokens"]').value = MAX_TOKENS_LIMIT;

  const initialSettings = handleChange(false);
  lastPersistedSettings = toPayload(initialSettings);

  const loadPersistedSettings = async () => {
    try {
      const response = await fetchModelSettings();
      const persisted = normalizeResponse(response);
      applySettingsToForm(persisted);
      lastPersistedSettings = toPayload(persisted);
    } catch (error) {
      log(`Failed to load saved model settings: ${error.message}`);
    } finally {
      allowSettingsAutosave = true;
    }
  };

  loadPersistedSettings().catch(() => undefined);
}

function setupSearchControls() {
  specsSearch.addEventListener("input", refreshSpecs);
  sortSelect.addEventListener("change", refreshSpecs);
}

async function pollHealth() {
  try {
    const data = await checkHealth();
    updateHealthStatus(healthIndicator, healthLabel, data.status);
  } catch (error) {
    updateHealthStatus(healthIndicator, healthLabel, "error");
    log(`Health check failed: ${error.message}`);
  }
}

function initialize() {
  setupDragAndDrop();
  setupTabs();
  setupSettingsForm();
  setupSearchControls();
  toggleSettingsBtn.addEventListener("click", () => toggleSettings(settingsPanel));

  fileInput.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) handleFileSelection(file);
  });

  uploadButton.addEventListener("click", () => {
    handleUpload().catch(() => undefined);
  });

  findHeadersBtn.addEventListener("click", () => {
    handleHeaders().catch(() => undefined);
  });

  findSpecsBtn.addEventListener("click", () => {
    handleSpecs().catch(() => undefined);
  });

  exportCsvBtn.addEventListener("click", () => {
    handleExport().catch(() => undefined);
  });

  refreshHeaders();
  pollHealth();
  setInterval(pollHealth, 10000);
}

initialize();
