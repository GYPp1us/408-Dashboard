/* Selection follows the tape; programmatic centering never becomes user input. */
(() => {
  'use strict';
  if (window.PaperTape) return;
  const bindings = new WeakMap();
  const now = () => performance.now();
  const scale = strip => window.MutsumiViewport?.elementScale(strip) || (strip.offsetWidth ? strip.getBoundingClientRect().width / strip.offsetWidth : 1) || 1;
  const options = (strip, state) => [...strip.querySelectorAll(state.selector)];
  function nearest(strip, state) {
    const rect = strip.getBoundingClientRect(), x = rect.left + rect.width / 2;
    return options(strip, state).reduce((best, node) => {
      const bounds = node.getBoundingClientRect(), distance = Math.abs(bounds.left + bounds.width / 2 - x);
      return !best || distance < best.distance ? {node, distance} : best;
    }, null)?.node;
  }
  function clearFrame(state) { if (state.frame != null) cancelAnimationFrame(state.frame); state.frame = null; }
  function unlockAfterScroll(state) {
    clearTimeout(state.timer);
    state.timer = setTimeout(() => { state.programmatic = false; }, 180);
  }
  function center(strip, value, behavior = 'auto') {
    const state = bindings.get(strip); if (!state) return;
    const node = options(strip, state).find(node => node.dataset.value === String(value));
    if (!node || !strip.clientWidth) return;
    const bounds = node.getBoundingClientRect(), rect = strip.getBoundingClientRect();
    if (!rect.width) return;
    const left = strip.scrollLeft + (bounds.left + bounds.width / 2 - rect.left - rect.width / 2) / scale(strip);
    state.programmatic = true; clearFrame(state);
    strip.scrollTo({left:Math.max(0, Math.min(strip.scrollWidth - strip.clientWidth, left)), behavior});
    unlockAfterScroll(state);
  }
  function reset(strip, selected) {
    const state = bindings.get(strip); if (!state) return;
    state.generation++; clearFrame(state); clearTimeout(state.timer);
    if (state.drag && strip.hasPointerCapture?.(state.drag.id)) strip.releasePointerCapture(state.drag.id);
    state.drag = null; state.programmatic = true;
    strip.classList.remove('is-dragging');
    const generation = state.generation;
    state.frame = requestAnimationFrame(() => {
      state.frame = requestAnimationFrame(() => {
        state.frame = null;
        if (state.generation === generation) center(strip, selected, 'auto');
      });
    });
  }
  function bind(strip, config) {
    if (!strip) return;
    let state = bindings.get(strip);
    if (state) { Object.assign(state, config); return; }
    state = {...config, generation:0, frame:null, timer:null, drag:null, programmatic:false, suppressClickUntil:0};
    bindings.set(strip, state);
    strip.addEventListener('scroll', () => {
      if (state.programmatic) { unlockAfterScroll(state); return; }
      if (state.frame != null) return;
      const generation = state.generation;
      state.frame = requestAnimationFrame(() => {
        state.frame = null;
        if (generation !== state.generation || state.programmatic) return;
        const node = nearest(strip, state); if (node) state.onSelect(node);
      });
    }, {passive:true});
    strip.addEventListener('scrollend', () => {
      if (state.programmatic) { clearTimeout(state.timer); state.programmatic = false; return; }
      const node = nearest(strip, state); if (node) state.onSelect(node);
    });
    strip.addEventListener('pointerdown', event => {
      clearFrame(state); clearTimeout(state.timer); state.programmatic = false;
      strip.scrollTo({left:strip.scrollLeft, behavior:'instant'});
      state.drag = {id:event.pointerId, x:event.clientX, left:strip.scrollLeft, touch:event.pointerType === 'touch', moved:false};
      if (!state.drag.touch) { strip.setPointerCapture?.(event.pointerId); strip.classList.add('is-dragging'); }
    });
    strip.addEventListener('pointermove', event => {
      const drag = state.drag; if (!drag || drag.id !== event.pointerId) return;
      drag.moved ||= Math.abs(event.clientX - drag.x) > 5;
      if (!drag.touch) strip.scrollLeft = drag.left - (event.clientX - drag.x) / scale(strip);
    });
    const finish = event => {
      const drag = state.drag; if (!drag || drag.id !== event.pointerId) return;
      if (strip.hasPointerCapture?.(drag.id)) strip.releasePointerCapture(drag.id);
      state.drag = null; strip.classList.remove('is-dragging');
      if (drag.moved || event.type === 'pointercancel') state.suppressClickUntil = now() + 250;
      // Touch scrolling and its snap remain browser-owned, including cancel.
      if (!drag.touch && event.type !== 'pointercancel') {
        const node = nearest(strip, state);
        if (node) { state.onSelect(node); center(strip, node.dataset.value, 'smooth'); }
      }
    };
    strip.addEventListener('pointerup', finish);
    strip.addEventListener('pointercancel', finish);
    strip.addEventListener('click', event => {
      if (now() < state.suppressClickUntil) return;
      const node = event.target.closest?.(state.selector); if (!node || !strip.contains(node)) return;
      state.onSelect(node); center(strip, node.dataset.value, 'smooth');
    });
    strip.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const nodes = options(strip, state), current = nodes.findIndex(node => node.dataset.value === String(state.selected()));
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? nodes.length - 1
        : Math.max(0, Math.min(nodes.length - 1, current + (event.key === 'ArrowRight' ? 1 : -1)));
      const node = nodes[index]; if (!node) return;
      event.preventDefault(); state.onSelect(node); center(strip, node.dataset.value, 'smooth');
    });
  }
  window.PaperTape = {bind, center, rendered:reset};
})();
