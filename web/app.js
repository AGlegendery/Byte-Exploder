// Byte Exploder — By AGlegend (https://github.com/AGlegendery)
// Page logic for the webview UI. Python side: web_api.py (window.pywebview.api).
// Strings live in i18n.js; every piece of visible text is kept as a function
// so switching the language re-renders it.
"use strict";

const $ = (id) => document.getElementById(id);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const scrollOpts = { block: "nearest", behavior: reducedMotion ? "auto" : "smooth" };
const METER_TILES = 32;
const TEXT_PREVIEW_MAX_SIDE = 1024;
const BLOCK_SIZES = [8, 12, 16, 24, 32, 48, 64];

let numFmt = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const num = (n) => numFmt.format(n);

function fmtBytes(n) {
  if (n < 1024) return t("unit.bytes", { n: num(n) });
  const units = t("unit.list").split("|");
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${num(v)} ${units[i]}`;
}

function splitPath(p) {
  const trimmed = p.replace(/[\\/]+$/, "");
  const i = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  return { dir: i >= 0 ? trimmed.slice(0, i) : "", name: trimmed.slice(i + 1) };
}

// Error objects from Python are {code, ...args}; anything else is shown as is.
function errText(err) {
  if (!err) return "";
  if (typeof err === "string") return err;
  const args = { ...err };
  for (const k of ["min", "max"]) if (typeof args[k] === "number") args[k] = num(args[k]);
  for (const k of ["size", "capacity"]) if (typeof args[k] === "number") args[k] = fmtBytes(args[k]);
  const key = `err.${err.code}`;
  return key in STRINGS.fa ? t(key, args) : (err.message || err.code);
}

let api = null;
const state = {
  tab: "enc",
  kind: "file",
  encPath: "",
  decImage: "",
  decKey: "",
  job: null,
  views: { enc: null, dec: null }, // what the canvas shows for each tab
  status: { text: () => t("status.ready"), error: false },
  keyhint: null,
  notices: {},
  photoCap: 12731, // replaced by the engine's value in init()
  photoUsage: null,
};

// ------------------------------------------------------------------ canvas
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
let revealToken = 0;

function drawPixels(bytes, width, height) {
  // bytes are RGB triples in row-major order; missing bytes are zero (black)
  canvas.width = width;
  canvas.height = height;
  const img = ctx.createImageData(width, height);
  const d = img.data;
  const pixels = width * height;
  for (let i = 0, j = 0; i < pixels; i++, j += 3) {
    const o = i * 4;
    d[o] = bytes[j] || 0;
    d[o + 1] = bytes[j + 1] || 0;
    d[o + 2] = bytes[j + 2] || 0;
    d[o + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
}

// The engine stores [8-byte big-endian length][data] row-major in a square.
function engineLayout(data) {
  const raw = new Uint8Array(8 + data.length);
  let len = data.length;
  for (let k = 7; k >= 0; k--) { raw[k] = len % 256; len = Math.floor(len / 256); }
  raw.set(data, 8);
  const side = Math.ceil(Math.sqrt(Math.ceil(raw.length / 3)));
  return { raw, side };
}

function drawImageUrl(url, animate) {
  const token = ++revealToken;
  const im = new Image();
  im.onload = () => {
    if (token !== revealToken) return;
    canvas.width = im.naturalWidth;
    canvas.height = im.naturalHeight;
    if (!animate || reducedMotion) { ctx.drawImage(im, 0, 0); return; }
    mosaicReveal(im, token);
  };
  im.src = url;
}

// The one orchestrated moment: the scrambled image arrives block by block,
// in random order, the way the engine scrambles it.
function mosaicReveal(im, token) {
  const w = im.naturalWidth, h = im.naturalHeight;
  const b = Math.max(4, Math.round(Math.max(w, h) / 20));
  const cells = [];
  for (let y = 0; y < h; y += b) for (let x = 0; x < w; x += b) cells.push([x, y]);
  for (let i = cells.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [cells[i], cells[j]] = [cells[j], cells[i]];
  }
  const start = performance.now();
  const duration = 700;
  let done = 0;
  const step = (now) => {
    if (token !== revealToken) return;
    const target = Math.min(cells.length, Math.ceil(((now - start) / duration) * cells.length));
    for (; done < target; done++) {
      const [x, y] = cells[done];
      ctx.drawImage(im, x, y, b, b, x, y, b, b);
    }
    if (done < cells.length) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// view: {type: "idle" | "bytes" | "url", ..., caption: () => string}
function render(view, animate = false) {
  revealToken++;
  if (!view) view = idleView();
  if (view.type === "idle") {
    const { raw, side } = engineLayout(new TextEncoder().encode(t("idle.text")));
    drawPixels(raw, side, side);
  }
  if (view.type === "bytes") drawPixels(view.bytes, view.width, view.height);
  if (view.type === "url") drawImageUrl(view.url, animate);
  $("caption").textContent = view.caption();
}

function setView(tab, view, animate = false) {
  state.views[tab] = view;
  if (state.tab === tab) render(view, animate);
}

function idleView(caption) {
  return {
    type: "idle",
    caption: caption || (() => t(state.tab === "enc" ? "cap.idle_enc" : "cap.idle_dec")),
  };
}

function textView(text) {
  const data = new TextEncoder().encode(text);
  const { raw, side } = engineLayout(data);
  const rows = Math.min(side, TEXT_PREVIEW_MAX_SIDE);
  const cols = Math.min(side, TEXT_PREVIEW_MAX_SIDE);
  let bytes = raw;
  if (cols < side) { // keep the top-left corner of very long texts
    bytes = new Uint8Array(rows * cols * 3);
    for (let r = 0; r < rows; r++) bytes.set(raw.subarray(r * side * 3, r * side * 3 + cols * 3), r * cols * 3);
  }
  return {
    type: "bytes", bytes, width: cols, height: rows,
    caption: () => (text ? t("cap.text", { w: num(side) }) : t("cap.text_empty")),
  };
}

function headView(info) {
  const bytes = Uint8Array.from(atob(info.head), (c) => c.charCodeAt(0));
  const side = Math.max(1, Math.ceil(Math.sqrt(Math.ceil(bytes.length / 3))));
  return {
    type: "bytes", bytes, width: side, height: side,
    caption: () => t(bytes.length < info.size ? "cap.head_part" : "cap.head_all", {
      size: fmtBytes(bytes.length), name: info.name, total: fmtBytes(info.size),
    }),
  };
}

// ------------------------------------------------------------------ status bar
const meter = $("meter");
for (let i = 0; i < METER_TILES; i++) meter.appendChild(document.createElement("i"));

function setProgress(p, mode = "") {
  const on = Math.round((Math.max(0, Math.min(100, p)) / 100) * METER_TILES);
  [...meter.children].forEach((tile, i) => tile.classList.toggle("on", i < on));
  meter.classList.toggle("is-done", mode === "done");
  meter.classList.toggle("is-error", mode === "error");
  meter.setAttribute("aria-valuenow", String(Math.round(p)));
}

function setStatus(text, error = false) {
  state.status = { text, error };
  renderStatus();
}

function renderStatus() {
  const s = $("status");
  s.textContent = state.status.text();
  s.classList.toggle("is-error", state.status.error);
}

function phaseKey(kind, p) {
  if (kind === "enc") return p < 10 ? "status.enc_read" : p < 80 ? "status.enc_scramble" : "status.enc_write";
  return p < 10 ? "status.dec_read" : "status.dec_restore";
}

const log = $("log");
function appendLog(lines) {
  if (!lines.length) return;
  log.textContent += lines.join("\n") + "\n";
  log.scrollTop = log.scrollHeight;
}

$("btn-log").addEventListener("click", () => {
  const open = log.hidden;
  log.hidden = !open;
  $("btn-log").setAttribute("aria-expanded", String(open));
});

// ------------------------------------------------------------------ notices
// spec: {title: () => string, lines: [[labelKey, value]], error, action: {labelKey, run}}
function notice(id, spec, scroll = true) {
  state.notices[id] = spec;
  const box = $(id);
  box.replaceChildren();
  box.classList.toggle("is-error", !!spec.error);
  box.setAttribute("role", spec.error ? "alert" : "status");
  const title = document.createElement("span");
  title.className = "notice-title";
  title.textContent = spec.title();
  box.appendChild(title);
  for (const [labelKey, value] of spec.lines || []) {
    const line = document.createElement("span");
    line.className = "notice-line";
    line.append(t(labelKey) + " ");
    const v = document.createElement("bdi");
    v.textContent = typeof value === "function" ? value() : value;
    line.appendChild(v);
    box.appendChild(line);
  }
  if (spec.note) {
    const note = document.createElement("span");
    note.className = "notice-line";
    note.textContent = spec.note();
    box.appendChild(note);
  }
  if (spec.action) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn";
    b.textContent = t(spec.action.labelKey);
    b.addEventListener("click", spec.action.run);
    box.appendChild(b);
  }
  box.hidden = false;
  if (scroll) box.scrollIntoView(scrollOpts);
}

function errorNotice(id, err) {
  notice(id, { title: () => errText(err), error: true });
}

function clearNotice(id) {
  delete state.notices[id];
  $(id).hidden = true;
}

function revealAction(path) {
  return { labelKey: "btn.reveal", run: () => api.reveal(path) };
}

// ------------------------------------------------------------------ busy / jobs
const lockable = () => document.querySelectorAll(
  ".panel button:not(#btn-lang):not(#btn-tour), .panel input, .panel select, .panel textarea:not([readonly])"
);

function setBusy(busy) {
  lockable().forEach((el) => {
    if (busy) { el.dataset.wasDisabled = el.disabled ? "1" : ""; el.disabled = true; }
    else if (el.dataset.wasDisabled !== undefined) { el.disabled = el.dataset.wasDisabled === "1"; delete el.dataset.wasDisabled; }
  });
  $("btn-cancel").hidden = !busy;
}

async function runJob(jobId, kind) {
  state.job = jobId;
  let since = 0;
  log.textContent = "";
  setProgress(0);
  setStatus(() => t(phaseKey(kind, 0)));
  for (;;) {
    let s;
    try {
      s = await api.job_status(jobId, since);
    } catch (e) {
      s = { state: "error", error: String(e), logs: [], progress: 0 };
    }
    appendLog(s.logs || []);
    since += (s.logs || []).length;
    if (s.state === "running") {
      const p = s.progress;
      setProgress(p);
      setStatus(() => `${t(phaseKey(kind, p))} ${t("percent", { p: num(p) })}`);
      await sleep(120);
      continue;
    }
    state.job = null;
    if (s.state === "done") setProgress(100, "done");
    else if (s.state === "error") { setProgress(s.progress, "error"); setStatus(() => t("status.failed"), true); }
    else { setProgress(0); setStatus(() => t("status.cancelled")); }
    return s;
  }
}

$("btn-cancel").addEventListener("click", () => {
  if (state.job !== null) { api.cancel(state.job); setStatus(() => t("status.cancelling")); }
});

// ------------------------------------------------------------------ tabs
function selectTab(tab) {
  state.tab = tab;
  for (const name of ["enc", "dec"]) {
    const btn = $(`tab-${name}`);
    btn.setAttribute("aria-selected", String(name === tab));
    btn.tabIndex = name === tab ? 0 : -1;
    $(`panel-${name}`).hidden = name !== tab;
  }
  render(state.views[tab]);
}

for (const name of ["enc", "dec"]) $(`tab-${name}`).addEventListener("click", () => selectTab(name));
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const next = state.tab === "enc" ? "dec" : "enc";
  selectTab(next);
  $(`tab-${next}`).focus();
});

// ------------------------------------------------------------------ pickers
function showPicker(prefix, path, emptyKey) {
  const { dir, name } = path ? splitPath(path) : { dir: "", name: t(emptyKey) };
  $(`${prefix}-name`).textContent = name;
  $(`${prefix}-dir`).textContent = dir;
  $(`${prefix}-picker`).classList.toggle("is-empty", !path);
}

function renderPickers() {
  const folder = state.kind === "folder";
  $("enc-browse").textContent = t(folder ? "pick.folder_btn" : "pick.file_btn");
  showPicker("enc", state.encPath, folder ? "pick.folder_empty" : "pick.file_empty");
  showPicker("dec", state.decImage, "pick.image_empty");
  showPicker("key", state.decKey, "pick.key_empty");
  $("key-clear").hidden = !state.decKey;
}

// ------------------------------------------------------------------ encrypt tab
function setKind(kind) {
  if (state.kind !== kind) state.encPath = "";
  state.kind = kind;
  const isText = kind === "text";
  $("enc-picker").hidden = isText;
  $("enc-textbox").hidden = !isText;
  clearNotice("enc-notice");
  renderPickers();
  renderOptions();
  schedulePhotoUsage();
  if (isText) {
    updateText();
    $("enc-text").focus();
  } else {
    setView("enc", null);
  }
}

document.querySelectorAll('input[name="kind"]').forEach((r) =>
  r.addEventListener("change", () => r.checked && setKind(r.value))
);

function renderCounter() {
  const text = $("enc-text").value;
  $("enc-counter").textContent = text
    ? t("text.counter", { chars: num(text.length), size: fmtBytes(new TextEncoder().encode(text).length) })
    : "";
}

let textFrame = 0;
function updateText() {
  cancelAnimationFrame(textFrame);
  textFrame = requestAnimationFrame(() => {
    const text = $("enc-text").value;
    renderCounter();
    setView("enc", text || $("opt-empty").checked ? textView(text) : null);
  });
}
// An error about the text is out of date as soon as the text or the switch changes.
function textChanged() {
  if (state.notices["enc-notice"]?.error) clearNotice("enc-notice");
  updateText();
  schedulePhotoUsage();
}
$("enc-text").addEventListener("input", textChanged);
$("opt-empty").addEventListener("change", textChanged);

// ------------------------------------------------------------------ photo-safe
// Block size, output format and safe mode don't apply to photo-safe images.
function renderOptions() {
  const photo = $("opt-photo").checked;
  $("opt-row").hidden = photo;
  $("safe-enc-row").hidden = photo || state.kind === "text";
}

function renderPhoto() {
  $("photo-hint").textContent = t("opt.photo_hint", { cap: fmtBytes(state.photoCap) });
  const usage = $("photo-usage");
  const u = state.photoUsage;
  usage.hidden = !($("opt-photo").checked && u && typeof u.used === "number");
  if (usage.hidden) return;
  const vars = { used: fmtBytes(u.used), cap: fmtBytes(u.capacity) };
  usage.textContent = t(u.fits ? "photo.usage" : "photo.usage_over", vars);
  usage.classList.toggle("is-over", !u.fits);
}

let usageTimer = 0;
let usageSeq = 0;
function schedulePhotoUsage() {
  clearTimeout(usageTimer);
  if (!$("opt-photo").checked || !api) { state.photoUsage = null; renderPhoto(); return; }
  usageTimer = setTimeout(async () => {
    const seq = ++usageSeq;
    const u = await api.photo_usage({ mode: state.kind, path: state.encPath, text: $("enc-text").value });
    if (seq !== usageSeq) return;
    state.photoUsage = u && !u.error ? u : null;
    renderPhoto();
  }, 300);
}

$("opt-photo").addEventListener("change", () => {
  if (state.notices["enc-notice"]?.error) clearNotice("enc-notice");
  renderOptions();
  schedulePhotoUsage();
});

function fillBlockSizes() {
  const select = $("opt-block");
  const value = select.value;
  select.replaceChildren(new Option(t("opt.block_auto"), ""));
  for (const n of BLOCK_SIZES) select.appendChild(new Option(t("opt.block_px", { n: num(n) }), String(n)));
  select.value = value;
}

async function chooseInput() {
  const path = state.kind === "folder" ? await api.pick_folder() : await api.pick_file();
  if (!path) return;
  state.encPath = path;
  renderPickers();
  clearNotice("enc-notice");
  schedulePhotoUsage();
  const info = await api.describe_input(path);
  if (info.error) { errorNotice("enc-notice", info.error); return; }
  if (info.kind === "folder") {
    setView("enc", idleView(() => t("cap.folder", { name: info.name })));
  } else {
    setView("enc", headView(info));
  }
}
$("enc-browse").addEventListener("click", chooseInput);

async function encrypt() {
  clearNotice("enc-notice");
  const opts = {
    mode: state.kind,
    path: state.encPath,
    text: $("enc-text").value,
    allow_empty: $("opt-empty").checked,
    block_size: $("opt-block").value || null,
    embed: $("opt-embed").checked,
    photo_safe: $("opt-photo").checked,
    safe: $("opt-safe-enc").checked,
    format: document.querySelector('input[name="format"]:checked').value,
  };
  if (opts.mode !== "text" && !opts.path) {
    notice("enc-notice", { title: () => t(state.kind === "folder" ? "enc.pick_folder_first" : "enc.pick_file_first"), error: true });
    return;
  }
  if (opts.mode === "text" && !opts.text.trim() && !opts.allow_empty) {
    errorNotice("enc-notice", { code: "text_empty" });
    return;
  }
  setBusy(true);
  try {
    const r = await api.start_encrypt(opts);
    if (r.error) { errorNotice("enc-notice", r.error); return; }
    if (r.cancelled) return;
    const s = await runJob(r.job, "enc");
    if (s.state === "error") { errorNotice("enc-notice", s.error); return; }
    if (s.state !== "done") return;

    const res = s.result;
    setStatus(() => t("status.image_made"));
    const lines = [["line.image", res.output]];
    if (res.key_path) lines.push(["line.key", res.key_path]);
    notice("enc-notice", {
      title: () => t(res.embedded ? "enc.done_embedded" : "enc.done_keyfile"),
      lines,
      note: () => t(res.photo_safe ? "enc.send_tip_photo" : "enc.send_tip"),
      action: revealAction(res.output),
    });
    const info = await api.image_info(res.output);
    if (info.thumb) {
      setView("enc", {
        type: "url", url: info.thumb,
        caption: () => t("cap.encrypted", { w: num(info.width), h: num(info.height), size: fmtBytes(info.size) }),
      }, true);
    } else if (!info.error) {
      setView("enc", idleView(() => t("cap.encrypted_big", { size: fmtBytes(info.size) })));
    }
  } catch (e) {
    errorNotice("enc-notice", String(e));
  } finally {
    setBusy(false);
  }
}
$("btn-encrypt").addEventListener("click", encrypt);

// ------------------------------------------------------------------ decrypt tab
function setKeyhint(text, kind = "") {
  state.keyhint = text ? { text, kind } : null;
  renderKeyhint();
}

function renderKeyhint() {
  const h = $("dec-keyhint");
  const k = state.keyhint;
  h.hidden = !k;
  if (!k) return;
  h.textContent = k.text();
  h.className = "keyhint" + (k.kind ? ` is-${k.kind}` : "");
}

function describeKey(k) {
  if (k.kind === "text") return t("what.text");
  if (k.kind === "folder") return t("what.folder", { name: k.name });
  if (typeof k.size === "number") return t("what.file_size", { name: k.name, size: fmtBytes(k.size) });
  return t("what.file", { name: k.name });
}

function setKey(path) {
  state.decKey = path || "";
  renderPickers();
}

async function setDecImage(path) {
  state.decImage = path;
  renderPickers();
  clearNotice("dec-notice");
  $("dec-result").hidden = true;
  setKeyhint(() => t("cap.reading"));
  setView("dec", idleView(() => t("cap.reading")));
  const info = await api.image_info(path);
  if (state.decImage !== path) return;
  if (info.error) {
    setKeyhint(null);
    setView("dec", null);
    errorNotice("dec-notice", info.error);
    return;
  }
  const dims = () => ({ w: num(info.width), h: num(info.height), size: fmtBytes(info.size) });
  setView("dec", info.thumb
    ? { type: "url", url: info.thumb, caption: () => t("cap.image", dims()) }
    : idleView(() => t("cap.image_big", dims())));

  if (info.compressed) {
    setKeyhint(() => t("hint.compressed"), "missing");
  } else if (info.photo_safe) {
    if (info.key) {
      setKeyhint(() => t("hint.photo_found", { what: describeKey(info.key) }), "found");
    } else if (info.sibling_key && !state.decKey) {
      setKey(info.sibling_key);
      setKeyhint(() => t("hint.photo_sibling"), "found");
    } else {
      setKeyhint(() => t("hint.photo_needs_key"), "missing");
    }
  } else if (info.key) {
    setKeyhint(() => t("hint.found", { what: describeKey(info.key) }), "found");
  } else if (info.key_checked) {
    if (info.sibling_key && !state.decKey) {
      setKey(info.sibling_key);
      setKeyhint(() => t("hint.sibling"), "found");
    } else {
      setKeyhint(() => t("hint.none"), "missing");
    }
  } else {
    if (info.sibling_key && !state.decKey) setKey(info.sibling_key);
    setKeyhint(() => t("hint.big"));
  }
}

$("dec-browse").addEventListener("click", async () => {
  const path = await api.pick_image();
  if (path) setDecImage(path);
});
$("key-browse").addEventListener("click", async () => {
  const path = await api.pick_key();
  if (path) { setKey(path); clearNotice("dec-notice"); }
});
$("key-clear").addEventListener("click", () => setKey(""));

$("btn-check").addEventListener("click", async () => {
  clearNotice("dec-notice");
  setBusy(true);
  setStatus(() => t("status.reading_key"));
  try {
    const r = await api.check_key({ key: state.decKey, image: state.decImage });
    if (r.error) { errorNotice("dec-notice", r.error); return; }
    notice("dec-notice", {
      title: () => t(r.source === "file" ? "check.file_ok" : "check.embedded_ok"),
      lines: [
        ["line.contents", () => describeKey(r)],
        ["line.block", () => t("opt.block_px", { n: num(r.block_size) })],
      ],
    });
  } catch (e) {
    errorNotice("dec-notice", String(e));
  } finally {
    setStatus(() => t("status.ready"));
    setBusy(false);
  }
});

async function decrypt() {
  clearNotice("dec-notice");
  $("dec-result").hidden = true;
  if (!state.decImage) {
    notice("dec-notice", { title: () => t("dec.pick_image_first"), error: true });
    return;
  }
  setBusy(true);
  try {
    const r = await api.start_decrypt({ image: state.decImage, key: state.decKey, safe: $("opt-safe-dec").checked });
    if (r.error) { errorNotice("dec-notice", r.error); return; }
    const s = await runJob(r.job, "dec");
    if (s.state === "error") { errorNotice("dec-notice", s.error); return; }
    if (s.state !== "done") return;

    const res = s.result;
    if (typeof res.text === "string") {
      setStatus(() => t("status.text_restored"));
      $("dec-text").value = res.text;
      $("dec-result").hidden = false;
      $("dec-result").scrollIntoView(scrollOpts);
      return;
    }
    const key = res.is_folder ? "status.folder_restored" : "status.file_restored";
    setStatus(() => t(key));
    notice("dec-notice", {
      title: () => t(key),
      lines: [[res.is_folder ? "line.folder" : "line.file", res.output]],
      action: revealAction(res.output),
    });
  } catch (e) {
    errorNotice("dec-notice", String(e));
  } finally {
    setBusy(false);
  }
}
$("btn-decrypt").addEventListener("click", decrypt);

async function copyText() {
  const ta = $("dec-text");
  try {
    await navigator.clipboard.writeText(ta.value);
  } catch {
    ta.select();
    document.execCommand("copy");
    ta.setSelectionRange(0, 0);
  }
  const b = $("btn-copy");
  b.textContent = t("btn.copied");
  setTimeout(() => { b.textContent = t("btn.copy"); }, 1500);
}
$("btn-copy").addEventListener("click", copyText);

$("btn-save-text").addEventListener("click", async () => {
  const r = await api.save_text($("dec-text").value);
  if (r.error) errorNotice("dec-notice", r.error);
  else if (r.saved) notice("dec-notice", { title: () => t("dec.text_saved"), lines: [["line.file", r.saved]], action: revealAction(r.saved) });
});

// ------------------------------------------------------------------ language
function applyLanguage(lang) {
  LANG = lang in STRINGS ? lang : "fa";
  const root = document.documentElement;
  root.lang = LANG;
  root.dir = LANG === "fa" ? "rtl" : "ltr";
  numFmt = new Intl.NumberFormat(LANG === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 1 });

  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });

  const other = LANG === "fa" ? "en" : "fa";
  const langBtn = $("btn-lang");
  langBtn.textContent = STRINGS[other]["lang.name"];
  langBtn.lang = other;

  fillBlockSizes();
  renderPickers();
  renderPhoto();
  renderCounter();
  renderStatus();
  renderKeyhint();
  for (const [id, spec] of Object.entries(state.notices)) notice(id, spec, false);
  render(state.views[state.tab]);
  if (!$("tour").hidden) showTourStep();
}

$("btn-lang").addEventListener("click", () => {
  const next = LANG === "fa" ? "en" : "fa";
  applyLanguage(next);
  if (api) api.set_language(next);
});

// ------------------------------------------------------------------ tour
// First run (and the Guide button): walk through each part of the window.
const TOUR = [
  { key: "welcome" },
  { key: "input", tab: "enc", target: '.seg[aria-labelledby="kind-label"]' },
  { key: "canvas", target: ".tile" },
  { key: "embed", tab: "enc", target: "#embed-row" },
  { key: "photo", tab: "enc", target: "#photo-row" },
  { key: "options", tab: "enc", target: "#opt-row" },
  { key: "decrypt", tab: "dec", target: "#tab-dec" },
  { key: "lang", target: "#btn-lang" },
  { key: "send", important: true },
];
const tour = { steps: [], index: 0, returnTab: "enc", returnFocus: null };

function startTour() {
  tour.returnTab = state.tab;
  tour.returnFocus = document.activeElement;
  // skip steps whose element is hidden right now (e.g. settings in photo-safe mode)
  tour.steps = TOUR.filter((step) => {
    if (!step.target) return true;
    const el = document.querySelector(step.target);
    return el && !el.closest('[hidden]:not([role="tabpanel"])');
  });
  tour.index = 0;
  $("tour").hidden = false;
  showTourStep();
}

function endTour() {
  $("tour").hidden = true;
  selectTab(tour.returnTab);
  if (tour.returnFocus && tour.returnFocus.focus) tour.returnFocus.focus();
  if (api) api.set_tour_done();
}

function showTourStep() {
  const step = tour.steps[tour.index];
  if (step.tab && step.tab !== state.tab) selectTab(step.tab);
  const last = tour.index === tour.steps.length - 1;
  $("tour-title").textContent = t(`tour.${step.key}.title`);
  $("tour-body").textContent = t(`tour.${step.key}.body`, { cap: fmtBytes(state.photoCap) });
  $("tour-count").textContent = t("tour.count", { n: num(tour.index + 1), total: num(tour.steps.length) });
  $("tour-prev").hidden = tour.index === 0;
  $("tour-skip").hidden = last;
  $("tour-next").textContent = t(last ? "tour.done" : "tour.next");
  $("tour-card").classList.toggle("is-important", !!step.important);
  placeTour();
  $("tour-next").focus();
}

function placeTour() {
  const step = tour.steps[tour.index];
  const spot = $("tour-spot"), card = $("tour-card");
  const vw = window.innerWidth, vh = window.innerHeight, gap = 12, pad = 6;
  const el = step.target && document.querySelector(step.target);
  if (!el) {
    Object.assign(spot.style, { transform: `translate(${vw / 2}px, ${vh / 2}px)`, width: "0px", height: "0px" });
    card.style.left = `${Math.max(gap, (vw - card.offsetWidth) / 2)}px`;
    card.style.top = `${Math.max(gap, (vh - card.offsetHeight) / 2)}px`;
    return;
  }
  el.scrollIntoView({ block: "nearest" });
  const r = el.getBoundingClientRect();
  Object.assign(spot.style, {
    transform: `translate(${r.left - pad}px, ${r.top - pad}px)`,
    width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px`,
  });
  const cw = card.offsetWidth, ch = card.offsetHeight;
  let top = r.bottom + pad + gap;
  if (top + ch > vh - gap) top = r.top - pad - gap - ch;
  top = Math.min(Math.max(gap, top), vh - ch - gap);
  let left = document.documentElement.dir === "rtl" ? r.right - cw : r.left;
  left = Math.min(Math.max(gap, left), vw - cw - gap);
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

