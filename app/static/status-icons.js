/* Shared completion marks use a fixed vector canvas, never a font glyph. */
(() => {
  'use strict';
  if (window.StatusIcons) return;
  const completion = (completed=true) => `<svg class="completion-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="display:block;flex:none" aria-hidden="true" focusable="false"><path d="${completed?'M5.5 12 10 16.5 18.5 7.5':'M7 12h10'}"/></svg>`;
  window.StatusIcons = Object.freeze({completion});
})();
