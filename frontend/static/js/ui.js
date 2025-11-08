const DISCIPLINE_ORDER = [
  'mechanical',
  'electrical',
  'controls',
  'software',
  'project_management',
  'unknown',
];

const AGENT_CODES = ['Mechanical', 'Electrical', 'Controls', 'Software', 'ProjectManagement'];

export function initDropZone({ zone, input, browseButton, onFiles }) {
  if (!zone) return;

  const handleFiles = (fileList) => {
    const files = Array.from(fileList ?? []).filter((file) =>
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'),
    );
    if (!files.length) {
      showToast('Select at least one PDF file.', 'error');
      return;
    }
    onFiles?.(files);
  };

  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  });

  zone.addEventListener('dragover', () => zone.classList.add('is-dragging'));
  zone.addEventListener('dragleave', () => zone.classList.remove('is-dragging'));
  zone.addEventListener('drop', (event) => {
    zone.classList.remove('is-dragging');
    const files = event.dataTransfer?.files;
    if (files?.length) {
      handleFiles(files);
    }
  });

  zone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      input?.click();
    }
  });

  browseButton?.addEventListener('click', () => input?.click());
  input?.addEventListener('change', (event) => {
    const files = event.target?.files;
    if (files?.length) {
      handleFiles(files);
      event.target.value = '';
    }
  });
}

export function createUploadTracker(list, filename) {
  const item = document.createElement('li');
  const name = document.createElement('span');
  name.textContent = filename;
  name.style.flex = '1 1 auto';
  const progress = document.createElement('progress');
  progress.max = 100;
  progress.value = 0;
  const status = document.createElement('span');
  status.textContent = 'Starting…';

  item.append(name, progress, status);
  list?.prepend(item);

  return {
    updateProgress(value) {
      progress.value = value;
    },
    markComplete(text = 'Uploaded') {
      progress.value = 100;
      status.textContent = text;
    },
    markError(message) {
      progress.classList.add('upload-error');
      status.textContent = message;
    },
  };
}

export function renderDocumentList(container, documents, selectedId) {
  if (!container) return;
  container.innerHTML = '';

  if (!Array.isArray(documents) || !documents.length) {
    container.dataset.empty = 'true';
    return;
  }

  container.dataset.empty = 'false';

  documents.forEach((doc) => {
    const option = document.createElement('div');
    option.className = 'document-item';
    option.id = `document-${doc.id}`;
    option.setAttribute('role', 'option');
    option.tabIndex = -1;
    option.dataset.documentId = String(doc.id);
    if (doc.id === selectedId) {
      option.setAttribute('aria-selected', 'true');
      option.tabIndex = 0;
    } else {
      option.setAttribute('aria-selected', 'false');
    }

    const name = document.createElement('p');
    name.className = 'document-item__name';
    name.textContent = doc.filename;

    const meta = document.createElement('div');
    meta.className = 'document-item__meta';
    const status = document.createElement('span');
    status.textContent = doc.status ?? 'uploaded';
    const uploaded = document.createElement('span');
    uploaded.textContent = formatDate(doc.uploaded_at);
    meta.append(status, uploaded);

    option.append(name, meta);
    container.append(option);
  });
}

export function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString();
}

export function setDocumentMeta(container, documentRecord) {
  if (!container) return;
  if (!documentRecord) {
    container.innerHTML = '<p class="panel-status">No document selected.</p>';
    return;
  }

  container.innerHTML = '';
  const id = document.createElement('span');
  id.textContent = `ID: ${documentRecord.id}`;
  const status = document.createElement('span');
  status.textContent = `Status: ${documentRecord.status}`;
  const uploaded = document.createElement('span');
  uploaded.textContent = `Uploaded: ${formatDate(documentRecord.uploaded_at)}`;
  container.append(id, status, uploaded);
}

export function setPanelLoading(container, message = 'Loading…') {
  if (!container) return;
  container.innerHTML = `<p class="panel-status">${message}</p>`;
}

export function setPanelError(container, message) {
  if (!container) return;
  container.innerHTML = `<p class="panel-error">${message}</p>`;
}

