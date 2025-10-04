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

function createHeaderButton(header, { activeSection, processedSections, onSelect } = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "header-node";
  if (activeSection === header.section_number) {
    button.classList.add("active");
  }

  const status = document.createElement("span");
  status.className = "header-status";
  const key = header?.section_number ? String(header.section_number) : null;
  if (key && processedSections?.has(key)) {
    status.classList.add("header-status--complete");
    status.textContent = "✓";
  }
  button.appendChild(status);

  const label = document.createElement("span");
  label.className = "header-label";
  label.textContent = `${header.section_number} ${header.section_name}`;
  button.appendChild(label);

  button.addEventListener("click", () => onSelect?.(header));
  return button;
}

function renderTreeNode(node, activeSection, processedSections, onSelect) {
  if (!node.children) return document.createDocumentFragment();
  const ul = document.createElement("ul");
  const entries = Array.from(node.children.entries()).sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }));
  entries.forEach(([, child]) => {
    const li = document.createElement("li");
    if (child.header) {
      const button = createHeaderButton(child.header, { activeSection, processedSections, onSelect });
      li.appendChild(button);
    }
    if (child.children && child.children.size > 0) {
      li.appendChild(renderTreeNode(child, activeSection, processedSections, onSelect));
    }
    ul.appendChild(li);
  });
  return ul;
}

export function renderHeadersTree(container, headers, { onSelect, activeSection, processedSections } = {}) {
  container.innerHTML = "";
  if (!headers?.length) {
    container.textContent = "No headers extracted yet.";
    return;
  }
  const tree = buildTree(headers);
  const fragment = renderTreeNode(tree, activeSection, processedSections, onSelect);
  container.appendChild(fragment);
}

export function renderSidebarHeadersList(container, headers, { onSelect, activeSection, processedSections } = {}) {
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
      const button = createHeaderButton(header, { activeSection, processedSections, onSelect });
      item.appendChild(button);
      list.appendChild(item);
    });

  container.appendChild(list);
}

export function updateSectionPreview(element, text) {
  element.textContent = text || "No preview available.";
}

function normalize(value) {
  return value.toLowerCase();
}

export function renderSpecsTable(tableBody, specs, { searchTerm = "", sortKey = "section_number" } = {}) {
  tableBody.innerHTML = "";
  let rows = Array.isArray(specs) ? [...specs] : [];
  if (searchTerm) {
    const term = searchTerm.toLowerCase();
    rows = rows.filter((row) =>
      [row.section_number, row.section_name, row.specification, row.domain]
        .join(" ")
        .toLowerCase()
        .includes(term),
    );
  }
  rows.sort((a, b) => {
    const left = normalize(String(a[sortKey] || ""));
    const right = normalize(String(b[sortKey] || ""));
    return left.localeCompare(right, undefined, { numeric: true });
  });

  const fragment = document.createDocumentFragment();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    [row.section_number, row.section_name, row.specification, row.domain].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
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
