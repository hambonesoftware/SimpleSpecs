import { MAX_TOKENS_LIMIT } from "./constants.js";

export const state = {
  uploadId: null,
  objects: [],
  headers: [],
  specs: [],
  sectionTexts: new Map(),
  headerProgress: new Map(),
  provider: "openrouter",
  model: "",
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

export function setObjects(objects) {
  state.objects = objects;
}

export function setHeaders(headers) {
  state.headers = headers;
  state.headerProgress = new Map();
  headers.forEach((header) => {
    if (header?.section_number) {
      const key = String(header.section_number);
      state.headerProgress.set(key, false);
    }
  });
}

export function setSpecs(specs) {
  state.specs = specs;
}

export function markHeaderProcessed(sectionNumber) {
  if (!sectionNumber) return;
  if (!state.headerProgress) {
    state.headerProgress = new Map();
  }
  const key = String(sectionNumber);
  state.headerProgress.set(key, true);
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

export function addLog(entry) {
  state.logs.push(entry);
  if (state.logs.length > 200) {
    state.logs.splice(0, state.logs.length - 200);
  }
}

export function resetLogs() {
  state.logs = [];
}