export function renderParseSummary(container, payload) {
  if (!container) return;
  if (!payload) {
    setPanelError(container, 'Parse data unavailable.');
    return;
  }

  const pages = Array.isArray(payload.pages) ? payload.pages : [];
  const totalBlocks = pages.reduce((acc, page) => acc + (page.blocks?.length ?? 0), 0);
  const totalTables = pages.reduce((acc, page) => acc + (page.tables?.length ?? 0), 0);

  const stats = [
    { label: 'Pages', value: pages.length },
    { label: 'Text blocks', value: totalBlocks },
    { label: 'Tables', value: totalTables },
    { label: 'OCR used', value: payload.has_ocr ? 'Yes' : 'No' },
    { label: 'MinerU fallback', value: payload.used_mineru ? 'Yes' : 'No' },
  ];

  const grid = document.createElement('div');
  grid.className = 'parse-grid';
  stats.forEach((stat) => {
    const card = document.createElement('div');
    card.className = 'parse-stat';
    const title = document.createElement('strong');
    title.textContent = stat.label;
    const value = document.createElement('span');
    value.textContent = String(stat.value);
    card.append(title, value);
    grid.append(card);
  });

  container.innerHTML = '';
  container.append(grid);
}

// ⬇️ Drop-in replacement
export function renderHeaderRawResponse(container, payload) {
  if (!container) return;

  let rawParts = [];
  let fencedParts = [];
  let fallbackText = '';

  if (typeof payload === 'string') {
    fallbackText = payload;
  } else if (payload && typeof payload === 'object') {
    if (Array.isArray(payload.llm_raw_responses)) {
      rawParts = payload.llm_raw_responses
        .map((part) => String(part ?? ''))
        .filter((part) => part.trim().length);
    }
    if (Array.isArray(payload.llm_fenced_blocks)) {
      fencedParts = payload.llm_fenced_blocks
        .map((part) => String(part ?? ''))
        .filter((part) => part.trim().length);
    }
    if (payload.fenced_text != null) {
      fallbackText = String(payload.fenced_text);
    }
  } else {
    fallbackText = '';
  }

  container.innerHTML = '';

  if (rawParts.length) {
    rawParts.forEach((part, index) => {
      const details = document.createElement('details');
      details.className = 'raw-response__details';
      if (index === 0) details.open = true;
      const summary = document.createElement('summary');
      summary.textContent =
        rawParts.length === 1 ? 'LLM raw response' : `LLM raw response (part ${index + 1})`;
      const pre = document.createElement('pre');
      pre.className = 'raw-response';
      pre.textContent = part;
      details.append(summary, pre);
      container.append(details);
    });

    if (fencedParts.length) {
      fencedParts.forEach((block, index) => {
        const details = document.createElement('details');
        details.className = 'raw-response__details';
        const summary = document.createElement('summary');
        summary.textContent =
          fencedParts.length === 1
            ? 'Parsed SIMPLEHEADERS JSON'
            : `Parsed SIMPLEHEADERS JSON (part ${index + 1})`;
        const pre = document.createElement('pre');
        pre.className = 'raw-response';
        pre.textContent = block;
        details.append(summary, pre);
        container.append(details);
      });
    } else if (fallbackText && fallbackText.trim()) {
      const details = document.createElement('details');
      details.className = 'raw-response__details';
      const summary = document.createElement('summary');
      summary.textContent = 'Parsed SIMPLEHEADERS JSON';
      const pre = document.createElement('pre');
      pre.className = 'raw-response';
      pre.textContent = fallbackText;
      details.append(summary, pre);
      container.append(details);
    }

    // 🔎 NEW: Append trace/decisions panel if available
    if (payload?.trace) {
      const traceDetails = document.createElement('details');
      traceDetails.className = 'raw-response__details';
      traceDetails.open = false;
      const summary = document.createElement('summary');
      summary.textContent = 'Trace: decisions & chunking';
      traceDetails.append(summary, buildTraceView(payload.trace));
      container.append(traceDetails);
    }

    if (!container.childElementCount) {
      container.innerHTML = '<p class="panel-status">Raw response unavailable.</p>';
    }
    return;
  }

  const fallback = fencedParts.length ? fencedParts.join('\n\n') : fallbackText;

  if (!fallback || !String(fallback).trim()) {
    container.innerHTML = '<p class="panel-status">Raw response unavailable.</p>';
    // 🔎 NEW: show trace even if no raw output
    if (payload?.trace) {
      const traceDetails = document.createElement('details');
      traceDetails.className = 'raw-response__details';
      traceDetails.open = true;
      const summary = document.createElement('summary');
      summary.textContent = 'Trace: decisions & chunking';
      traceDetails.append(summary, buildTraceView(payload.trace));
      container.append(traceDetails);
    }
    return;
  }

  const pre = document.createElement('pre');
  pre.className = 'raw-response';
  pre.textContent = String(fallback);
  container.append(pre);

  // 🔎 NEW: Append trace/decisions panel
  if (payload?.trace) {
    const traceDetails = document.createElement('details');
    traceDetails.className = 'raw-response__details';
    traceDetails.open = false;
    const summary = document.createElement('summary');
    summary.textContent = 'Trace: decisions & chunking';
    traceDetails.append(summary, buildTraceView(payload.trace));
    container.append(traceDetails);
  }
}

