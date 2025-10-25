const dropZone = document.querySelector("#drop-zone");
const fileInput = document.querySelector("#file-input");
const browseButton = document.querySelector("#browse-button");
const uploadList = document.querySelector("#upload-progress");
const documentsStatus = document.querySelector("#documents-status");
const filesTableBody = document.querySelector("#files-table tbody");

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