$("tour-next").addEventListener("click", () => {
  if (tour.index < tour.steps.length - 1) { tour.index++; showTourStep(); } else endTour();
});
$("tour-prev").addEventListener("click", () => {
  if (tour.index > 0) { tour.index--; showTourStep(); }
});
$("tour-skip").addEventListener("click", endTour);
$("btn-tour").addEventListener("click", startTour);
window.addEventListener("resize", () => { if (!$("tour").hidden) placeTour(); });
$("tour").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.preventDefault(); endTour(); return; }
  if (e.key !== "Tab") return;
  // keep focus inside the card
  const items = [...$("tour-card").querySelectorAll("button")].filter((b) => !b.hidden);
  const first = items[0], lastItem = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastItem.focus(); }
  else if (!e.shiftKey && document.activeElement === lastItem) { e.preventDefault(); first.focus(); }
});

// ------------------------------------------------------------------ start
let started = false;
async function init() {
  if (started || !window.pywebview || !window.pywebview.api) return;
  started = true;
  api = window.pywebview.api;
  const s = (await api.initial_state()) || {};
  if (s.photo_capacity) state.photoCap = s.photo_capacity;
  if (s.lang && s.lang !== LANG) applyLanguage(s.lang);
  else renderPhoto();
  if (s.image) { selectTab("dec"); setDecImage(s.image); }
  if (!s.tour_done) startTour();
}

applyLanguage("fa");
setKind("file");
window.addEventListener("pywebviewready", init);
init();