// Internal helper used by renderHeaderRawResponse and renderHeaderTrace
function buildTraceView(trace) {
  const root = document.createElement('div');
  root.className = 'trace';

  const events = Array.isArray(trace?.events) ? trace.events : [];
  const decisionTypes = new Set([
    'candidate_found',
    'anchor_resolved',
    'fallback_triggered',
    'monotonic_violation',
    // chunking visibility
    'chunking_start',
    'line_index_map_built',
    'header_missing_global',
    'header_not_in_lines',
    'chunk_bounds_resolved',
    'chunk_skipped_inverted',
    'chunk_built',
    'chunking_complete',
    // cache-state
    'cache_purged',
    'cache_bypassed',
  ]);
  const decisions = events.filter((e) => decisionTypes.has(e?.type));

  // Quick chunking summary from events
  const counts = (type) => decisions.filter((e) => e?.type === type).length;
  const chunkBuilt = decisions.filter((e) => e?.type === 'chunk_built');
  const summary = document.createElement('div');
  summary.className = 'trace-summary';
  summary.innerHTML = `
    <div class="trace-kv">
      <span class="kv-label">Chunks built</span>
      <span class="kv-value">${chunkBuilt.length}</span>
    </div>
    <div class="trace-kv">
      <span class="kv-label">Bounds resolved</span>
      <span class="kv-value">${counts('chunk_bounds_resolved')}</span>
    </div>
    <div class="trace-kv">
      <span class="kv-label">Skipped (inverted)</span>
      <span class="kv-value">${counts('chunk_skipped_inverted')}</span>
    </div>
    <div class="trace-kv">
      <span class="kv-label">Missing global</span>
      <span class="kv-value">${counts('header_missing_global')}</span>
    </div>
    <div class="trace-kv">
      <span class="kv-label">Not in lines</span>
      <span class="kv-value">${counts('header_not_in_lines')}</span>
    </div>
  `;
  root.append(summary);

  if (chunkBuilt.length) {
    const built = document.createElement('details');
    built.open = false;
    const sum = document.createElement('summary');
    sum.textContent = 'Built chunks';
    built.append(sum);

    const list = document.createElement('ul');
    list.className = 'decision-list';
    chunkBuilt.forEach((ev) => {
      const li = document.createElement('li');
      li.className = 'decision-item';
      const label = document.createElement('div');
      label.className = 'decision-title';
      const pos = isFinite(ev?.position) ? ` #${ev.position}` : '';
      label.textContent = `chunk_built${pos} · L${ev.level ?? '—'} · [${ev.start_global_idx ?? '—'}–${ev.end_global_idx ?? '—'}] (p${(ev.start_page ?? 0) + 1}–p${(ev.end_page ?? 0) + 1})`;
      const sub = document.createElement('div');
      sub.className = 'decision-sub';
      const headerTxt = (ev?.header_text ?? '').toString();
      sub.textContent = headerTxt ? headerTxt : '(no header text)';
      li.append(label, sub);
      list.append(li);
    });
    built.append(list);
    root.append(built);
  }

  // All decisions (chronological)
  if (decisions.length) {
    const all = document.createElement('details');
    all.open = false;
    const sum = document.createElement('summary');
    sum.textContent = `All decisions (${decisions.length})`;
    all.append(sum);

    const list = document.createElement('ul');
    list.className = 'decision-list';
    decisions.forEach((ev) => {
      const li = document.createElement('li');
      li.className = 'decision-item';
      const title = document.createElement('div');
      title.className = 'decision-title';
      const when = ev?.t ? new Date(ev.t * 1000).toLocaleTimeString() : '';
      title.textContent = `${ev.type}${when ? ' · ' + when : ''}`;

      const sub = document.createElement('div');
      sub.className = 'decision-sub';
      const dataPreview = { ...ev };
      delete dataPreview.t;
      delete dataPreview.type;
      sub.textContent = JSON.stringify(dataPreview);

      li.append(title, sub);
      list.append(li);
    });
    all.append(list);
    root.append(all);
  }

  // Paths (helpful for debugging)
  if (trace?.path || trace?.summary_path) {
    const paths = document.createElement('div');
    paths.className = 'trace-paths';
    if (trace.path) {
      const p = document.createElement('div');
      p.textContent = `trace: ${trace.path}`;
      paths.append(p);
    }
    if (trace.summary_path) {
      const s = document.createElement('div');
      s.textContent = `summary: ${trace.summary_path}`;
      paths.append(s);
    }
    root.append(paths);
  }

  return root;
}


