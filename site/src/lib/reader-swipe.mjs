// @ts-check

/**
 * Bind touch-only scene navigation to an artwork canvas. Kept self-contained so
 * the frozen Jev reader's export can use this same function without a runtime.
 * @param {HTMLElement} surface
 * @param {(direction: -1 | 1) => void} navigate
 * @returns {() => void} Remove listeners and restore browser gesture behavior.
 */
export function attachReaderSwipe(surface, navigate) {
  const doc = surface.ownerDocument;
  const win = doc.defaultView;
  if (!win) return () => {};
  const viewport = win.visualViewport;
  const originalTouchAction = surface.style.touchAction;
  /** @type {{id: number, x: number, y: number, started: number, threshold: number} | null} */
  let gesture = null;
  let suppressClickUntil = 0;
  const cancel = () => { gesture = null; };
  const unavailable = () => (viewport?.scale ?? 1) > 1.01
    || doc.getSelection()?.isCollapsed === false || !!doc.querySelector("dialog:modal");
  const updateZoom = () => {
    cancel();
    surface.style.touchAction = (viewport?.scale ?? 1) > 1.01 ? "auto" : "pan-y pinch-zoom";
  };
  /** @param {TouchEvent} event */
  const observeContacts = event => { if (event.touches.length !== 1) cancel(); };
  /** @param {TouchEvent} event */
  const start = event => {
    cancel();
    suppressClickUntil = 0;
    if (event.touches.length !== 1 || unavailable()) return;
    const target = event.target instanceof Element ? event.target : null;
    const control = target?.closest("a,button,input,textarea,select,summary,video,audio,[contenteditable],[role=button],[role=slider]");
    // A canvas link still opens its original image on a tap. Nested controls,
    // including Jev's in-slide links and media, retain their own gestures.
    if (control && control !== surface) return;
    const touch = event.touches[0];
    // Leave browser edge-navigation gestures alone.
    if (touch.clientX < 24 || touch.clientX > win.innerWidth - 24) return;
    gesture = {
      id: touch.identifier, x: touch.clientX, y: touch.clientY,
      started: event.timeStamp,
      threshold: Math.max(48, Math.min(96, surface.clientWidth * 0.12)),
    };
  };
  /** @param {TouchEvent} event */
  const move = event => {
    if (!gesture) return;
    if (event.touches.length !== 1 || unavailable() || event.timeStamp - gesture.started > 650) { cancel(); return; }
    const touch = event.touches[0];
    if (touch.identifier !== gesture.id) { cancel(); return; }
    const dx = Math.abs(touch.clientX - gesture.x), dy = Math.abs(touch.clientY - gesture.y);
    if (Math.max(dx, dy) < 12) return;
    // Once a stroke is vertical/diagonal it cannot turn into a page swipe.
    if (dx < dy * 1.5) { cancel(); return; }
    if (event.cancelable) event.preventDefault();
  };
  /** @param {TouchEvent} event */
  const end = event => {
    const current = gesture;
    cancel();
    if (!current || event.touches.length || unavailable() || event.timeStamp - current.started > 650) return;
    const touch = Array.from(event.changedTouches).find(item => item.identifier === current.id);
    if (!touch) return;
    const dx = touch.clientX - current.x, dy = touch.clientY - current.y;
    if (Math.abs(dx) < current.threshold || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    // Do not also activate the canvas's full-size-image link after a swipe.
    if (event.cancelable) event.preventDefault();
    suppressClickUntil = win.performance.now() + 400;
    navigate(dx < 0 ? 1 : -1);
  };
  /** @param {MouseEvent} event */
  const click = event => {
    if (event.detail && win.performance.now() < suppressClickUntil) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  };
  const selectionChanged = () => { if (doc.getSelection()?.isCollapsed === false) cancel(); };
  updateZoom();
  surface.addEventListener("touchstart", start, { passive: true });
  surface.addEventListener("touchmove", move, { passive: false });
  surface.addEventListener("touchend", end, { passive: false });
  surface.addEventListener("touchcancel", cancel, { passive: true });
  surface.addEventListener("contextmenu", cancel);
  surface.addEventListener("click", click, true);
  doc.addEventListener("touchstart", observeContacts, { capture: true, passive: true });
  doc.addEventListener("selectionchange", selectionChanged);
  doc.addEventListener("scroll", cancel, { capture: true, passive: true });
  win.addEventListener("blur", cancel);
  win.addEventListener("pagehide", cancel);
  win.addEventListener("popstate", cancel);
  win.addEventListener("hashchange", cancel);
  viewport?.addEventListener("resize", updateZoom);
  return () => {
    cancel();
    surface.style.touchAction = originalTouchAction;
    surface.removeEventListener("touchstart", start);
    surface.removeEventListener("touchmove", move);
    surface.removeEventListener("touchend", end);
    surface.removeEventListener("touchcancel", cancel);
    surface.removeEventListener("contextmenu", cancel);
    surface.removeEventListener("click", click, true);
    doc.removeEventListener("touchstart", observeContacts, true);
    doc.removeEventListener("selectionchange", selectionChanged);
    doc.removeEventListener("scroll", cancel, true);
    win.removeEventListener("blur", cancel);
    win.removeEventListener("pagehide", cancel);
    win.removeEventListener("popstate", cancel);
    win.removeEventListener("hashchange", cancel);
    viewport?.removeEventListener("resize", updateZoom);
  };
}
