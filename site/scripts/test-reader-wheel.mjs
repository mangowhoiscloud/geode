/** Input partitions and momentum state; browser-native input is checked separately. */
import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import { attachReaderWheel } from "../src/lib/reader-wheel.mjs";

function fixture() {
  class Element extends EventTarget {
    closest() { return this.control ?? null; }
    contains(target) { return target === this || target.parentElement === this; }
    getBoundingClientRect() { return { left: 100, right: 1200, top: 100, bottom: 800 }; }
  }
  const viewport = Object.assign(new EventTarget(), { scale: 1 });
  const win = Object.assign(new EventTarget(), { innerWidth: 1440, visualViewport: viewport,
    matchMedia: () => ({ matches: !win.coarse }), getComputedStyle: node => ({ overflowX: node.overflowX ?? "visible" }) });
  const doc = Object.assign(new EventTarget(), { defaultView: win,
    getSelection: () => ({ isCollapsed: !doc.selected }), querySelector: () => doc.modal });
  const surface = Object.assign(new Element(), { ownerDocument: doc, parentElement: null, clientWidth: 1100, scrollWidth: 1100 });
  const moves = [];
  const state = { index: 1 };
  const cleanup = runInNewContext(`(${attachReaderWheel.toString()})`, { Element })(surface,
    direction => state.index + direction >= 0 && state.index + direction <= 4,
    direction => { moves.push(direction); state.index += direction; });
  const wheel = (deltaX, deltaY = 0, timeStamp = 100, extra = {}) => {
    const { target = surface, cancelable = true, ...fields } = extra;
    const e = new Event("wheel", { cancelable });
    const values = { target, deltaX, deltaY, deltaMode: 0, clientX: 600, clientY: 300, buttons: 0, timeStamp, ...fields };
    Object.defineProperties(e, Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { value }])));
    doc.dispatchEvent(e);
    if (surface.contains(target)) surface.dispatchEvent(e);
    return e;
  };
  return { viewport, win, doc, surface, moves, state, cleanup, wheel, Element };
}
let count = 0;
function check(name, run) {
  const f = fixture();
  try { run(f); count++; } catch (error) { throw new Error(name, { cause: error }); }
  finally { f.cleanup(); }
}
check("horizontal accumulation advances once despite momentum", f => {
  assert(f.wheel(40).defaultPrevented); f.wheel(60, 0, 130);
  for (const [time, dx] of [[160, 150], [210, 90], [350, 60], [580, 15], [810, 8]]) assert(f.wheel(dx, 0, time).defaultPrevented);
  assert.deepEqual(f.moves, [1]); assert.equal(f.state.index, 2);
  f.wheel(110, 0, 1200); assert.deepEqual(f.moves, [1, 1]);
});
check("negative horizontal delta goes back", f => { f.wheel(-110); assert.deepEqual(f.moves, [-1]); });
check("small stroke stays on current scene", f => { f.wheel(30); f.wheel(20, 0, 150); assert.deepEqual(f.moves, []); });
check("separate small strokes do not accumulate", f => { f.wheel(60); f.wheel(60, 0, 500); assert.deepEqual(f.moves, []); });
check("slow stroke is not paging", f => { f.wheel(30); f.wheel(30, 0, 300); f.wheel(30, 0, 510); f.wheel(40, 0, 620); assert.deepEqual(f.moves, []); });
check("minimum interval rejects separated momentum", f => { f.wheel(110); f.wheel(110, 0, 450); assert.deepEqual(f.moves, [1]); f.wheel(-110, 0, 900); assert.deepEqual(f.moves, [1, -1]); });
for (const [name, dx, dy] of [["vertical", 2, 80], ["diagonal", 50, 40]]) check(name + " onset locks native direction", f => {
  assert(!f.wheel(dx, dy).defaultPrevented); assert(!f.wheel(150, 0, 150).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("direction reversal cancels an incomplete stroke", f => { f.wheel(60); assert(!f.wheel(-100, 0, 150).defaultPrevented); assert.deepEqual(f.moves, []); });
check("vertical input stays native after a scene turn", f => { f.wheel(110); assert(!f.wheel(0, 90, 150).defaultPrevented); assert.deepEqual(f.moves, [1]); });
for (const key of ["ctrlKey", "metaKey", "altKey", "shiftKey", "buttons"]) check(key + " remains native", f => {
  assert(!f.wheel(150, 0, 100, { [key]: 1 }).defaultPrevented); f.wheel(150, 0, 150); assert.deepEqual(f.moves, []);
});
for (const deltaMode of [1, 2]) check("nonpixel wheel mode " + deltaMode, f => { assert(!f.wheel(150, 0, 100, { deltaMode }).defaultPrevented); assert.deepEqual(f.moves, []); });
check("noncancelable wheel does not navigate", f => { f.wheel(150, 0, 100, { cancelable: false }); assert.deepEqual(f.moves, []); });
check("coarse pointer retains native behavior", f => { f.win.coarse = true; assert(!f.wheel(150).defaultPrevented); assert.deepEqual(f.moves, []); });
for (const index of [0, 4]) check("boundary " + index + " remains native", f => {
  f.state.index = index; assert(!f.wheel(index ? 150 : -150).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("canvas link is allowed but nested links are native", f => {
  f.surface.control = f.surface; f.wheel(110); assert.deepEqual(f.moves, [1]);
  const target = Object.assign(new f.Element(), { parentElement: f.surface }); target.control = target;
  assert(!f.wheel(150, 0, 1000, { target }).defaultPrevented); assert.deepEqual(f.moves, [1]);
});
check("nested horizontal scroller remains native at its edge", f => {
  const target = Object.assign(new f.Element(), { parentElement: f.surface, clientWidth: 200, scrollWidth: 600, scrollLeft: 400, overflowX: "auto" });
  assert(!f.wheel(150, 0, 100, { target }).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("whole-document horizontal overflow stays native", f => {
  f.doc.scrollingElement = { scrollWidth: 1600, clientWidth: 1440 }; assert(!f.wheel(150).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("stroke starting outside canvas cannot enter midway", f => {
  f.wheel(30, 0, 100, { target: new f.Element() }); assert(!f.wheel(150, 0, 140).defaultPrevented); assert.deepEqual(f.moves, []);
});
for (const coords of [{ clientX: 10 }, { clientY: 50 }]) check("browser edge/outside artwork remains native " + JSON.stringify(coords), f => {
  assert(!f.wheel(150, 0, 100, coords).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("pointer drag does not become navigation", f => {
  f.doc.dispatchEvent(new Event("pointerdown")); assert(!f.wheel(150).defaultPrevented);
  f.doc.dispatchEvent(new Event("pointerup")); f.wheel(150, 0, 180); assert.deepEqual(f.moves, []);
});
for (const name of ["selection", "modal", "zoom"]) check(name + " stays native", f => {
  if (name === "selection") f.doc.selected = true;
  if (name === "modal") f.doc.modal = {};
  if (name === "zoom") f.viewport.scale = 2;
  assert(!f.wheel(150).defaultPrevented); assert.deepEqual(f.moves, []);
});
for (const [owner, event] of [["doc", "scroll"], ["doc", "keydown"], ["win", "popstate"], ["win", "hashchange"], ["win", "blur"], ["win", "pagehide"], ["viewport", "resize"]]) check(event + " cancels pending input", f => {
  f.wheel(50); f[owner].dispatchEvent(new Event(event)); f.wheel(150, 0, 150); assert.deepEqual(f.moves, []);
});
check("navigation scroll does not release the momentum lock", f => {
  f.wheel(110); f.doc.dispatchEvent(new Event("scroll")); assert(f.wheel(150, 0, 150).defaultPrevented); assert.deepEqual(f.moves, [1]);
});
check("cleanup removes recognition and native cancellation", f => {
  f.wheel(30); f.cleanup(); assert(!f.wheel(150, 0, 150).defaultPrevented); assert.deepEqual(f.moves, []);
});
console.log(`Reader wheel: ${count} direction, native-input, momentum and cleanup contracts passed.`);