// ⬇️ Optional: small enhancement to renderHeaderOutline to surface a quick chunking hint if trace present
export function renderHeaderOutline(container, payload, options = {}) {
  if (!container) return;
  if (
    payload?.mode === 'llm_full_error' &&
    payload?.llm_failure_raw_response &&
    String(payload.llm_failure_raw_response).trim()
  ) {
    const message = document.createElement('p');
    message.className = 'panel-error';
    message.textContent =
      'LLM returned an invalid response. Review the raw output below to diagnose the fault.';

    const pre = document.createElement('pre');
    pre.className = 'raw-response';
    pre.textContent = String(payload.llm_failure_raw_response);

    container.innerHTML = '';
    container.append(message, pre);
    return;
  }
  if (Array.isArray(payload?.simpleheaders) && payload.simpleheaders.length && Array.isArray(payload.sections) && payload.sections.length) {
    // Quick banner showing number of chunks if trace exists
    container.innerHTML = '';
    if (payload?.trace?.events) {
      const chunksBuilt = payload.trace.events.filter((e) => e.type === 'chunk_built').length;
      const banner = document.createElement('p');
      banner.className = 'panel-status';
      banner.textContent = `Sections: ${payload.sections.length} • Chunks built: ${chunksBuilt}`;
      container.append(banner);
    }
    // Render the regular SimpleHeaders UI beneath
    const holder = document.createElement('div');
    container.append(holder);
    renderSimpleHeaders(holder, payload, options);
    return;
  }
  if (!payload?.outline?.length) {
    setPanelError(container, 'No headers detected.');
    return;
  }

  const list = document.createElement('ul');
  list.className = 'tree-list';
  payload.outline.forEach((node) => list.append(renderTreeNode(node)));

  container.innerHTML = '';
  container.append(list);
}


