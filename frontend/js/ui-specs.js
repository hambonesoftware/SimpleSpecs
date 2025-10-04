export function initSpecs() {
  const container = document.querySelector('[data-specs]');
  if (!container) {
    return;
  }

  container.textContent = 'Run spec extraction to populate mechanical requirements.';
}
