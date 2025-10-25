const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#file-input");
const browseButton = document.querySelector("#browse-button");
const uploadList = document.querySelector("#upload-progress");
const documentsStatus = document.querySelector("#documents-status");
const filesTableBody = document.querySelector("#files-table tbody");
const specsForm = document.querySelector("#specs-form");
const specsStatus = document.querySelector("#specs-status");
const specsTabs = document.querySelector("#specs-tabs");
const specsTablist = specsTabs?.querySelector(".specs-tablist") ?? null;
const specsPanels = specsTabs?.querySelector(".specs-panels") ?? null;
const DISCIPLINE_ORDER = [
  "mechanical",
  "electrical",
  "controls",
  "software",
  "project_management",
  "unknown",
];

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleString();
}

function createProgressItem(filename) {
  const item = document.createElement("li");
  item.className = "upload-item";

  const nameSpan = document.createElement("span");
  nameSpan.textContent = filename;
  nameSpan.className = "upload-name";

  const progress = document.createElement("progress");
  progress.max = 100;
  progress.value = 0;

  const statusSpan = document.createElement("span");
  statusSpan.className = "upload-status";
  statusSpan.textContent = "Starting...";

  item.append(nameSpan, progress, statusSpan);
  uploadList.prepend(item);

  return { item, progress, statusSpan };
}

function updateDocumentsTable(documents) {
  filesTableBody.innerHTML = "";
  if (!documents.length) {
    documentsStatus.textContent = "No files uploaded yet.";
    return;
  }

  documentsStatus.textContent = `Showing ${documents.length} document${documents.length > 1 ? "s" : ""}.`;

  for (const doc of documents) {
    const row = document.createElement("tr");
    if (typeof doc.id === "number") {
      row.dataset.documentId = String(doc.id);
      row.addEventListener("click", () => {
        const input = document.querySelector("#specs-document-id");
        if (input) {
          input.value = String(doc.id);
          input.focus();
        }
      });
    }

    const filenameCell = document.createElement("td");
    filenameCell.textContent = doc.filename;

    const statusCell = document.createElement("td");
    statusCell.textContent = doc.status;

    const uploadedCell = document.createElement("td");
    uploadedCell.textContent = formatDate(doc.uploaded_at);

    row.append(filenameCell, statusCell, uploadedCell);
    filesTableBody.append(row);
  }
}

async function fetchDocuments() {
  try {
    const response = await fetch("/api/files");
    if (!response.ok) {
      throw new Error(`Failed to fetch files (${response.status})`);
    }
    const documents = await response.json();
    updateDocumentsTable(documents);
  } catch (error) {
    console.error(error);
    documentsStatus.textContent = "Unable to fetch files.";
  }
}

function uploadFile(file) {
  const { progress, statusSpan } = createProgressItem(file.name);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        progress.value = Math.round((event.loaded / event.total) * 100);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        progress.value = 100;
        statusSpan.textContent = xhr.status === 201 ? "Uploaded" : "Already uploaded";
        resolve(xhr.response);
      } else {
        const detail = xhr.response?.detail || `Upload failed (${xhr.status})`;
        statusSpan.textContent = detail;
        progress.classList.add("upload-error");
        reject(new Error(detail));
      }
    };

    xhr.onerror = () => {
      statusSpan.textContent = "Network error";
      progress.classList.add("upload-error");
      reject(new Error("Network error"));
    };

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

async function handleFiles(files) {
  const pdfFiles = Array.from(files).filter((file) => file.type === "application/pdf" || file.name.endsWith(".pdf"));
  if (!pdfFiles.length) {
    window.alert("Only PDF files can be uploaded.");
    return;
  }

  for (const file of pdfFiles) {
    try {
      await uploadFile(file);
    } catch (error) {
      console.error(error);
    }
  }

  await fetchDocuments();
}

function preventDefaults(event) {
  event.preventDefault();
  event.stopPropagation();
}

function normaliseDisciplineName(value) {
  if (!value) {
    return "Unknown";
  }
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function renderSpecs(buckets, documentId) {
  if (!specsTabs || !specsTablist || !specsPanels) {
    return;
  }

  specsTablist.innerHTML = "";
  specsPanels.innerHTML = "";

  const entries = Object.entries(buckets ?? {}).sort((a, b) => {
    const indexA = DISCIPLINE_ORDER.indexOf(a[0]);
    const indexB = DISCIPLINE_ORDER.indexOf(b[0]);
    const safeA = indexA === -1 ? DISCIPLINE_ORDER.length : indexA;
    const safeB = indexB === -1 ? DISCIPLINE_ORDER.length : indexB;
    if (safeA === safeB) {
      return a[0].localeCompare(b[0]);
    }
    return safeA - safeB;
  });

  if (!entries.length) {
    specsTabs.hidden = true;
    return;
  }

  entries.forEach(([discipline, lines], index) => {
    const tabId = `spec-tab-${discipline}`;
    const panelId = `spec-panel-${discipline}`;

    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "specs-tab";
    tab.id = tabId;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panelId);
    tab.dataset.discipline = discipline;
    tab.textContent = `${normaliseDisciplineName(discipline)} (${lines.length})`;
    tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
    tab.tabIndex = index === 0 ? 0 : -1;
    tab.addEventListener("click", () => {
      activateSpecsTab(discipline);
    });
    specsTablist.append(tab);

    const panel = document.createElement("section");
    panel.id = panelId;
    panel.className = "specs-panel";
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", tabId);
    panel.hidden = index !== 0;
    panel.append(createBucketToolbar(discipline, lines, documentId));
    panel.append(createSpecList(lines));
    specsPanels.append(panel);
  });

  specsTabs.hidden = false;
  activateSpecsTab(entries[0][0]);
}