function renderSimpleHeaders(container, payload, { documentId, fetchSection } = {}) {
  const headers = Array.isArray(payload.simpleheaders) ? payload.simpleheaders : [];
  const sections = Array.isArray(payload.sections) ? payload.sections : [];
  if (!headers.length || !sections.length) {
    setPanelError(container, 'No headers detected.');
    return;
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'simpleheaders';

  const list = document.createElement('div');
  list.className = 'simpleheaders__list';
  const viewer = document.createElement('pre');
  viewer.className = 'simpleheaders__viewer';
  viewer.textContent = 'Select a section to preview its text.';

  let activeIndex = -1;
  let requestToken = 0;

  const formatPageRange = (section) => {
    const startPage = Number(section?.start_page ?? 0) + 1;
    const endPageRaw = section?.end_page ?? section?.start_page ?? 0;
    const endPage = Number(endPageRaw) + 1;
    if (!Number.isFinite(startPage) || !Number.isFinite(endPage)) {
      return 'Pages unknown';
    }
    return startPage === endPage ? `Page ${startPage}` : `Pages ${startPage}–${endPage}`;
  };

  const items = headers.map((header, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'simpleheaders__item';
    button.dataset.index = String(index);
    const label = header.number ? `${header.number} ${header.text}` : header.text;
    button.style.paddingLeft = `${Math.max(0, Number(header.level || 1) - 1) * 12}px`;
    button.title = formatPageRange(sections[index]) ?? `Page ${Number(header.page ?? 0) + 1}`;
    if (header.section_key) {
      button.dataset.sectionKey = String(header.section_key);
    }

    const labelEl = document.createElement('span');
    labelEl.className = 'simpleheaders__item-label';
    labelEl.textContent = label;

    const metaEl = document.createElement('span');
    metaEl.className = 'simpleheaders__item-meta';
    const metaParts = [];
    const pageNumber = Number(header.page);
    if (Number.isFinite(pageNumber)) {
      metaParts.push(`Page ${pageNumber + 1}`);
    }
    const lineNumber = Number(header.line_idx);
    if (Number.isFinite(lineNumber)) {
      metaParts.push(`Line ${lineNumber + 1}`);
    }
    const pageLabel = formatPageRange(sections[index]) ?? '';
    if (!metaParts.length && pageLabel) {
      metaParts.push(pageLabel);
    }
    if (metaParts.length) {
      metaEl.textContent = metaParts.join(' · ');
    }

    button.textContent = '';
    button.append(labelEl);
    if (metaEl.textContent) {
      button.append(metaEl);
    }

    button.addEventListener('click', () => selectIndex(index));
    list.append(button);
    return button;
  });

  async function selectIndex(index) {
    if (index === activeIndex) return;
    activeIndex = index;
    const section = sections[index];
    const sectionKey = headerKeyForIndex(index);
    const pageLabel = formatPageRange(section);
    items.forEach((item, idx) => {
      if (idx === index) {
        item.dataset.active = 'true';
        item.setAttribute('aria-current', 'true');
      } else {
        delete item.dataset.active;
        item.removeAttribute('aria-current');
      }
    });

    if (!section || typeof fetchSection !== 'function' || !documentId) {
      viewer.textContent = 'Section data unavailable.';
      return;
    }

    const token = ++requestToken;
    viewer.dataset.loading = 'true';
    viewer.textContent = `Loading section…\n${pageLabel}`;

    try {
      const text = await fetchSection(
        documentId,
        section.start_global_idx,
        section.end_global_idx,
        sectionKey,
      );
      if (token !== requestToken) {
        return;
      }
      const finalText = text?.trim() ? text : '(Empty section)';
      viewer.textContent = `${pageLabel}\n\n${finalText}`;
    } catch (error) {
      if (token !== requestToken) {
        return;
      }
      const message = error instanceof Error ? error.message : 'Unable to load section.';
      viewer.textContent = message;
    } finally {
      if (token === requestToken) {
        delete viewer.dataset.loading;
      }
    }
  }

  function headerKeyForIndex(index) {
    const header = headers[index];
    if (header && header.section_key) {
      return header.section_key;
    }
    const section = sections[index];
    return section?.section_key ?? null;
  }

  wrapper.append(list, viewer);
  container.innerHTML = '';
  container.append(wrapper);

  if (headers.length) {
    selectIndex(0);
  }
}

function renderTreeNode(node) {
  const item = document.createElement('li');
  item.className = 'tree-item';
  const title = document.createElement('div');
  title.className = 'tree-item__title';
  title.textContent = node.numbering ? `${node.numbering} ${node.title}` : node.title;
  const meta = document.createElement('div');
  meta.className = 'tree-item__meta';
  meta.textContent = node.page != null ? `Page ${node.page + 1}` : 'Page unknown';
  item.append(title, meta);

  if (Array.isArray(node.children) && node.children.length) {
    const children = document.createElement('ul');
    children.className = 'tree-list';
    node.children.forEach((child) => children.append(renderTreeNode(child)));
    item.append(children);
  }
  return item;
}

function normaliseDiscipline(value) {
  if (!value) return 'Unknown';
  return value
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function renderSpecsBuckets(
  container,
  buckets,
  { documentId, approvedLines, onApproveToggle, readOnly = false } = {},
) {
  if (!container) return;
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
    setPanelError(container, 'No specification lines available.');
    return;
  }

  const tabs = document.createElement('div');
  tabs.className = 'specs-tabs';
  const tabList = document.createElement('div');
  tabList.className = 'specs-tablist';
  tabList.setAttribute('role', 'tablist');
  const panels = document.createElement('div');
  panels.className = 'specs-panels';

  entries.forEach(([discipline, lines], index) => {
    const tabId = `spec-tab-${discipline}`;
    const panelId = `spec-panel-${discipline}`;

    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'specs-tab';
    tab.id = tabId;
    tab.dataset.discipline = discipline;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', panelId);
    tab.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
    tab.tabIndex = index === 0 ? 0 : -1;
    tab.textContent = `${normaliseDiscipline(discipline)} (${lines.length})`;
    tab.addEventListener('click', () => activateSpecsTab(tabList, panels, discipline, { focus: true }));
    tabList.append(tab);

    const panel = document.createElement('section');
    panel.className = 'specs-panel';
    panel.id = panelId;
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', tabId);
    panel.hidden = index !== 0;

    const meta = document.createElement('p');
    meta.className = 'panel-status';
    meta.textContent = `${lines.length} line${lines.length === 1 ? '' : 's'} in this bucket.`;
    panel.append(meta);

    lines.forEach((line, lineIndex) => {
      const key = buildLineKey(line, lineIndex);
      const item = document.createElement('article');
      item.className = 'spec-line';
      item.dataset.lineKey = key;
      const initiallyApproved = approvedLines?.has(key) || readOnly;
      if (initiallyApproved) {
        item.dataset.approved = 'true';
      }

      const text = document.createElement('p');
      text.className = 'spec-line__text';
      text.textContent = line.text;

      const metaRow = document.createElement('p');
      metaRow.className = 'spec-line__meta';
      const headerPath = Array.isArray(line.header_path) && line.header_path.length
        ? line.header_path.join(' › ')
        : 'No header context';
      const pageNumber = typeof line.page === 'number' ? line.page + 1 : '—';
      metaRow.textContent = `Page ${pageNumber} • Header: ${headerPath}`;

      const actionRow = document.createElement('div');
      actionRow.className = 'spec-line__actions';
      const approveButton = document.createElement('button');
      approveButton.type = 'button';
      approveButton.className = 'ghost-button';
      if (readOnly) {
        approveButton.textContent = 'Frozen';
        approveButton.disabled = true;
      } else {
        approveButton.textContent = approvedLines?.has(key) ? 'Approved' : 'Approve';
      }
      approveButton.addEventListener('click', () => {
        if (readOnly) {
          return;
        }
        const approvedSet = approvedLines ?? null;
        const approved = !approvedSet?.has?.(key);
        if (approved) {
          item.dataset.approved = 'true';
          approveButton.textContent = 'Approved';
          if (approvedSet) {
            approvedSet.add(key);
          }
        } else {
          delete item.dataset.approved;
          approveButton.textContent = 'Approve';
          if (approvedSet) {
            approvedSet.delete(key);
          }
        }
        onApproveToggle?.({ key, approved, line, documentId, discipline });
      });
      actionRow.append(approveButton);

      item.append(text, metaRow, actionRow);
      panel.append(item);
    });

    panels.append(panel);
  });

  tabs.append(tabList, panels);
  container.innerHTML = '';
  container.append(tabs);

  tabList.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) {
      return;
    }
    const tabButtons = Array.from(tabList.querySelectorAll('[role="tab"]'));
    if (!tabButtons.length) {
      return;
    }
    const current = tabButtons.findIndex((tab) => tab.getAttribute('aria-selected') === 'true');
    if (current === -1) {
      return;
    }
    event.preventDefault();
    const delta = event.key === 'ArrowRight' ? 1 : -1;
    const nextIndex = (current + delta + tabButtons.length) % tabButtons.length;
    const nextDiscipline = tabButtons[nextIndex]?.dataset.discipline;
    if (nextDiscipline) {
      activateSpecsTab(tabList, panels, nextDiscipline, { focus: true });
    }
  });
}

