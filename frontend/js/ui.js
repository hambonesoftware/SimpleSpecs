function buildTree(headers) {
  const root = {};
  headers.forEach((header) => {
    const parts = header.section_number.split(".");
    let node = root;
    parts.forEach((part, index) => {
      node.children = node.children || new Map();
      if (!node.children.has(part)) {
        node.children.set(part, { children: new Map() });
      }
      node = node.children.get(part);
      if (index === parts.length - 1) {
        node.header = header;
      }
    });
  });
  return root;
}

function createHeaderButton(header, { activeSection, headerProgress, onSelect } = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "header-node";
  if (activeSection === header.section_number) {
    button.classList.add("active");
  }

  const status = document.createElement("span");
  status.className = "header-status";
  const key = header?.section_number ? String(header.section_number) : null;
  const progress = key ? headerProgress?.get(key) : null;
  if (progress?.requested) {
    status.classList.add("header-status--requested");
    status.textContent = progress.completed ? "✓✓" : "✓";
  }
  if (progress?.completed) {
    status.classList.add("header-status--complete");
  }
  button.appendChild(status);

  const details = document.createElement("div");
  details.className = "header-details";

  const title = document.createElement("span");
  title.className = "header-label";
  title.textContent = `${header.section_number} ${header.section_name}`;
  details.appendChild(title);

  const locationParts = [];
  if (header.page_number != null) {
    locationParts.push(`Page ${header.page_number}`);
  }
  if (header.line_number != null) {
    locationParts.push(`Line ${header.line_number}`);
  }
  if (locationParts.length > 0) {
    const meta = document.createElement("span");
    meta.className = "header-meta";
    meta.textContent = locationParts.join(" • ");
    details.appendChild(meta);
  }

  button.appendChild(details);

  button.addEventListener("click", () => onSelect?.(header));
  return button;
}

function renderTreeNode(node, activeSection, headerProgress, onSelect) {
  if (!node.children) return document.createDocumentFragment();
  const ul = document.createElement("ul");
  const entries = Array.from(node.children.entries()).sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }));
  entries.forEach(([, child]) => {
    const li = document.createElement("li");
    if (child.header) {
      const button = createHeaderButton(child.header, { activeSection, headerProgress, onSelect });
      li.appendChild(button);
    }
    if (child.children && child.children.size > 0) {
      li.appendChild(renderTreeNode(child, activeSection, headerProgress, onSelect));
    }
    ul.appendChild(li);
  });
  return ul;
}

export function renderHeadersTree(container, headers, { onSelect, activeSection, headerProgress } = {}) {
  container.innerHTML = "";
  if (!headers?.length) {
    container.textContent = "No headers extracted yet.";
    return;
  }
  const tree = buildTree(headers);
  const fragment = renderTreeNode(tree, activeSection, headerProgress, onSelect);
  container.appendChild(fragment);
}

export function renderSidebarHeadersList(container, headers, { onSelect, activeSection, headerProgress } = {}) {
  container.innerHTML = "";
  if (!headers?.length) {
    container.textContent = "No headers extracted yet.";
    return;
  }

  const list = document.createElement("ul");
  list.className = "headers-list";

  headers
    .slice()
    .sort((a, b) => a.section_number.localeCompare(b.section_number, undefined, { numeric: true }))
    .forEach((header) => {
      const item = document.createElement("li");
      const button = createHeaderButton(header, { activeSection, headerProgress, onSelect });
      item.appendChild(button);
      list.appendChild(item);
    });

  container.appendChild(list);
}

export function updateSectionPreview(element, preview) {
  element.innerHTML = "";

  if (!preview) {
    const placeholder = document.createElement("p");
    placeholder.className = "section-preview-placeholder";
    placeholder.textContent = "Select a header to preview text.";
    element.appendChild(placeholder);
    return;
  }

  if (typeof preview === "string") {
    const placeholder = document.createElement("p");
    placeholder.className = "section-preview-placeholder";
    placeholder.textContent = preview;
    element.appendChild(placeholder);
    return;
  }

  const { header, text } = preview;
  if (!header) {
    updateSectionPreview(element, text || "Select a header to preview text.");
    return;
  }

  const title = document.createElement("p");
  title.className = "section-preview-title";
  title.textContent = `${header.section_number} ${header.section_name}`;
  element.appendChild(title);

  const metaParts = [];
  if (header.page_number != null) {
    metaParts.push(`Page ${header.page_number}`);
  }
  if (header.line_number != null) {
    metaParts.push(`Line ${header.line_number}`);
  }
  if (metaParts.length > 0) {
    const meta = document.createElement("p");
    meta.className = "section-preview-meta";
    meta.textContent = metaParts.join(" • ");
    element.appendChild(meta);
  }

  const pre = document.createElement("pre");
  pre.className = "section-preview-text";
  pre.textContent = text || "No preview available.";
  element.appendChild(pre);
}

function normalize(value) {
  return value.toLowerCase();
}

function resolveSectionNumber(row) {
  return row.section_number ?? row.section ?? row.sectionNumber ?? "";
}

function resolveSectionName(row) {
  return row.section_name ?? row.section_title ?? row.sectionName ?? "";
}

function resolveSpecification(row) {
  return row.specification ?? row.spec_text ?? row.text ?? "";
}

function resolveDomain(row) {
  return row.domain ?? row.category ?? row.group ?? "";
}

function buildRenderableSpecs(specs) {
  if (!Array.isArray(specs)) return [];
  return specs.map((row) => ({
    section_number: resolveSectionNumber(row),
    section_name: resolveSectionName(row),
    specification: resolveSpecification(row),
    domain: resolveDomain(row),
  }));
}

export function renderSpecsTable(tableBody, specs, { searchTerm = "", sortKey = "section_number" } = {}) {
  tableBody.innerHTML = "";
  const rows = buildRenderableSpecs(specs);
  let filtered = rows;
  if (searchTerm) {
    const term = searchTerm.toLowerCase();
    filtered = rows.filter((row) =>
      [row.section_number, row.section_name, row.specification, row.domain]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }
  filtered.sort((a, b) => {
    const left = normalize(String(a[sortKey] || ""));
    const right = normalize(String(b[sortKey] || ""));
    return left.localeCompare(right, undefined, { numeric: true });
  });

  const fragment = document.createDocumentFragment();
  filtered.forEach((row) => {
    const tr = document.createElement("tr");
    [row.section_number, row.section_name, row.specification, row.domain || "—"].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value || "";
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  if (!fragment.childNodes.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = "No specifications found.";
    tr.appendChild(td);
    fragment.appendChild(tr);
  }
  tableBody.appendChild(fragment);
}

export function setActiveTab(tabs, contents, active) {
  tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === active);
  });
  contents.forEach((section) => {
    section.classList.toggle("hidden", section.id !== `tab-${active}`);
  });
}

export function updateHealthStatus(indicator, label, status) {
  indicator.classList.remove("status-online", "status-offline", "status-warning");
  if (status === "ok") {
    indicator.classList.add("status-online");
    label.textContent = "Healthy";
  } else if (status === "degraded") {
    indicator.classList.add("status-warning");
    label.textContent = "Degraded";
  } else {
    indicator.classList.add("status-offline");
    label.textContent = "Offline";
  }
}

export function updateProgress(fill, percent) {
  fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
}

export function appendLog(consoleEl, message) {
  const timestamp = new Date().toLocaleTimeString();
  consoleEl.textContent += `[${timestamp}] ${message}\n`;
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

export function toggleSettings(panel) {
  panel.classList.toggle("hidden");
}
