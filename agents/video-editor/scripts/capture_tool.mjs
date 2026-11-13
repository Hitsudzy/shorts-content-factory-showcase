#!/usr/bin/env node
// CF-0567: the browser half of the own-capture recorder (capture_tool.py).
// One public page, one recording, then exit. Everything that is policy -
// the channel's capture host, robots.txt of the exact host, no sign-in, the
// Space's licence, the duration cap - is decided in capture_tool.py before
// this is ever started; this file only does what a browser does: open the
// page signed out (a fresh profile, no stored state), wait for it to settle, start
// a screencast, play the small script of steps, stop.
//
// Backend: the chrome-headless-shell Remotion installs (as capture_page.mjs),
// over the DevTools protocol through Node's built-in WebSocket. Frames come
// from Page.startScreencast as JPEGs into --frames-dir, each with the wall
// time it arrived; capture_tool.py assembles them into the mp4 with ffmpeg.
// A screencast sends a frame only when the picture changes, so a frame lasts
// until the next one (and the last until the stop).
//
// Steps (a JSON list, validated by capture_tool.py):
//   {"do": "wait", "seconds": 2}
//   {"do": "scroll", "by": 600, "seconds": 1.5}            smooth, in CSS px
//   {"do": "click", "selector": "button#run"}
//   {"do": "type", "selector": "textarea", "text": "a red fox", "delay_ms": 60}
//   {"do": "press", "key": "Enter"}                         Enter | Tab
//   {"do": "wait_for", "selector": ".result img", "seconds": 20}
// Nothing is typed into a password field, nothing is accepted, nothing is
// hidden or injected: the page is recorded as it is.
//
// Usage:
//   node capture_tool.mjs --chrome <bin> --url <url> --frames-dir <dir>
//        [--steps <steps.json>] [--max-seconds 30] [--tail 1.0]
//        [--user-agent <ua>] [--timeout 30] [--width 540] [--height 960]
//        [--scale 2] [--quality 85]
// Prints one JSON line: {ok, reason, detail, status, final_url, frames,
// duration_s, capped, steps_done, width, height}. Exit 0 whenever a verdict
// was reached; non-zero only when the browser itself could not be run.
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
}
const CHROME = args.chrome;
const URL_ = args.url;
const FRAMES = args['frames-dir'];
const STEPS = args.steps ? JSON.parse(readFileSync(args.steps, 'utf8')) : [];
const MAX_MS = Math.round(parseFloat(args['max-seconds'] || '30') * 1000);
const TAIL_MS = Math.round(parseFloat(args.tail || '1.0') * 1000);
const UA = args['user-agent'] || 'shorts-content-factory/video-editor (personal research tool)';
const TIMEOUT_MS = Math.round(parseFloat(args.timeout || '30') * 1000);
const WIDTH = parseInt(args.width || '540', 10);
const HEIGHT = parseInt(args.height || '960', 10);
const SCALE = parseFloat(args.scale || '2');
const QUALITY = parseInt(args.quality || '85', 10);
const IDLE_MS = 500;

const emit = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!CHROME || !URL_ || !FRAMES) {
  process.stderr.write('capture_tool.mjs: --chrome, --url and --frames-dir are required\n');
  process.exit(2);
}

const profile = mkdtempSync(join(tmpdir(), 'own-capture-'));
const chrome = spawn(CHROME, [
  '--headless',
  '--remote-debugging-port=0',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-gpu',
  '--disable-extensions',
  '--disable-sync',
  '--disable-background-networking',
  '--mute-audio',
  '--hide-scrollbars',
  `--user-agent=${UA}`,
  `--window-size=${WIDTH},${HEIGHT}`,
  `--force-device-scale-factor=${SCALE}`,
  `--user-data-dir=${profile}`,
  'about:blank',
], {stdio: ['ignore', 'ignore', 'pipe']});

let done = false;
const finish = (code) => {
  if (done) return;
  done = true;
  try { chrome.kill('SIGKILL'); } catch {}
  try { rmSync(profile, {recursive: true, force: true}); } catch {}
  process.exit(code);
};
process.on('SIGTERM', () => finish(1));
process.on('SIGINT', () => finish(1));

// The whole run: the load, the recording and a margin.
const hardStop = setTimeout(() => { emit({ok: false, reason: 'timeout'}); finish(0); },
  TIMEOUT_MS + MAX_MS + 10000);