function activateSpecsTab(tabList, panels, discipline, { focus = false } = {}) {
  const tabs = Array.from(tabList.querySelectorAll('[role="tab"]'));
  const panelElements = Array.from(panels.querySelectorAll('[role="tabpanel"]'));
  const activePanelId = `spec-panel-${discipline}`;
  tabs.forEach((tab) => {
    const isActive = tab.dataset.discipline === discipline;
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    tab.tabIndex = isActive ? 0 : -1;
    if (isActive && focus) {
      tab.focus({ preventScroll: true });
    }
  });
  panelElements.forEach((panel) => {
    panel.hidden = panel.id !== activePanelId;
  });
}

function buildLineKey(line, index) {
  const header = Array.isArray(line.header_path) ? line.header_path.join('/') : '';
  return `${line.page ?? 'na'}|${header}|${index}|${line.text}`;
}

function formatPercent(value) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

export function renderRiskPanel(container, report) {
  if (!container) return;
  if (!report) {
    setPanelError(container, 'Risk report unavailable.');
    return;
  }

  const summary = document.createElement('div');
  summary.className = 'risk-summary';

  const overallCard = document.createElement('div');
  overallCard.className = 'risk-card';
  const overallTitle = document.createElement('p');
  overallTitle.className = 'risk-card__title';
  overallTitle.textContent = 'Overall coverage';
  const overallValue = document.createElement('p');
  overallValue.className = 'risk-card__value';
  overallValue.textContent = formatPercent(report.overall_score);
  overallCard.append(overallTitle, overallValue);
  summary.append(overallCard);

  if (report.coverage_by_discipline) {
    for (const [discipline, score] of Object.entries(report.coverage_by_discipline)) {
      const card = document.createElement('div');
      card.className = 'risk-card';
      const title = document.createElement('p');
      title.className = 'risk-card__title';
      title.textContent = normaliseDiscipline(discipline);
      const value = document.createElement('p');
      value.className = 'risk-card__value';
      value.textContent = formatPercent(score);
      card.append(title, value);
      summary.append(card);
    }
  }

  const missingClauses = Array.isArray(report.missing_clause_ids) ? report.missing_clause_ids : [];
  const missingHeading = document.createElement('h4');
  missingHeading.textContent = missingClauses.length ? 'Missing clauses' : 'All mandatory clauses satisfied';

  const missingList = document.createElement('ul');
  missingList.className = 'risk-missing-list';
  if (missingClauses.length) {
    missingClauses.forEach((clauseId) => {
      const item = document.createElement('li');
      item.textContent = clauseId;
      missingList.append(item);
    });
  }

  const findingsDetails = document.createElement('details');
  findingsDetails.open = false;
  const summaryLabel = document.createElement('summary');
  summaryLabel.textContent = 'View clause findings';
  findingsDetails.append(summaryLabel);
  const findingsList = document.createElement('ul');
  findingsList.className = 'risk-missing-list';
  (report.findings ?? []).forEach((finding) => {
    const item = document.createElement('li');
    const discipline = normaliseDiscipline(finding.discipline);
    const status = finding.matched ? 'matched' : 'missing';
    item.textContent = `${finding.clause_id} • ${discipline} • ${status} (${formatPercent(
      finding.score,
    )})`;
    findingsList.append(item);
  });
  findingsDetails.append(findingsList);

  const compliance = Array.isArray(report.compliance_notes) ? report.compliance_notes : [];
  const complianceFragment = document.createDocumentFragment();
  if (compliance.length) {
    const heading = document.createElement('h4');
    heading.textContent = 'Compliance recommendations';
    complianceFragment.append(heading);
    const list = document.createElement('ul');
    list.className = 'risk-missing-list';
    compliance.forEach((entry) => {
      const item = document.createElement('li');
      const text = entry.action ?? entry.note ?? JSON.stringify(entry);
      item.textContent = text;
      list.append(item);
    });
    complianceFragment.append(list);
  }

  container.innerHTML = '';
  container.append(summary, missingHeading, missingList, findingsDetails, complianceFragment);
}

