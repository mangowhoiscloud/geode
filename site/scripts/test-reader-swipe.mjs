/** Deterministic gesture boundaries; native browser touch is verified separately. */
import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import { attachReaderSwipe } from "../src/lib/reader-swipe.mjs";

function fixture() {
  class Element extends EventTarget { closest() { return this.control ?? null; } }
  const viewport = Object.assign(new EventTarget(), { scale: 1 });
  const win = Object.assign(new EventTarget(), { innerWidth: 390, visualViewport: viewport, performance });
  const doc = Object.assign(new EventTarget(), { defaultView: win, getSelection: () => ({ isCollapsed: !doc.selected }), querySelector: () => doc.modal });
  const surface = Object.assign(new Element(), { ownerDocument: doc, style: { touchAction: "" }, clientWidth: 358 });
  const moves = [];
  const cleanup = runInNewContext(`(${attachReaderSwipe.toString()})`, { Element })(surface, direction => moves.push(direction));
  const touch = (x, y = 200, identifier = 1) => ({ clientX: x, clientY: y, identifier });
  const emit = (type, touches, timeStamp = 100, changedTouches = touches, target = surface) => {
    const e = new Event(type, { cancelable: true });
    Object.defineProperties(e, { touches: { value: touches }, changedTouches: { value: changedTouches }, timeStamp: { value: timeStamp }, target: { value: target } });
    if (type === "touchstart") doc.dispatchEvent(e);
    surface.dispatchEvent(e);
    return e;
  };
  const start = () => emit("touchstart", [touch(290)]);
  const finish = () => emit("touchend", [], 300, [touch(120)]);
  const swipe = () => { start(); emit("touchmove", [touch(120)], 200); return finish(); };
  return { viewport, win, doc, surface, moves, cleanup, touch, emit, start, finish, swipe, Element };
}

let count = 0;
function check(name, run) {
  const f = fixture();
  try { run(f); count++; } catch (error) { throw new Error(name, { cause: error }); }
  finally { f.cleanup(); }
}
check("left advances once and cancels image activation", f => {
  assert(f.swipe().defaultPrevented); f.finish(); assert.deepEqual(f.moves, [1]);
});
check("right moves back", f => {
  f.emit("touchstart", [f.touch(100)]); f.emit("touchmove", [f.touch(250)], 200); f.emit("touchend", [], 300, [f.touch(250)]); assert.deepEqual(f.moves, [-1]);
});
check("tap remains a native image link", f => {
  f.start(); assert(!f.emit("touchend", [], 200, [f.touch(291)]).defaultPrevented); assert.deepEqual(f.moves, []);
});
check("short drag does not change scenes", f => {
  f.start(); f.emit("touchend", [], 200, [f.touch(250)]); assert.deepEqual(f.moves, []);
});
check("vertical onset cannot turn into navigation", f => {
  f.start(); assert(!f.emit("touchmove", [f.touch(285, 170)], 150).defaultPrevented); f.finish(); assert.deepEqual(f.moves, []);
});
check("diagonal release cancels", f => {
  f.start(); f.emit("touchend", [], 200, [f.touch(120, 330)]); assert.deepEqual(f.moves, []);
});
check("long press is not a swipe", f => {
  f.start(); f.emit("touchmove", [f.touch(120)], 900); f.finish(); assert.deepEqual(f.moves, []);
});
check("multitouch cancels the whole sequence", f => {
  f.start(); f.emit("touchstart", [f.touch(290), f.touch(90, 200, 2)], 150); f.finish(); assert.deepEqual(f.moves, []);
});
check("nested controls retain gestures", f => {
  const target = new f.Element(); target.control = target;
  f.emit("touchstart", [f.touch(290)], 100, [], target); f.finish(); assert.deepEqual(f.moves, []);
});
check("canvas anchor allows both swipe and tap", f => {
  f.surface.control = f.surface; f.swipe(); assert.deepEqual(f.moves, [1]);
});
for (const event of ["touchcancel", "contextmenu"]) check(event, f => {
  f.start(); f.surface.dispatchEvent(new Event(event)); f.finish(); assert.deepEqual(f.moves, []);
});
for (const event of ["blur", "pagehide", "popstate", "hashchange"]) check(event, f => {
  f.start(); f.win.dispatchEvent(new Event(event)); f.finish(); assert.deepEqual(f.moves, []);
});
check("scroll cancels", f => { f.start(); f.doc.dispatchEvent(new Event("scroll")); f.finish(); assert.deepEqual(f.moves, []); });
check("selection cancels and is preserved", f => { f.start(); f.doc.selected = true; f.doc.dispatchEvent(new Event("selectionchange")); f.finish(); assert.deepEqual(f.moves, []); assert(f.doc.selected); });
check("modal prevents navigation", f => { f.doc.modal = {}; f.swipe(); assert.deepEqual(f.moves, []); });
check("pinch and zoomed panning stay native", f => {
  assert.equal(f.surface.style.touchAction, "pan-y pinch-zoom");
  f.start(); f.viewport.scale = 2; f.viewport.dispatchEvent(new Event("resize")); f.finish(); f.swipe();
  assert.equal(f.surface.style.touchAction, "auto"); assert.deepEqual(f.moves, []);
  f.viewport.scale = 1; f.viewport.dispatchEvent(new Event("resize")); f.swipe(); assert.deepEqual(f.moves, [1]);
});
check("edge navigation remains browser-owned", f => { f.emit("touchstart", [f.touch(10)]); f.finish(); assert.deepEqual(f.moves, []); });
check("cleanup restores native behavior", f => { f.start(); f.cleanup(); f.finish(); f.swipe(); assert.equal(f.surface.style.touchAction, ""); assert.deepEqual(f.moves, []); });
console.log(`Reader swipe: ${count} gesture and cleanup contracts passed.`);
