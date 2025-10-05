import {
  checkHealth,
  ingestFile,
  fetchParsedObjects,
  fetchModelSettings,
  requestHeaders,
  exportSpecs,
  updateModelSettings,
  streamSpecs,
  fetchSystemCapabilities,
} from "./api.js";
import {
  state,
  setUpload,
  setHeaders,
  setSpecs,
  setSectionText,
  updateSettings,
  addLog,
  resetLogs,
  resetHeaderProgress,
  markHeaderRequested,
  markHeaderResponded,
  markHeaderProcessed,
  setEngine,
  getEngine,
  ENGINE_OPTIONS,
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
const engineToggle = document.getElementById("engine-toggle");
const engineButtons = engineToggle ? Array.from(engineToggle.querySelectorAll("[data-engine]")) : [];

const ENGINE_STORAGE_KEY = "simplespecs.pdf_engine";
const ENGINE_SET = new Set(ENGINE_OPTIONS);

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

function getHeaderProgress() {
  if (!state.headerProgress) {
    return new Map();
  }
  return new Map(state.headerProgress);
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
  const headerProgress = getHeaderProgress();
  if (!state.headers?.length) {
    activeSection = null;
  }

  renderHeadersTree(headersTreeEl, state.headers, {
    activeSection,
    headerProgress,
    onSelect: (header) => selectHeader(header),
  });

  renderSidebarHeadersList(sidebarHeadersEl, state.headers, {
    activeSection,
    headerProgress,
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

function normalizeEngine(engine) {
  if (typeof engine !== "string") {
    return null;
  }
  const normalized = engine.toLowerCase();
  return ENGINE_SET.has(normalized) ? normalized : null;
}

function readPersistedEngine() {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const stored = window.localStorage.getItem(ENGINE_STORAGE_KEY);
    return normalizeEngine(stored);
  } catch (error) {
    console.warn("Unable to read stored engine selection:", error);
    return null;
  }
}

function persistEngineSelection(engine) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(ENGINE_STORAGE_KEY, engine);
  } catch (error) {
    console.warn("Unable to persist engine selection:", error);
  }
}

function setupEngineToggle() {
  if (!engineToggle || engineButtons.length === 0) {
    return;
  }

  const updateButtons = (engine) => {
    engineButtons.forEach((button) => {
      const isActive = button.dataset.engine === engine;
      button.classList.toggle("active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  };

  const applyEngine = (engine, { persist = false } = {}) => {
    const normalized = normalizeEngine(engine);
    if (!normalized) {
      updateButtons(getEngine());
      return getEngine();
    }
    const current = setEngine(normalized);
    updateButtons(current);
    if (persist) {
      persistEngineSelection(current);
    }
    return current;
  };

  engineButtons.forEach((button) => {
    button.addEventListener("click", () => {
      applyEngine(button.dataset.engine, { persist: true });
    });
  });

  const stored = readPersistedEngine();
  if (stored) {
    applyEngine(stored);
    return;
  }

  updateButtons(getEngine());

  (async () => {
    try {
      const capabilities = await fetchSystemCapabilities();
      const backendEngine = normalizeEngine(capabilities?.pdf_engine);
      if (backendEngine) {
        applyEngine(backendEngine);
      }
    } catch (error) {
      console.warn("Failed to load default engine from backend:", error);
    }
  })();
}

async function handleUpload() {
  if (!selectedFile) {
    log("Please select a file before uploading.");
    return;
  }
  clearLog();
  const engine = getEngine();
  log(`Uploading ${selectedFile.name} with the ${engine} engine…`);
  updateProgress(progressFill, 10);
  try {
    const response = await ingestFile(selectedFile, engine);
    const fileId = response.file_id || response.upload_id;
    const status = response.status || "processed";
    const reportedCount = Number.isFinite(Number(response.object_count))
      ? Number(response.object_count)
      : 0;
    if (!fileId) {
      throw new Error("Upload response missing file identifier.");
    }
    updateProgress(progressFill, 25);
    if (status !== "processed") {
      log(`Ingest status: ${status}. Fetching parsed objects…`);
    }
    const fetchedObjects = await fetchParsedObjects(fileId);
    const objects = Array.isArray(fetchedObjects) ? fetchedObjects : [];
    setUpload({ uploadId: fileId, objects });
    const parsedCount = objects.length || reportedCount;
    log(`Parsed ${parsedCount} objects (file ${fileId}).`);
    reportedInvalidHeaderMatches.clear();
    refreshHeaders();
    updateProgress(progressFill, 40);
    log("Document ready. Proceed with header extraction.");
    updateProgress(progressFill, 50);
  } catch (error) {
    const detail = error?.detail;
    const detailMessage = typeof detail === "string" ? detail : detail?.message;
    const message = detailMessage || error.message;
    log(`Upload failed: ${message}`);
    if (detail && typeof detail === "object" && detail.error === "mineru_not_available") {
      log("Switch to the native engine or install MinerU to continue.");
    }
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
  resetHeaderProgress();
  refreshHeaders();
  log("Requesting specifications from LLM…");
  updateProgress(progressFill, 80);
  const totalHeaders = state.headers.length;
  const processedSections = new Set();
  const respondedSections = new Set();
  const requestedSections = new Set();
  const collectedSpecs = [];
  setSpecs([]);
  refreshSpecs();
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
    for await (const event of streamSpecs(config)) {
      const eventType = event?.event;
      const sectionNumber = event?.section_number ?? event?.section ?? event?.sectionNumber;
      const key = sectionNumber != null ? String(sectionNumber) : null;

      if (eventType === "request" && key && !requestedSections.has(key)) {
        requestedSections.add(key);
        markHeaderRequested(key);
        refreshHeaders();
        continue;
      }

      if (eventType === "response" && key && !respondedSections.has(key)) {
        respondedSections.add(key);
        markHeaderResponded(key);
        refreshHeaders();
        continue;
      }

      if (eventType === "processed" && key && !processedSections.has(key)) {
        const specsForSection = Array.isArray(event?.specs) ? event.specs : [];
        if (specsForSection.length > 0) {
          collectedSpecs.push(...specsForSection);
          setSpecs([...collectedSpecs]);
          refreshSpecs();
        }
        processedSections.add(key);
        markHeaderProcessed(key);
        refreshHeaders();
        if (totalHeaders > 0) {
          const progress = 80 + Math.round((processedSections.size / totalHeaders) * 20);
          updateProgress(progressFill, Math.min(progress, 99));
        }
        continue;
      }

      if (eventType === "complete") {
        const finalSpecs = Array.isArray(event?.specs) ? event.specs : collectedSpecs;
        if (finalSpecs !== state.specs) {
          setSpecs(finalSpecs);
          refreshSpecs();
        }
        const duration = ((performance.now() - startTime) / 1000).toFixed(1);
        updateProgress(progressFill, 100);
        log(`Specifications extracted (${finalSpecs.length}) in ${duration}s.`);
        break;
      }

      if (eventType === "error") {
        const status = event?.status ? ` (status ${event.status})` : "";
        const message = event?.message || "Specification extraction failed.";
        throw new Error(`${message}${status}`);
      }
    }

    if (processedSections.size < totalHeaders) {
      const remaining = (state.headers || [])
        .map((header) => header?.section_number)
        .filter((section) => section != null)
        .map((section) => String(section))
        .filter((section) => !processedSections.has(section));
      remaining.forEach((section) => {
        processedSections.add(section);
        markHeaderProcessed(section);
      });
      refreshHeaders();
    }

    if (!state.specs?.length && collectedSpecs.length > 0) {
      setSpecs([...collectedSpecs]);
      refreshSpecs();
    }

    if (processedSections.size >= totalHeaders) {
      updateProgress(progressFill, 100);
    }
  } catch (error) {
    log(`Specification extraction failed: ${error.message}`);
    updateProgress(progressFill, 65);
    throw error;
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

function setupSpecsControls() {
  specsSearch.addEventListener("input", refreshSpecs);
  sortSelect.addEventListener("change", refreshSpecs);
  setupEngineToggle();
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
  setupSpecsControls();
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