export function renderSpecAnalysisStatus(container, message, variant = 'info') {
  if (!container) return;
  container.innerHTML = '';
  if (!message) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const status = document.createElement('p');
  status.className = `panel-status panel-status--${variant}`;
  status.textContent = message;
  container.append(status);
}

export function renderSpecAnalysis(container, sections, { agent = 'all', level = 'all' } = {}) {
  if (!container) return;
  container.innerHTML = '';

  if (!Array.isArray(sections) || !sections.length) {
    const empty = document.createElement('p');
    empty.className = 'panel-status';
    empty.textContent = 'No aligned sections available yet.';
    container.append(empty);
    return;
  }

  sections.forEach((section) => {
    const details = document.createElement('details');
    details.className = 'spec-section';
    const summary = document.createElement('summary');
    summary.className = 'spec-section__summary';

    const title = document.createElement('span');
    title.className = 'spec-section__title';
    title.textContent = section.title || 'Untitled section';

    const meta = document.createElement('span');
    meta.className = 'spec-section__meta';
    const pageStart = Number.isFinite(section.pageStart) ? section.pageStart : null;
    const pageEnd = Number.isFinite(section.pageEnd) ? section.pageEnd : null;
    if (pageStart != null && pageEnd != null && pageStart !== pageEnd) {
      meta.textContent = `Pages ${pageStart}–${pageEnd}`;
    } else if (pageStart != null) {
      meta.textContent = `Page ${pageStart}`;
    } else if (pageEnd != null) {
      meta.textContent = `Page ${pageEnd}`;
    } else {
      meta.textContent = 'Page range unknown';
    }

    const status = document.createElement('span');
    status.className = `spec-section__status status-${section.status}`;
    status.textContent = section.status;

    summary.append(title, meta, status);
    details.append(summary);

    const grid = document.createElement('div');
    grid.className = 'spec-section__grid';

    AGENT_CODES.forEach((code) => {
      if (agent !== 'all' && agent !== code) {
        return;
      }
      const record = section?.specs?.[code] ?? null;
      const card = document.createElement('article');
      card.className = 'spec-agent-card';
      card.dataset.agent = code;

      const header = document.createElement('header');
      header.className = 'spec-agent-card__header';
      const heading = document.createElement('h5');
      heading.textContent = prettifyAgent(code);
      header.append(heading);

      if (record?.confidence) {
        const confidence = document.createElement('span');
        confidence.className = 'spec-agent-card__confidence';
        confidence.textContent = `Confidence ${record.confidence}`;
        header.append(confidence);
      }

      card.append(header);

      const body = document.createElement('div');
      body.className = 'spec-agent-card__body';

      const requirements = Array.isArray(record?.result?.requirements)
        ? record.result.requirements
        : [];
      const filtered = level === 'all'
        ? requirements
        : requirements.filter((req) => String(req.level).toUpperCase() === level);

      if (!record) {
        const note = document.createElement('p');
        note.className = 'spec-agent-card__empty';
        note.textContent = section.status === 'failed'
          ? 'Job failed for this agent.'
          : 'No result yet.';
        body.append(note);
      } else if (!filtered.length) {
        const note = document.createElement('p');
        note.className = 'spec-agent-card__empty';
        note.textContent = level === 'all'
          ? 'No requirements extracted.'
          : `No requirements at level ${level}.`;
        body.append(note);
      } else {
        const list = document.createElement('ul');
        list.className = 'spec-agent-card__list';
        filtered.forEach((req) => {
          const item = document.createElement('li');
          item.className = 'spec-agent-card__item';

          const headerRow = document.createElement('div');
          headerRow.className = 'spec-agent-card__item-header';
          const levelBadge = document.createElement('span');
          levelBadge.className = `spec-level spec-level--${String(req.level).toUpperCase()}`;
          levelBadge.textContent = String(req.level).toUpperCase();
          headerRow.append(levelBadge);
          if (req.page_hint != null) {
            const page = document.createElement('span');
            page.className = 'spec-agent-card__page';
            page.textContent = `Page ${req.page_hint}`;
            headerRow.append(page);
          }
          item.append(headerRow);

          const text = document.createElement('p');
          text.className = 'spec-agent-card__text';
          text.textContent = req.text;
          item.append(text);

          list.append(item);
        });
        body.append(list);
      }

      if (Array.isArray(record?.result?.notes) && record.result.notes.length) {
        const notes = document.createElement('ul');
        notes.className = 'spec-agent-card__notes';
        record.result.notes.forEach((note) => {
          const li = document.createElement('li');
          li.textContent = note;
          notes.append(li);
        });
        body.append(notes);
      }

      card.append(body);
      grid.append(card);
    });

    if (!grid.childElementCount) {
      const fallback = document.createElement('p');
      fallback.className = 'panel-status';
      fallback.textContent = 'Filters hide all agent results.';
      grid.append(fallback);
    }

    details.append(grid);
    container.append(details);
  });
}

function prettifyAgent(code) {
  switch (code) {
    case 'Mechanical':
      return 'Mechanical';
    case 'Electrical':
      return 'Electrical';
    case 'Controls':
      return 'Controls';
    case 'Software':
      return 'Software';
    case 'ProjectManagement':
      return 'Project Management';
    default:
      return code;
  }
}

export function showToast(message, variant = 'info', timeout = 3500) {
  const region = document.querySelector('#toast-region');
  if (!region) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  if (variant === 'error') {
    toast.classList.add('toast--error');
  } else if (variant === 'warning') {
    toast.classList.add('toast--warning');
  }
  toast.textContent = message;
  region.append(toast);
  setTimeout(() => {
    toast.classList.add('toast--closing');
    setTimeout(() => toast.remove(), 220);
  }, timeout);
}