const devtoolsUrl = await new Promise((resolve, reject) => {
  let buf = '';
  chrome.stderr.on('data', (d) => {
    buf += d.toString();
    const m = buf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
    if (m) resolve(m[1]);
  });
  chrome.on('exit', (code) => reject(new Error(`chrome exited (${code}) before listening: ${buf.slice(-400)}`)));
  setTimeout(() => reject(new Error('chrome did not start listening in time')), 15000);
}).catch((e) => {
  process.stderr.write(`capture_tool.mjs: ${e.message}\n`);
  finish(3);
});

const port = new URL(devtoolsUrl).port;
const targets = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = targets.find((t) => t.type === 'page');
if (!page) { process.stderr.write('capture_tool.mjs: no page target\n'); finish(3); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

let nextId = 1;
const pending = new Map();
const listeners = [];
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const {resolve, reject} = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
  } else if (msg.method) {
    for (const l of listeners) l(msg.method, msg.params || {});
  }
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, {resolve, reject});
  ws.send(JSON.stringify({id, method, params}));
});
const on = (fn) => listeners.push(fn);
const evaluate = async (expression) => {
  const r = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'evaluate failed');
  return r.result.value;
};

const inflight = new Set();
let loaded = false;
let docStatus = null;
let docUrl = null;
let mainFrameId = null;
let navLoaderId = null;
on((method, p) => {
  if (method === 'Network.requestWillBeSent') inflight.add(p.requestId);
  if (method === 'Network.loadingFinished' || method === 'Network.loadingFailed') inflight.delete(p.requestId);
  if (method === 'Network.responseReceived' && p.type === 'Document'
      && p.frameId === mainFrameId && (navLoaderId === null || p.loaderId === navLoaderId)) {
    docStatus = p.response.status;
    docUrl = p.response.url;
  }
  if (method === 'Page.loadEventFired') loaded = true;
});

// --- the screencast: every frame to a file, with the wall time it arrived
const frames = [];
let recording = false;
on((method, p) => {
  if (method !== 'Page.screencastFrame') return;
  send('Page.screencastFrameAck', {sessionId: p.sessionId}).catch(() => {});
  if (!recording) return;
  const file = `f${String(frames.length).padStart(5, '0')}.jpg`;
  writeFileSync(join(FRAMES, file), Buffer.from(p.data, 'base64'));
  frames.push({file, t: Date.now() / 1000});
});

const center = async (selector) => evaluate(`(() => {
  const el = document.querySelector(${JSON.stringify(selector)});
  if (!el) return null;
  el.scrollIntoView({block: 'center', inline: 'center'});
  const r = el.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2,
          password: (el.getAttribute('type') || '').toLowerCase() === 'password'
                    || el.getAttribute('autocomplete') === 'current-password'};
})()`);

const click = async (selector) => {
  const c = await center(selector);
  if (!c) throw new Error(`no element ${selector}`);
  await sleep(150);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await send('Input.dispatchMouseEvent', {type, x: c.x, y: c.y, button: 'left', clickCount: 1});
  }
  return c;
};

const KEYS = {Enter: {code: 'Enter', windowsVirtualKeyCode: 13, text: '\r'},
              Tab: {code: 'Tab', windowsVirtualKeyCode: 9}};

const runStep = async (step, untilMs) => {
  const left = () => Math.max(0, untilMs - Date.now());
  switch (step.do) {
    case 'wait':
      await sleep(Math.min(left(), Math.round((step.seconds || 0) * 1000)));
      return null;
    case 'scroll': {
      const total = Number(step.by || 0);
      const ms = Math.min(left(), Math.round((step.seconds || 1) * 1000));
      const n = Math.max(1, Math.round(ms / 40));
      for (let i = 0; i < n; i++) {
        await evaluate(`window.scrollBy(0, ${total / n})`);
        await sleep(ms / n);
      }
      return null;
    }
    case 'click':
      await click(step.selector);
      return null;
    case 'type': {
      const c = await center(step.selector);
      if (!c) throw new Error(`no element ${step.selector}`);
      if (c.password) throw new Error('refused: a password field is never typed into');
      await click(step.selector);
      const delay = Number(step.delay_ms ?? 60);
      for (const ch of String(step.text || '')) {
        if (left() <= 0) break;
        await send('Input.insertText', {text: ch});
        await sleep(delay);
      }
      return null;
    }
    case 'press': {
      const k = KEYS[step.key];
      if (!k) throw new Error(`key ${step.key} is not one the recorder presses`);
      await send('Input.dispatchKeyEvent', {type: 'keyDown', key: step.key, ...k});
      await send('Input.dispatchKeyEvent', {type: 'keyUp', key: step.key, code: k.code,
                                           windowsVirtualKeyCode: k.windowsVirtualKeyCode});
      return null;
    }
    case 'wait_for': {
      const until = Date.now() + Math.min(left(), Math.round((step.seconds || 10) * 1000));
      while (Date.now() < until) {
        const found = await evaluate(`!!document.querySelector(${JSON.stringify(step.selector)})`);
        if (found) return null;
        await sleep(100);
      }
      throw new Error(`${step.selector} did not appear`);
    }
    default:
      throw new Error(`unknown step ${step.do}`);
  }
};

