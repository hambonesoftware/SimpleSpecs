export function initSections() {
  const container = document.querySelector('[data-section-tree]');
  if (!container) {
    return;
  }

  container.textContent = 'Run header discovery to view section outlines.';
}
