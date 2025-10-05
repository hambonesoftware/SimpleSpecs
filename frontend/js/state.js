import { MAX_TOKENS_LIMIT } from "./constants.js";

export const ENGINE_OPTIONS = ["auto", "native", "mineru"];
const ENGINE_SET = new Set(ENGINE_OPTIONS);

const DEFAULT_HEADER_PROGRESS = {
  requested: false,
  responded: false,
  completed: false,
};

export const state = {
  uploadId: null,
  objects: [],
  headers: [],
  specs: [],
  sectionTexts: new Map(),
  headerProgress: new Map(),
  provider: "openrouter",
  model: "",
  engine: ENGINE_OPTIONS[0],
  params: {
    temperature: 0.2,
    max_tokens: MAX_TOKENS_LIMIT,
  },
  apiKey: "",
  baseUrl: "",
  logs: [],
};

export function setUpload({ uploadId, objectCount, objects }) {
  state.uploadId = uploadId;
  state.objects = objects || [];
  state.headers = [];
  state.specs = [];
  state.sectionTexts = new Map();
  state.headerProgress = new Map();
}

export function resetHeaderProgress() {
  state.headerProgress = new Map();
  (state.headers || []).forEach((header) => {
    if (header?.section_number != null) {
      const key = String(header.section_number);
      state.headerProgress.set(key, { ...DEFAULT_HEADER_PROGRESS });
    }
  });
}

export function setObjects(objects) {
  state.objects = objects;
}

export function setHeaders(headers) {
  state.headers = headers;
  resetHeaderProgress();
}

export function setSpecs(specs) {
  state.specs = specs;
}

function ensureHeaderProgress(sectionNumber) {
  if (!sectionNumber) return null;
  if (!state.headerProgress) {
    state.headerProgress = new Map();
  }
  const key = String(sectionNumber);
  const current = state.headerProgress.get(key);
  if (current) {
    const normalized = { ...DEFAULT_HEADER_PROGRESS, ...current };
    state.headerProgress.set(key, normalized);
    return { key, current: normalized };
  }
  const initial = { ...DEFAULT_HEADER_PROGRESS };
  state.headerProgress.set(key, initial);
  return { key, current: initial };
}

export function markHeaderRequested(sectionNumber) {
  const result = ensureHeaderProgress(sectionNumber);
  if (!result) return;
  const { key, current } = result;
  state.headerProgress.set(key, { ...current, requested: true });
}

export function markHeaderResponded(sectionNumber) {
  const result = ensureHeaderProgress(sectionNumber);
  if (!result) return;
  const { key, current } = result;
  state.headerProgress.set(key, { ...current, requested: true, responded: true });
}

export function markHeaderProcessed(sectionNumber) {
  if (!sectionNumber) return;
  const result = ensureHeaderProgress(sectionNumber);
  if (!result) return;
  const { key, current } = result;
  state.headerProgress.set(key, { ...current, requested: true, responded: true, completed: true });
}

export function setSectionText(sectionNumber, text) {
  state.sectionTexts.set(sectionNumber, text);
}

export function updateSettings({ provider, model, temperature, maxTokens, apiKey, baseUrl }) {
  state.provider = provider;
  state.model = model;
  state.params = {
    ...state.params,
    temperature,
    max_tokens: maxTokens,
  };
  state.apiKey = apiKey;
  state.baseUrl = baseUrl;
}

export function setEngine(engine) {
  if (typeof engine !== "string") {
    return state.engine;
  }
  const normalized = engine.toLowerCase();
  if (!ENGINE_SET.has(normalized)) {
    return state.engine;
  }
  state.engine = normalized;
  return state.engine;
}

export function getEngine() {
  return state.engine;
}

export function addLog(entry) {
  state.logs.push(entry);
  if (state.logs.length > 200) {
    state.logs.splice(0, state.logs.length - 200);
  }
}

export function resetLogs() {
  state.logs = [];
}
