#!/usr/bin/env node
// CF-0071: the browser half of headless_browser (inserts/proof.json
// capture_methods[headless_browser].behaviour). One page, one capture, then
// exit. Everything that is policy - which hosts, robots.txt, the per-host
// rate and budget, one attempt per URL - is decided in capture_page.py
// before this is ever started; this file only does what a browser does:
// open the page signed out, wait for it to settle, hide the overlays, find
// the headline, screenshot the header.
//
// Backend: the chrome-headless-shell Remotion already installs under
// render/node_modules/.remotion (no new browser dependency), driven over
// the DevTools protocol through Node's built-in WebSocket. No puppeteer,
// no ws package: the protocol calls needed are eleven.
//
// Usage:
//   node capture_page.mjs --chrome <binary> --url <url> --out <png>
//        [--region article_header|article_header_with_standfirst|viewport]
//        [--user-agent <ua>] [--timeout 20] [--max-height 1400]
//        [--width 640] [--height 1136] [--scale 2]
// Prints one JSON line: {ok, reason, status, final_url, h1_text, standfirst_text,
// region, clip, width, height}. standfirst_text is the standfirst element's
// textContent when the region is article_header_with_standfirst, else null. Exit 0 whenever a verdict was reached (ok true or
// false); non-zero only when the browser itself could not be run.
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
}
const CHROME = args.chrome;
const URL_ = args.url;
const OUT = args.out;
const REGION = args.region || 'article_header';
const UA = args['user-agent'] || 'shorts-content-factory/video-editor (personal research tool)';
const TIMEOUT_MS = Math.round(parseFloat(args.timeout || '20') * 1000);
const MAX_HEIGHT_PX = parseInt(args['max-height'] || '1400', 10);
const WIDTH = parseInt(args.width || '640', 10);
const HEIGHT = parseInt(args.height || '1136', 10);
const SCALE = parseFloat(args.scale || '2');
const IDLE_MS = 500;

const emit = (obj) => process.stdout.write(JSON.stringify(obj) + '\n');
const fail = (reason, extra = {}) => emit({ok: false, reason, region: REGION, ...extra});

if (!CHROME || !URL_ || !OUT) {
  process.stderr.write('capture_page.mjs: --chrome, --url and --out are required\n');
  process.exit(2);
}

const profile = mkdtempSync(join(tmpdir(), 'proof-capture-'));
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

const deadline = Date.now() + TIMEOUT_MS;
const hardStop = setTimeout(() => { fail('timeout'); finish(0); }, TIMEOUT_MS + 5000);

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
  process.stderr.write(`capture_page.mjs: ${e.message}\n`);
  finish(3);
});

// The browser endpoint tells us the port; the page target comes from /json.
const port = new URL(devtoolsUrl).port;
const targets = await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json());
const page = targets.find((t) => t.type === 'page');
if (!page) { process.stderr.write('capture_page.mjs: no page target\n'); finish(3); }

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

// --- what a network-idle wait needs: the in-flight set and the document response
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