function activateSpecsTab(discipline, options = {}) {
  const { focusTab = false } = options;
  if (!specsTablist || !specsPanels) {
    return;
  }

  const tabs = Array.from(specsTablist.querySelectorAll('[role="tab"]'));
  const panels = Array.from(specsPanels.querySelectorAll('[role="tabpanel"]'));
  const activePanelId = `spec-panel-${discipline}`;

  for (const tab of tabs) {
    const isActive = tab.dataset.discipline === discipline;
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
    tab.tabIndex = isActive ? 0 : -1;
    if (isActive && focusTab) {
      tab.focus({ preventScroll: true });
    }
  }

  for (const panel of panels) {
    panel.hidden = panel.id !== activePanelId;
  }
}

function createBucketToolbar(discipline, lines, documentId) {
  const toolbar = document.createElement("div");
  toolbar.className = "specs-panel-toolbar";

  const count = document.createElement("span");
  count.className = "specs-meta";
  count.textContent = `${lines.length} line${lines.length === 1 ? "" : "s"}`;

  const downloadButton = document.createElement("button");
  downloadButton.type = "button";
  downloadButton.className = "specs-download";
  downloadButton.textContent = "Download JSON";
  downloadButton.addEventListener("click", () => {
    downloadBucket(discipline, lines, documentId);
  });

  toolbar.append(count, downloadButton);
  return toolbar;
}

function createSpecList(lines) {
  const list = document.createElement("ul");
  list.className = "specs-list";

  if (!Array.isArray(lines) || !lines.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "specs-meta";
    emptyItem.textContent = "No specification lines available.";
    list.append(emptyItem);
    return list;
  }

  for (const line of lines) {
    const item = document.createElement("li");

    const text = document.createElement("p");
    text.className = "specs-text";
    text.textContent = line.text;
    item.append(text);

    const header = document.createElement("p");
    header.className = "specs-meta";
    const headerPath = Array.isArray(line.header_path) && line.header_path.length
      ? line.header_path.join(" › ")
      : "(none)";
    header.textContent = `Header: ${headerPath}`;
    item.append(header);

    const details = document.createElement("p");
    details.className = "specs-meta";
    const pageNumber = typeof line.page === "number" ? line.page + 1 : "—";
    details.textContent = `Page ${pageNumber} · Source: ${line.source ?? "rule"}`;
    item.append(details);

    list.append(item);
  }

  return list;
}

function downloadBucket(discipline, lines, documentId) {
  const payload = {
    document_id: documentId,
    discipline,
    generated_at: new Date().toISOString(),
    count: Array.isArray(lines) ? lines.length : 0,
    lines,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `specs-${documentId}-${discipline}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function loadSpecs(documentId) {
  if (!specsStatus) {
    return;
  }

  specsStatus.textContent = `Loading specifications for document ${documentId}...`;
  if (specsTabs) {
    specsTabs.hidden = true;
  }

  try {
    const response = await fetch(`/api/specs/extract/${documentId}`, { method: "POST" });
    if (!response.ok) {
      let detail;
      try {
        detail = (await response.json()).detail;
      } catch (error) {
        detail = undefined;
      }
      if (response.status === 404) {
        throw new Error(detail || "Document not found.");
      }
      throw new Error(detail || `Failed to load specifications (${response.status})`);
    }

    const payload = await response.json();
    renderSpecs(payload.buckets ?? {}, documentId);
    const bucketValues = Object.values(payload.buckets ?? {});
    const bucketCount = bucketValues.length;
    const totalLines = bucketValues.reduce((total, bucket) => total + bucket.length, 0);
    specsStatus.textContent = totalLines
      ? `Loaded ${totalLines} line${totalLines === 1 ? "" : "s"} across ${bucketCount} bucket${
          bucketCount === 1 ? "" : "s"
        }.`
      : "No specification lines were found.";
  } catch (error) {
    console.error(error);
    specsStatus.textContent = error instanceof Error ? error.message : "Unable to load specifications.";
  }
}

specsForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(specsForm);
  const documentIdRaw = formData.get("documentId");
  const documentId = Number(documentIdRaw);
  if (!Number.isFinite(documentId) || documentId <= 0) {
    if (specsStatus) {
      specsStatus.textContent = "Enter a valid document ID.";
    }
    return;
  }
  void loadSpecs(documentId);
});

specsTablist?.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
    return;
  }

  const tabs = Array.from(specsTablist.querySelectorAll('[role="tab"]'));
  if (!tabs.length) {
    return;
  }

  const currentIndex = tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
  if (currentIndex === -1) {
    return;
  }

  event.preventDefault();
  const delta = event.key === "ArrowRight" ? 1 : -1;
  const nextIndex = (currentIndex + delta + tabs.length) % tabs.length;
  const nextDiscipline = tabs[nextIndex]?.dataset.discipline;
  if (nextDiscipline) {
    activateSpecsTab(nextDiscipline, { focusTab: true });
  }
});

if (dropZone) {
  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, preventDefaults, false);
  });

  dropZone.addEventListener("dragover", () => {
    dropZone.classList.add("is-dragging");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("is-dragging");
  });

  dropZone.addEventListener("drop", (event) => {
    dropZone.classList.remove("is-dragging");
    const files = event.dataTransfer?.files;
    if (files?.length) {
      void handleFiles(files);
    }
  });

  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput?.click();
    }
  });
}

browseButton?.addEventListener("click", () => {
  fileInput?.click();
});

fileInput?.addEventListener("change", (event) => {
  const target = event.target;
  if (target.files?.length) {
    void handleFiles(target.files);
    target.value = "";
  }
});

void fetchDocuments();
