// Native bridge contract: exact digest before sandboxed script execution.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const html = readFileSync(new URL("../public/benchmarks/terminal-bench/replay.html", import.meta.url), "utf8");
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
assert.match(script, /geode-eval-artifacts\/[a-f0-9]{40}\/terminal-bench\//);
assert.match(script, /const expected = '[a-f0-9]{64}'/);
assert.ok(!script.includes("allow-same-origin"));
const fixture = new TextEncoder().encode("<html>public fixture</html>");
const digest = Buffer.from(await webcrypto.subtle.digest("SHA-256", fixture)).toString("hex");

async function run({ corrupt = false, offline = false } = {}) {
  const frames = [];
  const status = {};
  let requested;
  const context = {
    TextDecoder, Uint8Array, Array, crypto: webcrypto, AbortSignal,
    document: {
      getElementById: () => status,
      body: { append: frame => frames.push(frame) },
      createElement: tag => ({ tag, setAttribute(name, value) { this[name] = value; } }),
    },
    fetch: async (url, options) => {
      requested = { url, options };
      return { ok: !offline, arrayBuffer: async () => corrupt ? new Uint8Array([0]).buffer : fixture.buffer };
    },
  };
  // Keep production control flow; only replace the pinned digest with a small fixture.
  const fixtureScript = script.replace(/const expected = '[a-f0-9]{64}'/, `const expected = '${digest}'`);
  await vm.runInNewContext(`(async () => {${fixtureScript}})()`, context);
  assert.equal(requested.options.credentials, "omit");
  assert.ok(requested.options.signal);
  if (corrupt || offline) {
    assert.equal(frames.length, 0);
    assert.match(status.textContent, /Replay blocked/);
  } else {
    assert.equal(frames.length, 1);
    assert.equal(frames[0].tag, "iframe");
    assert.equal(frames[0].sandbox, "allow-scripts");
    assert.equal(frames[0].srcdoc, new TextDecoder().decode(fixture));
    assert.equal(status.textContent, "SHA-256 verified.");
  }
}

await run();
await run({ corrupt: true });
await run({ offline: true });
console.log("Terminal replay bridge: digest pass, corruption rejection, fetch rejection, sandbox PASS");