try {
  await send('Network.enable');
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.setUserAgentOverride', {userAgent: UA});
  await send('Emulation.setDeviceMetricsOverride',
    {width: WIDTH, height: HEIGHT, deviceScaleFactor: SCALE, mobile: true});
  const tree = await send('Page.getFrameTree');
  mainFrameId = tree.frameTree.frame.id;

  const nav = await send('Page.navigate', {url: URL_});
  if (nav.errorText) { fail('navigation_error', {detail: nav.errorText}); finish(0); }
  navLoaderId = nav.loaderId || null;

  // DOM loaded and the network idle, up to the deadline. Nothing is
  // scrolled, clicked, typed or accepted.
  let idleSince = null;
  let timedOut = false;
  for (;;) {
    if (Date.now() > deadline) { timedOut = true; break; }
    if (loaded && inflight.size === 0) {
      if (idleSince === null) idleSince = Date.now();
      else if (Date.now() - idleSince >= IDLE_MS) break;
    } else {
      idleSince = null;
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  if (timedOut && !loaded) { fail('timeout', {status: docStatus, final_url: docUrl}); finish(0); }
  if (docStatus !== 200) { fail(`http_${docStatus ?? 'none'}`, {status: docStatus, final_url: docUrl}); finish(0); }

  // Hide fixed overlays (consent banners, newsletter prompts, modals) by
  // injected CSS - hidden, never clicked or accepted - and measure the
  // header region off the DOM: the first visible <h1>, its dateline, and
  // for the standfirst region the first paragraph after it.
  const measure = await send('Runtime.evaluate', {
    returnByValue: true,
    expression: `(() => {
      const vh = window.innerHeight;
      const style = document.createElement('style');
      style.textContent = 'html, body { overflow: visible !important; } ' +
        'dialog[open], [role="dialog"], [aria-modal="true"] { display: none !important; }';
      document.documentElement.appendChild(style);
      for (const el of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(el);
        if (cs.position !== 'fixed') continue;
        const r = el.getBoundingClientRect();
        // a fixed masthead at the very top stays; anything else fixed is an overlay
        const masthead = r.top <= 1 && r.height < vh * 0.25;
        if (!masthead) el.style.setProperty('display', 'none', 'important');
      }
      const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const h1 = [...document.querySelectorAll('h1')].find(visible);
      if (!h1) return {h1: null};
      const hr = h1.getBoundingClientRect();
      let bottom = hr.bottom;
      // The lowest-reaching visible element of sel whose top sits within
      // within CSS px under the headline: {bottom, text} or null.
      const after = (sel, within) => {
        let best = null;
        for (const el of document.querySelectorAll(sel)) {
          if (!visible(el)) continue;
          const r = el.getBoundingClientRect();
          if (r.top >= hr.bottom - 4 && r.top <= hr.bottom + within && (!best || r.bottom > best.bottom))
            best = {bottom: r.bottom, text: (el.textContent || '').trim().slice(0, 600)};
        }
        return best;
      };
      const dateline = after('time, [datetime], [class*="date" i], [class*="byline" i], [class*="author" i]', 320);
      if (dateline) bottom = Math.max(bottom, dateline.bottom);
      let standfirst = null;
      if (${JSON.stringify(REGION)} === 'article_header_with_standfirst') {
        standfirst = after('[class*="standfirst" i], [class*="dek" i], [class*="subhead" i], [class*="summary" i], h2, p', 420);
        if (standfirst) bottom = Math.max(bottom, standfirst.bottom);
      }
      return {h1: (h1.textContent || h1.innerText || '').trim().slice(0, 300), h1_top: hr.top, h1_bottom: hr.bottom,
              dateline: dateline ? dateline.bottom : null,
              standfirst: standfirst ? standfirst.bottom : null,
              standfirst_text: standfirst ? standfirst.text : null, bottom, vh};
    })()`,
  });
  const m = measure.result.value || {};
  if (!m.h1) { fail('no_h1', {status: docStatus, final_url: docUrl}); finish(0); }

  const maxCss = Math.floor(MAX_HEIGHT_PX / SCALE);
  let clipBottom = REGION === 'viewport' ? m.vh : m.bottom;
  clipBottom = Math.min(Math.ceil(clipBottom), maxCss);
  if (m.h1_bottom > maxCss) {
    fail('headline_below_region_max', {status: docStatus, final_url: docUrl, h1_text: m.h1});
    finish(0);
  }
  const clip = {x: 0, y: 0, width: WIDTH, height: Math.max(1, clipBottom), scale: 1};
  const shot = await send('Page.captureScreenshot', {format: 'png', clip, captureBeyondViewport: false});
  writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
  emit({ok: true, reason: null, status: docStatus, final_url: docUrl, h1_text: m.h1,
        standfirst_text: m.standfirst_text || null, region: REGION, clip, width: Math.round(clip.width * SCALE), height: Math.round(clip.height * SCALE)});
  clearTimeout(hardStop);
  finish(0);
} catch (e) {
  process.stderr.write(`capture_page.mjs: ${e.message}\n`);
  fail('browser_error', {detail: e.message});
  finish(0);
}
