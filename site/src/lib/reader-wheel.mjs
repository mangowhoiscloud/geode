// @ts-check

/**
 * Bind bounded horizontal wheel navigation to an artwork canvas. Self-contained
 * so the frozen Jev reader's route projection uses the same recognizer.
 * @param {HTMLElement} surface
 * @param {(direction: -1 | 1) => boolean} canNavigate
 * @param {(direction: -1 | 1) => void} navigate
 * @returns {() => void}
 */
export function attachReaderWheel(surface, canNavigate, navigate) {
  const doc = surface.ownerDocument, win = doc.defaultView;
  if (!win) return () => {};
  /** @type {{last: number, started: number, x: number, y: number, direction: -1 | 0 | 1, phase: "pending" | "blocked" | "locked"} | null} */
  let stroke = null;
  let lastNavigation = -Infinity;
  let pointerDown = false;
  // Navigation itself scrolls to the top. That must not release a claimed tail.
  const block = () => { if (stroke && stroke.phase !== "locked") stroke.phase = "blocked"; };
  /** @param {number} now */
  const transaction = now => {
    if (!stroke || now - stroke.last > 280) {
      stroke = { last: now, started: now, x: 0, y: 0, direction: 0,
        phase: now - lastNavigation < 650 ? "blocked" : "pending" };
    }
    stroke.last = now;
    return stroke;
  };
  /** @param {Element} target */
  const nativeTarget = target => {
    const control = target.closest("a,button,input,textarea,select,summary,video,audio,iframe,[contenteditable],[role=button],[role=slider],[role=scrollbar]");
    if (control && control !== surface) return true;
    // Keep a real horizontal scroller native, even when already at its edge.
    if (doc.scrollingElement && doc.scrollingElement.scrollWidth > doc.scrollingElement.clientWidth + 1) return true;
    /** @type {Element | null} */
    let node = target;
    for (; node; node = node.parentElement) {
      if (node.scrollWidth > node.clientWidth + 1
        && /auto|scroll|overlay/.test(win.getComputedStyle(node).overflowX)) return true;
    }
    return false;
  };
  /** @param {WheelEvent} event */
  const outside = event => {
    if (!(event.target instanceof Element) || !surface.contains(event.target)) {
      transaction(event.timeStamp).phase = "blocked";
    }
  };
  /** @param {WheelEvent} event */
  const wheel = event => {
    const current = transaction(event.timeStamp);
    const target = event.target instanceof Element ? event.target : null;
    const box = surface.getBoundingClientRect();
    if (!target || event.defaultPrevented || !event.cancelable || event.deltaMode !== 0
      || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.buttons || pointerDown
      || !win.matchMedia("(hover: hover) and (pointer: fine)").matches
      || (win.visualViewport?.scale ?? 1) > 1.01 || doc.getSelection()?.isCollapsed === false
      || doc.querySelector("dialog:modal") || nativeTarget(target)
      || event.clientX < 24 || event.clientX > win.innerWidth - 24
      || event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom) { block(); return; }
    const dx = Math.abs(event.deltaX), dy = Math.abs(event.deltaY);
    // A vertical/diagonal onset never changes into paging later in the stroke.
    if (!dx || dx < dy * 2) { block(); return; }
    if (current.phase === "blocked") return;
    // Continue swallowing only an already-claimed horizontal momentum tail.
    // A scene render must not recreate this listener or release this lock.
    if (current.phase === "locked") { event.preventDefault(); return; }
    const direction = event.deltaX > 0 ? 1 : -1;
    if ((current.direction && direction !== current.direction)
      || event.timeStamp - current.started > 500 || !canNavigate(direction)) { block(); return; }
    current.direction = direction;
    current.x += dx;
    current.y += dy;
    event.preventDefault();
    if (current.x < 96 || current.x < current.y * 2) return;
    current.phase = "locked";
    lastNavigation = event.timeStamp;
    navigate(direction);
  };
  const down = () => { pointerDown = true; block(); };
  const up = () => { pointerDown = false; };
  const blur = () => { pointerDown = false; block(); };
  const selection = () => { if (doc.getSelection()?.isCollapsed === false) block(); };
  doc.addEventListener("wheel", outside, { capture: true, passive: true });
  surface.addEventListener("wheel", wheel, { passive: false });
  doc.addEventListener("pointerdown", down, true);
  doc.addEventListener("pointerup", up, true);
  doc.addEventListener("pointercancel", up, true);
  doc.addEventListener("selectionchange", selection);
  doc.addEventListener("scroll", block, { capture: true, passive: true });
  doc.addEventListener("keydown", block, true);
  win.addEventListener("blur", blur);
  win.addEventListener("pagehide", block);
  win.addEventListener("popstate", block);
  win.addEventListener("hashchange", block);
  win.visualViewport?.addEventListener("resize", block);
  return () => {
    stroke = null;
    doc.removeEventListener("wheel", outside, true);
    surface.removeEventListener("wheel", wheel);
    doc.removeEventListener("pointerdown", down, true);
    doc.removeEventListener("pointerup", up, true);
    doc.removeEventListener("pointercancel", up, true);
    doc.removeEventListener("selectionchange", selection);
    doc.removeEventListener("scroll", block, true);
    doc.removeEventListener("keydown", block, true);
    win.removeEventListener("blur", blur);
    win.removeEventListener("pagehide", block);
    win.removeEventListener("popstate", block);
    win.removeEventListener("hashchange", block);
    win.visualViewport?.removeEventListener("resize", block);
  };
}