try {
  await send('Network.enable');
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.setUserAgentOverride', {userAgent: UA});
  await send('Emulation.setDeviceMetricsOverride',
    {width: WIDTH, height: HEIGHT, deviceScaleFactor: SCALE, mobile: true});
  const tree = await send('Page.getFrameTree');
  mainFrameId = tree.frameTree.frame.id;

  const loadDeadline = Date.now() + TIMEOUT_MS;
  const nav = await send('Page.navigate', {url: URL_});
  if (nav.errorText) { emit({ok: false, reason: 'navigation_error', detail: nav.errorText}); finish(0); }
  navLoaderId = nav.loaderId || null;

  let idleSince = null;
  for (;;) {
    if (Date.now() > loadDeadline) break;
    if (loaded && inflight.size === 0) {
      if (idleSince === null) idleSince = Date.now();
      else if (Date.now() - idleSince >= IDLE_MS) break;
    } else {
      idleSince = null;
    }
    await sleep(50);
  }
  if (!loaded) { emit({ok: false, reason: 'timeout', status: docStatus, final_url: docUrl}); finish(0); }
  if (docStatus !== 200) {
    emit({ok: false, reason: `http_${docStatus ?? 'none'}`, status: docStatus, final_url: docUrl});
    finish(0);
  }

  await send('Page.startScreencast', {format: 'jpeg', quality: QUALITY,
    maxWidth: Math.round(WIDTH * SCALE), maxHeight: Math.round(HEIGHT * SCALE), everyNthFrame: 1});
  recording = true;
  const startedAt = Date.now();
  const untilMs = startedAt + MAX_MS;
  // A page that does not change sends no frame: ask for one at the start.
  await sleep(200);

  const stepsDone = [];
  let failure = null;
  for (const [i, step] of STEPS.entries()) {
    if (Date.now() >= untilMs) break;
    try {
      await runStep(step, untilMs);
      stepsDone.push({index: i, do: step.do, ok: true, at_s: +((Date.now() - startedAt) / 1000).toFixed(3)});
    } catch (e) {
      stepsDone.push({index: i, do: step.do, ok: false, detail: e.message});
      failure = e.message;
      break;
    }
  }
  if (!failure) await sleep(Math.min(TAIL_MS, Math.max(0, untilMs - Date.now())));
  const stoppedAt = Date.now();
  recording = false;
  await send('Page.stopScreencast').catch(() => {});
  const finalUrl = await evaluate('location.href').catch(() => docUrl);
  const capped = stoppedAt >= untilMs - 5 && stepsDone.length < STEPS.length;
  writeFileSync(join(FRAMES, 'frames.json'),
    JSON.stringify({frames, started_at: startedAt / 1000, stopped_at: stoppedAt / 1000}));
  const common = {status: docStatus, final_url: finalUrl, frames: frames.length,
                  duration_s: +((stoppedAt - startedAt) / 1000).toFixed(3), capped,
                  steps_done: stepsDone, width: Math.round(WIDTH * SCALE),
                  height: Math.round(HEIGHT * SCALE)};
  if (failure) emit({ok: false, reason: 'step_failed', detail: failure, ...common});
  else if (!frames.length) emit({ok: false, reason: 'no_frames', ...common});
  else emit({ok: true, reason: null, ...common});
  clearTimeout(hardStop);
  finish(0);
} catch (e) {
  process.stderr.write(`capture_tool.mjs: ${e.message}\n`);
  emit({ok: false, reason: 'browser_error', detail: e.message});
  finish(0);
}
