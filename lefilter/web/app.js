"use strict";
/* Loot filter editor. State lives in S; the server only reads/writes files and runs the
   generator/matcher. Rules are kept top-first (index 0 = highest priority), as in-game. */

const $ = (sel) => document.querySelector(sel);

/** An affix category / picker header in the current language. */
function catName(name) {
  return S.meta.categories?.[name] || name;
}

function factionLabel(f) {
  return S.meta.enums.faction_labels[f] || f.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (["value", "checked", "selected", "disabled", "open"].includes(k)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

/** append children, skipping null/false and flattening arrays (Element.append would stringify them) */
function put(el, ...kids) {
  el.append(...kids.flat(Infinity).filter((k) => k != null && k !== false).map((k) => (k instanceof Node ? k : String(k))));
  return el;
}

/** Replace el's children, skipping null / false ones like h() and put() (replaceChildren would print "null"). */
function fill(el, ...kids) {
  el.replaceChildren();
  return put(el, ...kids);
}

const store = {
  get(k, dflt) { try { const v = localStorage.getItem(k); return v == null ? dflt : JSON.parse(v); } catch { return dflt; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const S = {
  meta: null, filters: [], doc: null, file: null, dirty: false,
  sel: -1, search: "", lvl: { on: false, level: 1 },
  undo: [], redo: [],
  lev: { opts: null, result: null, error: null },
  idol: { opts: null, classes: null, sel: null, search: "", result: null, error: null },
  bis: { opts: null, sel: "weapons", search: "", result: null, error: null },
  test: { item: null, result: null },
};
let M = null;
const SHOW_ALL_AFFIXES = new WeakSet();
let META_EN = null;   // the English game data; a language overlays a copy of it   // affix conditions whose picker lists every affix

async function api(path, body) {
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) { const e = new Error(data.error || res.statusText); e.status = res.status; throw e; }
  return data;
}

let toastTimer = null;
function toast(msg, error = false) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const t = h("div", { class: "toast" + (error ? " error" : "") }, msg);
  put(document.body, t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), error ? 8000 : 4000);
}

function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ---------- game data lookups ---------- */

const COND_LABELS = {
  RarityCondition: "Rarity", SubTypeCondition: "Item Type", AffixCondition: "Affix",
  CharacterLevelCondition: "Character Level", PotentialCondition: "Potential", ClassCondition: "Class Requirement",
  UniqueModifiersCondition: "Uniques", CorruptionCondition: "Corruption", FactionCondition: "Faction",
  AffixCountCondition: "Affix Count", LevelCondition: "Item Level", KeysCondition: "Keys",
  CraftingMaterialsCondition: "Crafting Materials", ResonancesCondition: "Resonances",
  WovenEchoesCondition: "Woven Echoes", GlyphCondition: "Glyphs", RuneCondition: "Runes",
};
const condLabel = (t) => COND_LABELS[t] || t.replace(/Condition$/, "");
const cap = (s) => s.charAt(0) + s.slice(1).toLowerCase();

/** Copy of the English data with a language's game names / affix texts laid over it (English kept as en_name). */
function applyLanguage(en, tr) {
  const meta = structuredClone(en);
  meta.value_after = !!tr?.value_after;
  meta.categories = tr?.categories || {};
  for (const a of meta.affixes) {
    a.en_name = a.name;
    if (!tr) continue;
    if (tr.affixes[a.id]) a.name = tr.affixes[a.id];
    (tr.lines[a.id] || []).forEach((t, i) => { if (t && a.lines[i]) a.lines[i].text = t; });
  }
  for (const b of meta.bases) {
    b.en_name = b.name;
    if (tr?.base_types[b.id]) b.name = tr.base_types[b.id];
    for (const s of b.subtypes) {
      s.en_name = s.name;
      const t = tr?.subtypes[`${b.id}/${s.id}`];
      if (t) s.name = t;
      (tr?.implicits?.[`${b.id}/${s.id}`] || []).forEach((text, i) => { if (text && s.implicits?.[i]) s.implicits[i].text = text; });
    }
  }
  for (const u of meta.uniques) {
    u.en_name = u.name;
    if (tr?.uniques[u.id]) u.name = tr.uniques[u.id];
    const tt = tr?.unique_tooltips?.[u.id];
    if (tt) {
      (tt.lines || []).forEach((text, i) => { if (text && u.tooltip?.[i]) u.tooltip[i].text = text; });
      (tt.rolls || []).forEach((text, i) => { if (text && u.rolls?.[i]) u.rolls[i].text = text; });
      if (tt.lore) u.lore = tt.lore;
    }
    if (tr?.base_types[u.base_type]) u.base_type_name = tr.base_types[u.base_type];
  }
  if (tr) {
    for (const k of meta.idol_kinds) {
      const sub = (id) => tr.subtypes[`${k.type_id}/${id}`];
      k.base_names = k.base_names.map((n, i) => sub(k.subtypes[i]) || n);
      k.heretical_names = k.heretical_names.map((n, i) => sub(k.subtypes[k.base_names.length + i]) || n);
      for (const p of k.pool) p.name = tr.affixes[p.id] || p.name;
    }
  }
  return meta;
}

let langSeq = 0;   // only the latest language choice applies, however the loads finish
async function setLanguage(code) {
  const seq = ++langSeq;
  let tr = null;
  if (code && code !== "en") {
    try { tr = await api(`/api/lang?code=${encodeURIComponent(code)}`); } catch (e) { if (seq === langSeq) toast(`Language ${code}: ${e.message}`, true); code = null; }
  }
  if (seq !== langSeq) return;
  S.meta = applyLanguage(META_EN, tr);
  indexMeta(S.meta);
  if (code) store.set("lang", code);   // a failed load keeps the saved choice for next time
  $("#lang-select").value = tr ? code : "en";
  renderDoc();
  renderLevForm(); renderLevPreview();
  renderIdolList(); renderIdolEditor();
  renderBisList(); renderBisEditor();
  renderTestForm(); renderTestResult();
}

function indexMeta(meta) {
  M = {
    affix: new Map(meta.affixes.map((a) => [a.id, a])),
    base: new Map(meta.bases.map((b) => [b.type, b])),
    baseById: new Map(meta.bases.map((b) => [b.id, b])),
    unique: new Map(meta.uniques.map((u) => [u.id, u])),
    toggle: new Map(meta.toggles.map((t) => [t.key, t])),
  };
}
const typeName = (t) => M.base.get(t)?.name || t;
const affixName = (id) => M.affix.get(id)?.name || `affix ${id}`;
/** The highest tier an affix rolls (T8 only on equipment: idol altar affixes stop at T7); 8 without tier data. */
const affixMaxTier = (id) => Math.max(0, ...(M.affix.get(id)?.lines || []).map((l) => l.tiers.length)) || 8;
/** An affix's group in the in-game picker: "Offensive · Damage Type". */
const affixGroup = (a) => (a ? `${catName(a.header)} · ${catName(a.category)}` : "Not in this game version");

/** Affixes (or ids) the in-game picker's way: its headers and categories in the game's order (data from
 *  before that order was extracted: by their names), a category's affixes by name; unknown ids last. */
function compareAffixes(x, y) {
  const a = typeof x === "number" ? M.affix.get(x) : x, b = typeof y === "number" ? M.affix.get(y) : y;
  if (!a || !b) return (!a) - (!b) || (a || b ? 0 : x - y);
  const [ah, ac] = a.order || [], [bh, bc] = b.order || [];
  const byOrder = ah != null && bh != null ? ah - bh || ac - bc : affixGroup(a).localeCompare(affixGroup(b));
  return byOrder || a.name.localeCompare(b.name);
}

/** An affix list's quick filter: { cats: picker groups shown (none = all), sort: "category" | "name" }. */
const newAffixFilter = () => ({ cats: new Set(), sort: "category" });
const AFFIX_PICKER = new WeakMap();   // per affix condition

/** Quick filter bar for an affix list: the in-game picker's categories as chips under their headers, with how
 *  many of `affixes` each has (several can be on; none = all), and the list's order - by category or by name.
 *  `all` (default: affixes) gives the categories; one with nothing left shows while it's ticked, so it can be
 *  unticked. redraw() redraws the list; affixShownBy(f) applies the filter to it. */
function affixFilterBar(f, affixes, redraw, all = affixes) {
  const box = h("div", { class: "uniq-types affix-cats" });
  const draw = () => {
    const counts = new Map(), heads = new Map(), seen = new Set();
    for (const a of affixes) counts.set(affixGroup(a), (counts.get(affixGroup(a)) || 0) + 1);
    for (const a of [...all].sort(compareAffixes)) {
      const key = affixGroup(a), head = catName(a.header) || "Other";
      if (seen.has(key) || !(counts.get(key) || f.cats.has(key))) continue;
      seen.add(key);
      (heads.get(head) || heads.set(head, []).get(head)).push([key, catName(a.category)]);
    }
    const change = (fn) => () => { fn(); draw(); redraw(); };
    fill(box,
      h("div", { class: "row" }, h("span", { class: "hint" }, "Sort"),
        h("div", { class: "seg" }, [["category", "by category"], ["name", "by name"]].map(([k, label]) =>
          h("button", { class: f.sort === k ? "on" : "", onclick: change(() => { f.sort = k; }) }, label))),
        f.cats.size ? h("button", { onclick: change(() => f.cats.clear()) }, "All categories") : null),
      [...heads].map(([head, cats]) => h("div", { class: "chips compact" }, h("span", { class: "hint cat" }, head),
        cats.map(([key, name]) => chipToggle(name, f.cats.has(key),
          change(() => { if (f.cats.has(key)) f.cats.delete(key); else f.cats.add(key); }), `${counts.get(key) || 0}`)))));
  };
  draw();
  return box;
}
const affixShownBy = (f) => (a) => !f.cats.size || f.cats.has(affixGroup(a));

/** Picked affixes as chips under subheaders: each picker group's line, then its chips, then the next group. */
function groupedChips(ids, chip) {
  const out = [];
  let group = null;
  for (const id of [...ids].sort(compareAffixes)) {
    const g = affixGroup(M.affix.get(id));
    if (g !== group) { group = g; out.push(h("div", { class: "chip-group" }, g)); }
    out.push(chip(id));
  }
  return out;
}
/** A "prefix" / "suffix" pill for an affix (or its id). */
function affixPill(a) {
  a = typeof a === "number" ? M.affix.get(a) : a;
  if (!a) return null;
  const kind = a.kind || (a.prefix ? "prefix" : "suffix");
  return h("span", { class: `pill ${kind}`, title: kind }, kind);
}
const uniqueName = (id) => M.unique.get(id)?.name || `unique ${id}`;
const filterColor = (i) => S.meta.palette.filter[i] || "#fff";
const beamColor = (i) => S.meta.palette.beam[i] || "#fff";
const rarityColor = (r) => S.meta.palette.rarity[r] || "#fff";
const equipmentBases = () => S.meta.bases.filter((b) => b.name && b.type !== "UNUSED");
const CATEGORY_ORDER = ["One Handed Weapons", "Two Handed Weapons", "Off-Hand", "Armor", "Accessories", "Idols", "Altars", "Other"];
/** Item types grouped by the in-game picker's categories, in its order. */
function basesByCategory() {
  const byCat = new Map(CATEGORY_ORDER.map((c) => [c, []]));
  for (const b of equipmentBases()) byCat.get(byCat.has(b.category) ? b.category : "Other").push(b);
  return [...byCat].filter(([, list]) => list.length);
}

const COND_DEFAULTS = {
  RarityCondition: { rarity: [] },
  SubTypeCondition: { types: [], subtypes: [] },
  AffixCondition: { affixes: [], comparsion: "ANY", comparsion_value: 0, min_on_same_item: 1,
    combined_comparsion: "ANY", combined_value: 1, advanced: false },
  CharacterLevelCondition: { min: 0, max: 100 },
  PotentialCondition: { lp_min: null, lp_max: null, ww_min: null, ww_max: null, wt_min: null, wt_max: null, fp_min: null, fp_max: null },
  ClassCondition: { classes: [] },
  UniqueModifiersCondition: { uniques: [] },
  CorruptionCondition: { corruption: "Any" },
  FactionCondition: { factions: [] },
  AffixCountCondition: { prefix_min: null, prefix_max: null, suffix_min: null, suffix_max: null, sealed: "Any" },
  LevelCondition: { threshold: 0, level_type: "BELOW_LEVEL" },
};

function newCondition(type) {
  if (S.meta.enums.flag_conditions[type]) return { type, flags: [] };
  return { type, ...structuredClone(COND_DEFAULTS[type] || {}) };
}

function newRule(name = "") {
  return { type: "SHOW", conditions: [], recolor: false, color: 0, enabled: true, level_dependent: false,
    min_lvl: 0, max_lvl: 0, emphasized: false, name, sound: 0, map_icon: 0, beam_override: false,
    beam_size: "NONE", beam_color: 0 };
}

const isRaw = (r) => "raw" in r;
const isSeparator = (r) => !isRaw(r) && r.conditions.length === 0;

/** What a rule still waits for, when it's one of the template's rules to fill in for a build (build slots, the
 *  BiS rules to pick bases for, the class hide rule) left as it came - or one that can't match yet. Optional:
 *  the filter works without them, so the editor only points them out. */
function todoNote(r) {
  if (isRaw(r)) return null;
  const conds = r.conditions.filter((c) => !c.raw);
  const has = (type, test) => conds.some((c) => c.type === type && test(c));
  const note = has("UniqueModifiersCondition", (c) => !c.uniques?.length) ? "pick the uniques or set items it shows"
    : has("SubTypeCondition", (c) => !c.types?.length) ? "pick the item type and its bases"
    : /\(pick (type & )?bases\)$/i.test(r.name || "") && has("SubTypeCondition", (c) => !c.subtypes?.length)
      ? "pick its bases and the affixes it needs - or let the Best in slot tab make these rules"
    : r.name === S.meta.class_hide_name && has("ClassCondition", (c) => c.classes?.length === S.meta.enums.classes.length)
      ? "untick the class you play (it hides the ticked classes' class items)"
    : null;
  return note && (r.enabled ? note : `${note}, then switch it on`);
}

function activeAt(r, level) {
  if (isRaw(r)) return true;
  return r.conditions.every((c) => c.type !== "CharacterLevelCondition" || c.raw || (level >= c.min && level <= c.max));
}

function rangeText(lo, hi, unit) {
  if (lo == null && hi == null) return null;
  if (hi == null) return `${lo}+ ${unit}`;
  if (lo == null) return `≤${hi} ${unit}`;
  return `${lo}-${hi} ${unit}`;
}

function condSummary(c) {
  if (c.raw) return `${condLabel(c.type)} (raw XML)`;
  switch (c.type) {
    case "RarityCondition": return c.rarity.length ? c.rarity.map(cap).join(" / ") : "no rarity";
    case "SubTypeCondition": {
      if (!c.types.length) return "no item type";
      if (c.types.length === 1) {
        return typeName(c.types[0]) + (c.subtypes.length ? ` (${c.subtypes.length} base${c.subtypes.length > 1 ? "s" : ""})` : "");
      }
      return c.types.length > 3 ? `${c.types.length} item types` : c.types.map(typeName).join(", ");
    }
    case "AffixCondition": {
      let s = `${c.min_on_same_item}+ of ${c.affixes.length || "any"} affix${c.affixes.length === 1 ? "" : "es"}`;
      if (c.advanced && c.comparsion !== "ANY") s += ` T${opText(c.comparsion)}${c.comparsion_value}`;
      if (c.advanced && c.combined_comparsion !== "ANY") s += ` Σ${opText(c.combined_comparsion)}${c.combined_value}`;
      return s;
    }
    case "CharacterLevelCondition": return `char lvl ${c.min}-${c.max}`;
    case "PotentialCondition":
      return [rangeText(c.lp_min, c.lp_max, "LP"), rangeText(c.ww_min, c.ww_max, "WW"),
        rangeText(c.wt_min, c.wt_max, "WT"), rangeText(c.fp_min, c.fp_max, "FP")].filter(Boolean).join(", ") || "potential: any";
    case "ClassCondition": return c.classes.length ? `class: ${c.classes.join("/")}` : "class: any";
    case "UniqueModifiersCondition": return `${c.uniques.length} unique${c.uniques.length === 1 ? "" : "s"}`;
    case "CorruptionCondition": return c.corruption === "Any" ? "corrupted or not" : c.corruption === "OnlyCorrupted" ? "corrupted" : "not corrupted";
    case "FactionCondition": return `faction: ${c.factions.map(factionLabel).join("/") || "none"}`;
    case "AffixCountCondition": return [rangeText(c.prefix_min, c.prefix_max, "prefixes"), rangeText(c.suffix_min, c.suffix_max, "suffixes")].filter(Boolean).join(", ") || "affix count";
    case "LevelCondition": return `${c.level_type.toLowerCase().replaceAll("_", " ")} ${c.threshold}`;
    default: return `${condLabel(c.type)}: ${(c.flags || []).join(", ") || "none"}`;
  }
}
const opText = (op) => ({ EQUAL: "=", LESS: "<", LESS_OR_EQUAL: "≤", MORE: ">", MORE_OR_EQUAL: "≥" }[op] || "");

/* ---------- undo / change tracking ---------- */

let typingTimer = null;
/** Snapshot for undo; keystrokes in a text field within a short pause count as one step. */
function beforeChange(typing = false) {
  if (!(typing && typingTimer)) {
    S.undo.push(JSON.stringify(S.doc));
    if (S.undo.length > 80) S.undo.shift();
    S.redo = [];
  }
  clearTimeout(typingTimer);
  typingTimer = typing ? setTimeout(() => { typingTimer = null; }, 800) : null;
  S.dirty = true;
}

/** Apply a change to the document and refresh the views that show it. */
function mutate(fn, { list = true, editor = false, typing = false } = {}) {
  if (!S.doc) return;
  beforeChange(typing);
  fn();
  renderStatus();
  if (list) renderList();
  if (editor) renderEditor();
  testSoon();
}

function undo() {
  if (!S.undo.length) return;
  S.redo.push(JSON.stringify(S.doc));
  S.doc = JSON.parse(S.undo.pop());
  S.dirty = true;
  clampSel();
  renderDoc();
  generatorsSoon();
}
function redo() {
  if (!S.redo.length) return;
  S.undo.push(JSON.stringify(S.doc));
  S.doc = JSON.parse(S.redo.pop());
  S.dirty = true;
  clampSel();
  renderDoc();
  generatorsSoon();
}
/** The generator tabs' summaries (rule counts, placement) depend on the open filter: work them out again. */
function generatorsSoon() { levelingSoon(); idolsSoon(); bisSoon(); }
function clampSel() { S.sel = Math.min(S.sel, (S.doc?.rules.length || 0) - 1); }

/* ---------- files ---------- */

async function loadFilters() {
  S.filters = await api("/api/filters");
  const sel = $("#file-select");
  sel.replaceChildren();
  for (const loc of ["game", "out", "template"].filter((l) => S.meta.locations.includes(l))) {
    const files = S.filters.filter((f) => f.location === loc);
    if (!files.length) continue;
    sel.append(h("optgroup", { label: LOCATION_LABELS[loc] || loc },
      files.map((f) => h("option", { value: `${f.location}|${f.file}` }, `${f.name}  —  ${f.file}`))));
  }
  if (!S.file) sel.prepend(h("option", { value: "", selected: true }, S.doc ? "(unsaved new filter)" : "Choose a filter…"));
  if (S.file) sel.value = `${S.file.location}|${S.file.file}`;
}

function confirmDiscard() {
  return !S.dirty || confirm("Discard unsaved changes to this filter?");
}

async function openFile(location, file) {
  try {
    const doc = await api(`/api/filter?location=${encodeURIComponent(location)}&file=${encodeURIComponent(file)}`);
    S.doc = { header: doc.header, rules: doc.rules };
    S.file = { location, file };
    S.dirty = false; S.undo = []; S.redo = []; S.sel = S.doc.rules.length ? 0 : -1;
    store.set("last-file", S.file);
    await loadFilters();
    renderDoc();
    levelingSoon();
    readIdolsFromFilter();
    readBisFromFilter();
  } catch (e) {
    toast(`Could not open ${file}: ${e.message}`, true);
  }
}

async function save(asNew = false) {
  if (!S.doc) return;
  if (asNew || !S.file) return saveAsDialog();
  await doSave(S.file.location, S.file.file, true);
}

async function doSave(location, file, overwrite) {
  try {
    const res = await api("/api/filter", { location, file, overwrite, doc: S.doc });
    S.file = { location, file };
    S.dirty = false;
    store.set("last-file", S.file);
    await loadFilters();
    renderStatus();
    toast(`Saved ${res.path}` + (res.backup ? ` (previous version backed up to ${res.backup})` : ""));
  } catch (e) {
    if (e.status === 409 && confirm(`${file} already exists. Overwrite it? (the old file is backed up)`)) {
      return doSave(location, file, true);
    }
    toast(`Save failed: ${e.message}`, true);
  }
}

function saveAsDialog() {
  const dlg = $("#dlg");
  const fileIn = h("input", { value: `${(S.doc.header.name || "Filter").replace(/[<>:"/\\|?*]/g, "_")}.xml`, size: 40 });
  const locs = S.meta.locations.filter((l) => l !== "template");
  const locSel = h("select", {}, locs.map((l) => h("option", { value: l, selected: l === (S.file?.location || "game") }, LOCATION_LABELS[l])));
  const nameIn = h("input", { value: S.doc.header.name || "", size: 40 });
  fill(dlg, 
    h("h3", {}, "Save filter as"),
    h("div", { class: "row fields" }, h("label", {}, "Folder ", locSel)),
    h("div", { class: "row fields" }, h("label", {}, "File ", fileIn)),
    h("div", { class: "row fields" }, h("label", {}, "In-game name ", nameIn)),
    h("p", { class: "hint" }, "The game lists filters by their in-game name (the Filter name field), not by the file name."),
    h("div", { class: "row" },
      h("button", { onclick: () => dlg.close() }, "Cancel"),
      h("button", { class: "primary", onclick: async () => {
        let f = fileIn.value.trim();
        if (!f) return;
        if (!f.toLowerCase().endsWith(".xml")) f += ".xml";
        const name = nameIn.value.trim();
        if (name && name !== S.doc.header.name) {
          mutate(() => { S.doc.header.name = name; }, { editor: false });
          renderHeader();
        }
        dlg.close();
        await doSave(locSel.value, f, false);
      } }, "Save")));
  dlg.showModal();
  fileIn.select();
}

function startDoc(doc) {
  S.doc = doc;
  S.file = null; S.dirty = true; S.undo = []; S.redo = []; S.sel = doc.rules.length ? 0 : -1;
  loadFilters();
  renderDoc();
  switchTab("rules");
  levelingSoon();
  idolsSoon();
}

/** The game's filter icon (tinted white sprite); 0 = no icon. */
function filterIcon(id, color, size = 24) {
  const c = S.meta.filter_icons.colors[color] || "#ddd";
  if (!id || !S.meta.filter_icons.icons.some((i) => i.id === id)) return h("span", { class: "none" }, id ? `#${id}` : "none");
  return h("span", { class: "ficon", title: S.meta.filter_icons.icons.find((i) => i.id === id)?.name,
    style: { width: `${size}px`, height: `${size}px`, background: c, webkitMaskImage: `url(/icons/${id}.png)`, maskImage: `url(/icons/${id}.png)` } });
}

/** Icon grid + colour swatches; state = {icon, color}, onChange(state) after each pick. */
function iconPicker(state, onChange) {
  const wrap = h("div", {});
  const draw = () => {
    const ids = [0, ...S.meta.filter_icons.icons.map((i) => i.id)];
    fill(wrap, 
      h("div", { class: "icon-grid" }, ids.map((id) => h("button", { class: "icon-cell" + (state.icon === id ? " on" : ""), type: "button",
        onclick: () => { state.icon = id; onChange(state); draw(); } }, filterIcon(id, state.color)))),
      h("div", { class: "row fields" }, h("span", { class: "hint" }, "Colour"),
        h("div", { class: "palette" }, S.meta.filter_icons.colors.map((c, i) => h("span", {
          class: "swatch" + (state.color === i ? " on" : ""), style: { background: c }, title: `${i}`,
          onclick: () => { state.color = i; onChange(state); draw(); } })))));
  };
  draw();
  return wrap;
}

function headerIconDialog() {
  if (!S.doc) return;
  const dlg = $("#dlg");
  const state = { icon: S.doc.header.icon || 0, color: S.doc.header.icon_color || 0 };
  fill(dlg, h("h3", {}, "Filter icon"),
    iconPicker(state, () => {}),
    h("div", { class: "row" }, h("button", { onclick: () => dlg.close() }, "Cancel"),
      h("button", { class: "primary", onclick: () => {
        dlg.close();
        mutate(() => { S.doc.header.icon = state.icon; S.doc.header.icon_color = state.color; }, { list: false });
        renderHeader();
      } }, "Set")));
  dlg.showModal();
}

const LOCATION_LABELS = { game: "Game Filters folder", out: "out/ (generated)", template: "New-filter template (project)" };

function newFilter() {
  if (!confirmDiscard()) return;
  // filling BiS / adding sections is opt-in (a blank slate by default); older saved choices don't carry over
  const last = { ...store.get("new-filter", { character_class: "" }), add_bis: false, add_leveling: false, add_idols: false,
    ...store.get("new-filter-fill", {}) };
  const dlg = $("#dlg");
  const nameIn = h("input", { value: "New filter", size: 34 });
  const clsSel = h("select", {}, h("option", { value: "" }, "none (class rules stay off)"),
    S.meta.enums.classes.map((c) => h("option", { value: c, selected: c === last.character_class }, c)));
  const hasPicks = Object.keys(idolOpts().picks || {}).length > 0 || altarPicked(idolOpts());
  const classIcons = S.meta.enums.class_icons;
  const icon = { icon: classIcons[last.character_class] ?? last.icon ?? 0, color: last.icon_color ?? 0, picked: false };
  let picker = null;
  const drawPicker = () => {
    const fresh = iconPicker(icon, () => { icon.picked = true; });
    if (picker) picker.replaceWith(fresh);
    picker = fresh;
  };
  drawPicker();
  clsSel.addEventListener("change", () => {
    if (!icon.picked && classIcons[clsSel.value]) { icon.icon = classIcons[clsSel.value]; drawPicker(); }
  });
  const box = (key, label, enabled = true) => {
    const b = h("input", { type: "checkbox", checked: enabled && last[key], disabled: !enabled });
    return [key, b, h("div", {}, h("label", {}, b, " ", label))];
  };
  const boxes = [
    box("add_bis", bisHasPicks() ? "Add the BiS rules (Best in slot tab picks)" : "Add the BiS rules (no Best in slot picks yet)", bisHasPicks()),
    box("add_leveling", "Add the leveling section now (the Leveling tab's settings)"),
    box("add_idols", hasPicks ? "Add the idol section (Idols and Idol Altars generator picks)" : "Add the idol section (no idol or altar picks yet)", hasPicks),
  ];
  const create = async () => {
    const flags = Object.fromEntries(boxes.map(([k, b]) => [k, b.checked]));
    store.set("new-filter", { character_class: clsSel.value, icon: icon.icon, icon_color: icon.color });
    store.set("new-filter-fill", flags);
    const options = { name: nameIn.value.trim() || "New filter", character_class: clsSel.value,
      add_leveling: flags.add_leveling, leveling: levBody(clsSel.value || levOpts().character_class),
      icon: icon.icon, icon_color: icon.color };
    if (flags.add_idols) options.idols = idolOpts();
    if (flags.add_bis) options.bis = bisOpts();
    try {
      const res = await api("/api/new", { options });
      dlg.close();
      if (options.character_class) {   // the class also becomes the generators' default
        levOpts().character_class = options.character_class;
        store.set("lev-opts", S.lev.opts);
        S.idol.classes = [options.character_class];
        store.set("idol-classes", S.idol.classes);
        bisOpts().character_class = options.character_class;
        store.set("bis-opts", S.bis.opts);
      }
      startDoc({ header: res.header, rules: res.rules });
      toast(`New filter with ${res.rules.length} rules - save it to keep it.` + (res.warnings.length ? ` ${res.warnings.join("; ")}` : ""));
    } catch (e) {
      toast(`Could not build the filter: ${e.message}`, true);
    }
  };
  const rebuild = async () => {
    if (!confirm(`Regenerate ${S.meta.template.file} from config.toml? Edits made to it are replaced (the old one is backed up).`)) return;
    try {
      const res = await api("/api/template/rebuild", {});
      await loadFilters();
      toast(`Template rebuilt: ${res.rules} rules` + (res.backup ? ` (backup: ${res.backup})` : ""));
    } catch (e) {
      toast(`Could not rebuild the template: ${e.message}`, true);
    }
  };
  fill(dlg, 
    h("h3", {}, "New filter"),
    h("div", { class: "row fields" }, h("label", {}, "Name ", nameIn)),
    h("div", { class: "row fields" }, h("label", {}, "Class ", clsSel)),
    h("p", { class: "hint" }, "The class switches on the rule hiding other classes' items (ticking every other class) and its shatter rule, and becomes the generators' class."),
    h("div", { class: "group-label" }, "Icon (follows the class until you pick one)"), picker,
    h("div", { class: "group-label" }, "Build-specific parts (off: a blank slate)"),
    ...boxes.map(([, , row]) => row),
    h("p", { class: "hint" }, "Left off, the BiS rules stay the template's generic ones - switched off, no affixes - "
      + "until you apply the Best in slot tab; the Leveling and Idols tabs apply their sections the same way."),
    h("p", { class: "hint" }, `Starts from the saved template only (${LOCATION_LABELS.template}: ${S.meta.template.file} - open it from the list to edit it): `
      + S.meta.template.parts.join("; ") + ". Its [A] rules are regenerated for the current game data."),
    h("div", { class: "row" },
      h("button", { onclick: () => dlg.close() }, "Cancel"),
      h("button", { onclick: () => { dlg.close(); startDoc({ header: { name: nameIn.value.trim() || "New filter", icon: 0, icon_color: 0, description: "", version: S.meta.game_version || "" }, rules: [] }); } }, "Empty filter"),
      h("button", { onclick: rebuild, title: "Regenerate the template from config.toml" }, "Rebuild template…"),
      h("button", { class: "primary", onclick: create }, "Create")));
  dlg.showModal();
  nameIn.select();
}

function deleteDialog() {
  if (!S.file) { toast("This filter isn't saved as a file yet - nothing to delete."); return; }
  if (S.file.location === "template") { toast("The new-filter template can't be deleted (Rebuild template regenerates it)."); return; }
  const { location, file } = S.file;
  const info = S.filters.find((f) => f.location === location && f.file === file);
  const dlg = $("#dlg");
  fill(dlg, 
    h("h3", {}, "Delete filter?"),
    h("p", {}, h("b", {}, info?.name || file), ` — ${location === "game" ? "game Filters folder" : "out"}/${file}`),
    h("p", { class: "hint" }, "The file is removed (the game stops listing it; if it's the active filter, pick another in-game). "
      + "A copy is kept in .cache/backups/." + (S.dirty ? " Unsaved changes in the editor are lost too." : "")),
    h("div", { class: "row" },
      h("button", { onclick: () => dlg.close() }, "Cancel"),
      h("button", { class: "danger", onclick: async () => {
        dlg.close();
        try {
          const res = await api("/api/filter/delete", { location, file });
          S.doc = null; S.file = null; S.dirty = false; S.undo = []; S.redo = []; S.sel = -1;
          store.set("last-file", null);
          await loadFilters();
          renderDoc();
          toast(`Deleted ${res.path} (backup: ${res.backup})`);
        } catch (e) {
          toast(`Delete failed: ${e.message}`, true);
        }
      } }, `Delete ${file}`)));
  dlg.showModal();
}

async function refreshGenerated() {
  if (!S.doc) return;
  try {
    const res = await api("/api/refresh", { rules: S.doc.rules });
    mutate(() => { S.doc.rules = res.rules; clampSel(); }, { editor: true });
    toast(`[A] rules regenerated: ${res.removed} replaced by ${res.added}; on/off state or filled build slots kept for ${res.kept}. Undo with Ctrl+Z.`
      + (res.warnings.length ? ` ${res.warnings.join("; ")}` : ""));
  } catch (e) {
    toast(`Could not regenerate: ${e.message}`, true);
  }
}

/** A filter `build --standalone` made: unique and set rules only (it says so in its description). */
const uniquesOnly = (doc) => /\[auto-uniques/.test(doc?.header?.description || "")
  && doc.rules.every((r) => isRaw(r) || /^\[[^\]]+\] /.test(r.name || ""));

function renderDocNotice() {
  const box = $("#doc-notice");
  box.replaceChildren();
  const todo = S.doc ? S.doc.rules.flatMap((r, i) => (todoNote(r) ? [i] : [])) : [];
  if (todo.length) {
    // the next one below the selected rule (from the top again after the last), among the rules the name filter shows
    const q = S.search.toLowerCase();
    const shown = todo.filter((i) => !q || (S.doc.rules[i].name || "").toLowerCase().includes(q));
    const next = () => {
      S.sel = shown.find((i) => i > S.sel) ?? shown[0];
      renderList(); renderEditor(); scrollToSel();
    };
    put(box, h("div", { class: "todo-notice" },
      h("span", { class: "badge todo" }, "to fill in"),
      h("span", {}, `${todo.length} rule${todo.length > 1 ? "s" : ""} to fill in for your build - optional: the filter works without them.`),
      h("button", { disabled: !shown.length, title: shown.length ? "Select the next rule to fill in" : "None of them matches the name filter", onclick: next }, "Next ▸")));
  }
  if (!uniquesOnly(S.doc)) return;
  put(box, h("div", { class: "box notice" },
    h("div", {}, h("b", {}, "Unique and set rules only. "),
      "This is the filter `build --standalone` writes: it has no BiS, exalted, legendary, shatter or hide-everything rules. "
      + "Start a full filter with New, or add them here."),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: addMissingSections }, "Add missing sections…"))));
}

/** Dialog: the template's sections the open filter lacks, made for a class and the Leveling tab's build (undo with Ctrl+Z). */
async function addMissingSections() {
  if (!S.doc) return;
  const dlg = $("#dlg");
  const o = levOpts();
  const clsSel = h("select", {}, h("option", { value: "" }, "none (class rules stay off)"),
    S.meta.enums.classes.map((c) => h("option", { value: c, selected: c === o.character_class }, c)));
  const preview = h("div", {});
  let res = null;
  const addBtn = h("button", { class: "primary", disabled: true, onclick: () => {
    mutate(() => { S.doc.rules = res.rules; clampSel(); }, { editor: true });
    dlg.close();
    toast(`${res.added.length} rules added. Undo with Ctrl+Z; save to keep them.` + (res.warnings.length ? ` ${res.warnings.join("; ")}` : ""));
  } }, "Add");
  let seq = 0;
  const load = async () => {
    const mine = ++seq;
    addBtn.disabled = true;
    fill(preview, h("p", { class: "hint" }, "Working out what's missing…"));
    try {
      const cls = clsSel.value;
      const r = await api("/api/complete", { rules: S.doc.rules,
        options: { character_class: cls } });
      if (mine !== seq) return;
      res = r;
    } catch (e) {
      if (mine === seq) fill(preview, h("p", { class: "bad" }, e.message));
      return;
    }
    const n = res.rules.length;
    fill(preview, 
      res.added.length ? h("p", {}, `${res.added.length} rules would be added (${n}/${S.meta.max_rules} rules then):`)
        : h("p", { class: "hint" }, "Nothing is missing: the filter has every section of the template."),
      res.added.length ? h("ul", { class: "gen-rules added-list" }, res.added.map((name) => h("li", {}, name))) : null,
      n > S.meta.max_rules ? h("p", { class: "bad" }, "That's over the game's rule limit: free up rules first.") : null);
    addBtn.disabled = !res.added.length || n > S.meta.max_rules;
  };
  clsSel.onchange = load;
  fill(dlg, h("h3", {}, "Add missing sections"),
    h("p", { class: "hint" }, `Adds the parts of the new-filter template (${S.meta.template.file}) this filter lacks - always-show affixes, BiS, `
      + "exalted and legendary, class hide, shatter, hide everything else - each where the template has it, and refreshes the [A] rules. "
      + "Rules already here stay as they are."),
    h("div", { class: "row fields" }, h("label", {}, "Class ", clsSel)),
    preview,
    h("div", { class: "row" }, h("button", { onclick: () => dlg.close() }, "Cancel"), addBtn));
  dlg.showModal();
  load();
}

const CLEANUPS = [
  ["separators", "Section separators",
    "Switched-off rules without conditions: headings that only decorate the list."],
  ["leveling", "Campaign leveling rules",
    "The generated leveling section, and every rule a character level condition switches off before the leveling cap: once the campaign is done they never match again."],
  ["common_uniques", "Most common uniques",
    "The generated rules for common and uncommon uniques below LP level 60 (random drops: no boss or quest uniques) at 0-2 LP. Those uniques then fall through to the rules below, usually the bottom hide rule."],
];

/** The generated sections - class hide rules, BiS rules, idol and leveling sections - moved back to their places (undo with Ctrl+Z). */
async function reorderSections() {
  if (!S.doc) return;
  try {
    const res = await api("/api/reorder", { rules: S.doc.rules,
      prefixes: { idols: idolOpts().rule_prefix, leveling: levOpts().rule_prefix } });
    if (!res.moved.length) { toast("The generated sections are already in their places."); return; }
    mutate(() => { S.doc.rules = res.rules; clampSel(); }, { editor: true });
    toast(`Moved back into place: ${res.moved.join(", ")}. Undo with Ctrl+Z; save to keep it.`);
  } catch (e) {
    toast(`Could not reorder: ${e.message}`, true);
  }
}

/** Where an affix is listed in the open filter's rules: [{rule, edit: [conditions it can go from], kept: [conditions
 *  listing only it]}]. Emptying a condition's list would make it match any affix, so those keep it. */
function affixUses(id) {
  const out = [];
  for (const r of S.doc.rules) {
    if (r.raw) continue;
    const conds = r.conditions.filter((c) => c.type === "AffixCondition" && !c.raw && c.affixes.includes(id));
    if (conds.length) out.push({ rule: r, edit: conds.filter((c) => c.affixes.some((x) => x !== id)),
      kept: conds.filter((c) => c.affixes.every((x) => x === id)) });
  }
  return out;
}

/** Where an affix is picked in the generator tabs: [{tab, short, label, edit: [places it goes from], kept: [places
 *  keeping it], keptNote, note, remove(), changed()}]. remove() takes it out of the edit places; changed() redraws the tab. */
function generatorAffixUses(id) {
  const out = [];
  const a = M.affix.get(id);
  // Leveling: the kinds of gear whose rules take it (from a toggle or a class affix pick) - it's left out there
  const res = S.lev.result, lo = levOpts();
  if (res && a) {
    const slots = levSlots(lo);
    // its own exclude list as well as the last result's: right after a change the result is a moment behind
    const gear = LEV_SECTIONS.filter(([s]) => slots[s].length && !(res.excluded?.[s] || []).includes(id) && !excludes(lo[sectionKey(s)], a)
      && (Object.values(res.picked[s] || {}).some((ids) => ids.includes(id))
        || (res.class_affixes.includes(id) && a.rolls_on.some((t) => sectionTypeIds(s).has(t)))));
    if (gear.length) {
      out.push({ tab: "leveling", short: "Leveling", label: "Leveling tab", edit: gear.map(([, l]) => l), kept: [],
        note: "left out of those kinds of gear's rules (tick it there to bring it back)", changed: levChanged,
        remove: () => { for (const [s] of gear) { const sec = lo[sectionKey(s)]; if (!excludes(sec, a)) sec.exclude.push(id); } } });
    }
  }
  // Best in slot: the slots listing it. A slot's only affix stays when it has bases: without it the slot would
  // show those bases whatever their affixes.
  const slots = Object.entries(bisOpts().slots || {}).filter(([, s]) => s.affixes?.includes(id));
  if (slots.length) {
    const sole = ([, s]) => s.affixes.every((x) => x === id) && Object.keys(s.bases || {}).length > 0;
    const label = ([k]) => bisSlotMeta(k)?.label || k;
    const edit = slots.filter((x) => !sole(x));
    out.push({ tab: "bis", short: "BiS", label: "Best in slot tab", edit: edit.map(label), kept: slots.filter(sole).map(label),
      keptNote: "the only affix those slots list: kept (without it they'd show their bases whatever their affixes)", changed: bisChanged,
      remove: () => { for (const [, s] of edit) s.affixes = s.affixes.filter((x) => x !== id); } });
  }
  // Idols: the idol kinds and the altar listing it (an idol kind left with no affix gets no rules)
  const io = idolOpts();
  const kinds = Object.entries(io.picks || {}).filter(([, p]) => p.affixes?.includes(id));
  const inAltar = !!io.altar?.affixes?.includes(id);
  if (kinds.length || inAltar) {
    const altarSole = inAltar && io.altar.affixes.length === 1 && io.altar.bases.length > 0;
    out.push({ tab: "idols", short: "Idols", label: "Idols tab",
      edit: [...kinds.map(([k, p]) => (idolKind(k)?.label || k) + (p.affixes.length === 1 ? " (its only affix: no rules for it then)" : "")),
        ...(inAltar && !altarSole ? ["Idol altar"] : [])],
      kept: altarSole ? ["Idol altar"] : [], changed: idolChanged,
      keptNote: "the only affix the preferred altars list: kept (without it they'd be its bases whatever their affixes)",
      remove: () => {
        for (const [k, p] of kinds) { p.affixes = p.affixes.filter((x) => x !== id); if (!p.affixes.length) delete io.picks[k]; }
        if (inAltar && !altarSole) io.altar.affixes = io.altar.affixes.filter((x) => x !== id);
      } });
  }
  return out;
}

/** Every affix the generator tabs pick (to list in the Remove an affix dialog). */
function generatorAffixIds() {
  const ids = new Set();
  const res = S.lev.result;
  if (res) {
    for (const toggles of Object.values(res.picked || {})) for (const list of Object.values(toggles)) list.forEach((x) => ids.add(x));
    res.class_affixes.forEach((x) => ids.add(x));
  }
  for (const s of Object.values(bisOpts().slots || {})) (s.affixes || []).forEach((x) => ids.add(x));
  const io = idolOpts();
  for (const p of Object.values(io.picks || {})) (p.affixes || []).forEach((x) => ids.add(x));
  (io.altar?.affixes || []).forEach((x) => ids.add(x));
  return ids;
}

const REMOVE_AFFIX_TITLE = "Take one affix out of the open filter's rules and the Leveling, Best in slot and Idols tabs' picks at once";
let removeAffixQuery = "";    // the dialog's filter text, kept for its next opening
let lastRemoval = null;       // {text, undo()}: what the dialog removed last, undoable while it stays open

/** The Remove an affix dialog, fresh (no earlier removal to undo). */
function openRemoveAffix() {
  lastRemoval = null;
  removeAffixEverywhere();
}

/** Dialog: pick an affix and take it out of the open filter's rules and the generator tabs' picks at once. */
function removeAffixEverywhere(selected = null) {
  const dlg = $("#dlg");
  const counts = new Map();
  for (const r of S.doc?.rules || []) {
    if (r.raw) continue;
    const ids = new Set(r.conditions.filter((c) => c.type === "AffixCondition" && !c.raw).flatMap((c) => c.affixes));
    for (const id of ids) counts.set(id, (counts.get(id) || 0) + 1);
  }
  const ruleLabel = (r) => r.name || `rule ${S.doc.rules.indexOf(r) + 1}`;
  const close = h("div", { class: "row" }, h("button", { class: "primary", onclick: () => dlg.close() }, "Close"));
  const title = h("h3", {}, "Remove an affix");
  const intro = h("p", { class: "hint" }, "Takes an affix out of the open filter's rules and out of the Leveling, Best in slot and Idols tabs' "
    + "picks at once, so applying a tab again doesn't bring it back. Pick an affix to see everywhere it's used; untick any place to leave it there.");
  const genUses = selected !== null ? generatorAffixUses(selected) : [];
  if (selected !== null && (counts.has(selected) || genUses.length)) {
    const uses = S.doc ? affixUses(selected) : [];
    const editable = uses.filter((u) => u.edit.length);
    const lowers = (c) => c.min_on_same_item > c.affixes.filter((x) => x !== selected).length;
    // the places, each with a tick: [{key, n (what it can go from), box}]
    const places = [];
    const btn = h("button", { class: "danger" });
    const refresh = () => {
      const on = places.filter((p) => p.box.checked && p.n);
      btn.disabled = !on.length;
      btn.textContent = on.length ? `Remove from ${on.map((p) => p.what).join(", ")}` : "Nothing ticked it can be removed from";
    };
    const place = (key, what, n, head, body) => {
      const box = h("input", { type: "checkbox", checked: n > 0, disabled: !n, onchange: refresh });
      places.push({ key, what, n, box });
      return h("div", { class: "remove-place" }, h("label", {}, box, h("b", {}, head)), body);
    };
    const parts = [];
    if (uses.length) {
      parts.push(place("rules", `${editable.length} rule${editable.length === 1 ? "" : "s"}`, editable.length, `Rules of the open filter (${uses.length})`,
        h("ul", { class: "gen-rules" }, uses.map((u) => h("li", {}, ruleLabel(u.rule),
          u.kept.length ? h("span", { class: "hint" }, " - the only affix it lists: kept (without it the rule would take any affix)") : null,
          u.edit.some(lowers) ? h("span", { class: "hint" }, " - asks for more affixes than it would have left: lowered to what's left") : null)))));
    }
    for (const g of genUses) {
      parts.push(place(g.tab, g.short, g.edit.length, g.label,
        h("div", { class: "remove-where" }, g.edit.length ? h("div", {}, g.edit.join(", "), g.note ? h("span", { class: "hint" }, ` - ${g.note}`) : null) : null,
          g.kept.length ? h("div", { class: "hint" }, `${g.kept.join(", ")}: ${g.keptNote}`) : null)));
    }
    // the Leveling tab's picks come from its last result: worked out again before the list is drawn
    const levelingNow = async (gens) => { if (gens.some((g) => g.tab === "leveling")) await runLeveling(); };
    btn.onclick = async () => {
      const on = new Set(places.filter((p) => p.box.checked && p.n).map((p) => p.key));
      const snap = { leveling: structuredClone(S.lev.opts), bis: structuredClone(S.bis.opts), idols: structuredClone(S.idol.opts) };
      const done = [];
      let ruleMark = null;
      if (on.has("rules")) {
        let n = 0;
        mutate(() => {
          for (const u of affixUses(selected)) {
            if (!u.edit.length) continue;
            n++;
            for (const c of u.edit) {
              c.affixes = c.affixes.filter((x) => x !== selected);
              c.min_on_same_item = Math.min(c.min_on_same_item, c.affixes.length);
            }
          }
        }, { editor: true });
        ruleMark = S.undo.length;
        done.push(`${n} rule${n === 1 ? "" : "s"}`);
      }
      const gens = genUses.filter((g) => on.has(g.tab));
      for (const g of gens) { g.remove(); g.changed(); done.push(`${g.label} (${g.edit.length})`); }
      const name = affixName(selected);
      lastRemoval = {
        text: `${name} removed from ${done.join(", ")}.` + (on.has("rules") ? " Save to keep the rules' change." : ""),
        undo: async () => {
          if (ruleMark != null && S.undo.length === ruleMark) undo();   // unless the rules changed again since
          for (const g of gens) {
            if (g.tab === "leveling") S.lev.opts = snap.leveling; else if (g.tab === "bis") S.bis.opts = snap.bis; else S.idol.opts = snap.idols;
            g.changed();
          }
          lastRemoval = null;
          await levelingNow(gens);
          toast(`${name} is back where it was.`);
          removeAffixEverywhere();
        },
      };
      await levelingNow(gens);
      removeAffixEverywhere();   // its list says what was removed, with Undo
    };
    refresh();
    fill(dlg, title, intro,
      h("div", { class: "row" }, h("b", {}, affixName(selected)), affixPill(selected), h("span", { class: "spacer" }),
        h("button", { onclick: () => removeAffixEverywhere() }, "← Other affix")),
      parts, h("div", { class: "row" }, btn), close);
  } else {
    const search = h("input", { type: "search", placeholder: "Filter affixes…", style: { width: "100%" }, value: removeAffixQuery });
    const list = h("div", { class: "remove-affix-list" });
    const gen = generatorAffixIds();
    const items = [...new Set([...counts.keys(), ...gen])]
      .map((id) => ({ id, n: counts.get(id) || 0, uses: gen.has(id) ? generatorAffixUses(id) : [] }))
      .filter((x) => x.n || x.uses.length)
      .sort((a, b) => compareAffixes(a.id, b.id))
      .map((x) => ({ ...x, name: affixName(x.id), group: affixGroup(M.affix.get(x.id)) }));
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      removeAffixQuery = search.value;
      let group = null;
      fill(list, ...items.filter((x) => !q || x.name.toLowerCase().includes(q)).flatMap((x) => [
        x.group !== group ? h("div", { class: "grp" }, (group = x.group)) : null,
        h("button", { class: "affix-row", onclick: () => removeAffixEverywhere(x.id) }, x.name, affixPill(x.id),
          h("span", { class: "hint" }, " " + [x.n ? `${x.n} rule${x.n > 1 ? "s" : ""}` : null,
            ...x.uses.map((u) => `${u.short} ${u.edit.length + u.kept.length}`)].filter(Boolean).join(" · ")))]));
      if (!list.children.length) list.append(h("p", { class: "hint" }, items.length ? "No affix matches." : "No rule or generator tab picks any affix."));
    };
    search.oninput = draw;
    draw();
    fill(dlg, title, intro,
      lastRemoval ? h("div", { class: "box notice row" }, h("span", {}, lastRemoval.text), h("span", { class: "spacer" }),
        h("button", { onclick: lastRemoval.undo }, "Undo")) : null,
      search, list, close);
    // the last filter text comes back, selected: typing replaces it
    setTimeout(() => { search.focus(); search.select(); }, 0);
  }
  if (!dlg.open) dlg.showModal();
}

/** Dialog: the template's exalted & legendary section put back - only the rules the filter lacks, or all of
 *  it in place of the filter's (undo with Ctrl+Z). Only asks when there's a choice to make. */
async function restoreExalted() {
  if (!S.doc) return;
  let res;
  try {
    res = await api("/api/restore", { rules: S.doc.rules });
  } catch (e) {
    toast(`Could not read the new-filter template: ${e.message}`, true);
    return;
  }
  if (res.matches) { toast("The exalted section already is the template's."); return; }
  const dlg = $("#dlg");
  const n = (way) => res[way].rules.length;
  const apply = (way, done) => {
    mutate(() => { S.doc.rules = res[way].rules; clampSel(); }, { editor: true });
    dlg.close();
    toast(`${done} Undo with Ctrl+Z; save to keep it.`);
  };
  const names = (title, list) => list.length
    ? h("details", {}, h("summary", {}, `${title} (${list.length})`), h("ul", { class: "gen-rules" }, list.map((x) => h("li", {}, x)))) : null;
  const limit = (way) => n(way) > S.meta.max_rules
    ? h("p", { class: "bad" }, `That makes ${n(way)}/${S.meta.max_rules} rules: free up rules first.`) : null;
  const plural = (k) => `${k} rule${k === 1 ? "" : "s"}`;
  const { added } = res.add;
  const addBox = h("div", { class: "box" },
    h("div", { class: "row" }, h("b", {}, "Only add missing ones"), h("span", { class: "spacer" }),
      h("button", { class: "primary", disabled: !added.length || n("add") > S.meta.max_rules,
        onclick: () => apply("add", `${plural(added.length)} added to the exalted section.`) },
        added.length ? `Add ${plural(added.length)}` : "Nothing missing")),
    h("p", { class: "hint" }, added.length ? "Each goes in after the rule it follows in the template; the rules already here stay as they are."
      : "Every rule of the template's section is here; some differ from the template's - replacing takes the template's."),
    names("Rules it adds", added), limit("add"));
  const replaceBox = h("div", { class: "box" },
    h("div", { class: "row" }, h("b", {}, "Replace all exalted rules"), h("span", { class: "spacer" }),
      h("button", { class: "danger", disabled: n("replace") > S.meta.max_rules,
        onclick: () => apply("replace", `The exalted section replaced by the template's (${plural(res.replace.added.length)}).`) }, "Replace")),
    h("p", { class: "hint" }, "Takes out this filter's section - with your own rules in it and your changes to its rules - and puts the template's in its place."),
    names("Rules it removes", res.replace.removed), names("Rules it puts in", res.replace.added), limit("replace"));
  fill(dlg, h("h3", {}, "Restore exalted section"),
    h("p", { class: "hint" }, `Puts the new-filter template's "${res.header}" section (${S.meta.template.file}) - its exalted, corrupted and legendary rules - back into this filter.`),
    res.found ? [h("p", {}, "Do you want to replace all exalted rules, or only add missing ones?"), addBox, replaceBox]
      : [h("p", {}, "This filter has no exalted section: the template's goes after the BiS section (else before the uniques)."),
        names("Rules it adds", added), limit("add")],
    h("div", { class: "row" }, h("button", { onclick: () => dlg.close() }, "Cancel"),
      res.found ? null : h("button", { class: "primary", disabled: n("add") > S.meta.max_rules,
        onclick: () => apply("add", `The exalted section added (${plural(added.length)}).`) }, "Add it")));
  dlg.showModal();
}

/** Dialog: what each way of freeing rules would remove, with a button to do it (undo with Ctrl+Z). */
async function freeUpRules() {
  if (!S.doc) return;
  const dlg = $("#dlg");
  const o = levOpts();
  let res;
  try {
    res = await api("/api/cleanup", { rules: S.doc.rules, leveling: { prefix: o.rule_prefix, cap: o.cap } });
  } catch (e) {
    toast(`Could not check the rules: ${e.message}`, true);
    return;
  }
  const n = S.doc.rules.length;
  fill(dlg, h("h3", {}, "Free up rules"),
    h("p", { class: "hint" }, `${n}/${S.meta.max_rules} rules. Removing is undone with Ctrl+Z. Regenerating the [A] rules or applying a generator again brings its removed rules back.`),
    ...CLEANUPS.map(([kind, title, what]) => {
      const { removed } = res[kind];
      return h("div", { class: "box" },
        h("div", { class: "row" }, h("b", {}, title), h("span", { class: "spacer" }),
          h("button", { class: "danger", disabled: !removed.length, onclick: () => {
            mutate(() => { S.doc.rules = res[kind].rules; clampSel(); }, { editor: true });
            toast(`Removed ${removed.length} rules (${title.toLowerCase()}). Undo with Ctrl+Z.`);
            freeUpRules();
          } }, removed.length ? `Remove ${removed.length} rule${removed.length > 1 ? "s" : ""}` : "Nothing to remove")),
        h("p", { class: "hint" }, what),
        removed.length ? h("details", {}, h("summary", {}, "Rules it removes"), h("ul", { class: "gen-rules" }, removed.map((name) => h("li", {}, name)))) : null);
    }),
    h("div", { class: "row" }, h("button", { class: "primary", onclick: () => dlg.close() }, "Close")));
  if (!dlg.open) dlg.showModal();
}

/* ---------- top-level rendering ---------- */

function renderStatus() {
  const st = $("#status");
  $("#btn-delete").disabled = !S.file || S.file.location === "template";
  if (!S.doc) { st.textContent = "No filter open"; return; }
  const n = S.doc.rules.length;
  fill(st, 
    S.file ? `${{ game: "game", out: "out", template: "templates" }[S.file.location]}/${S.file.file}` : "unsaved",
    " · ", h("span", { class: n > S.meta.max_rules ? "bad" : "" }, `${n}/${S.meta.max_rules} rules`),
    S.dirty ? h("span", { class: "dirty" }, " · unsaved changes") : "",
    ` · game ${S.meta.game_version || "?"} · editor ${S.meta.app_version || "?"}`);
  $("#btn-undo").disabled = !S.undo.length;
  $("#btn-redo").disabled = !S.redo.length;
}

function renderHeader() {
  const btn = $("#hdr-icon");
  fill(btn, S.doc ? filterIcon(S.doc.header.icon || 0, S.doc.header.icon_color || 0, 20) : "");
  btn.disabled = !S.doc;
  const name = $("#hdr-name"), desc = $("#hdr-desc");
  name.value = S.doc?.header.name || "";
  desc.value = S.doc?.header.description || "";
  name.disabled = desc.disabled = !S.doc;
}

function renderDoc() {
  renderHeader();
  renderStatus();
  renderList();
  renderEditor();
  testSoon();
}

/* ---------- rule list ---------- */

function ruleSwatch(r) {
  if (isRaw(r)) return h("span", { class: "swatch none", title: "unrecognised rule" });
  if (r.type === "HIDE") return h("span", { class: "swatch", style: { background: "#2a2024" }, title: "hide" });
  if (!r.recolor) return h("span", { class: "swatch none", title: "default colour" });
  return h("span", { class: "swatch", style: { background: filterColor(r.color) }, title: `colour ${r.color}` });
}

let dragFrom = null;
const dropAfter = (li, e) => { const r = li.getBoundingClientRect(); return e.clientY > r.top + r.height / 2; };

function renderList() {
  const ol = $("#rule-list");
  ol.replaceChildren();
  renderDocNotice();
  if (!S.doc) { put(ol, h("li", { class: "empty" }, "Choose a filter above, or start a new one.")); return; }
  const q = S.search.toLowerCase();
  S.doc.rules.forEach((r, i) => {
    if (q && !(r.name || "").toLowerCase().includes(q)) return;
    const raw = isRaw(r);
    const cls = ["rule-row"];
    if (i === S.sel) cls.push("selected");
    if (!raw && !r.enabled) cls.push("disabled");
    if (isSeparator(r)) cls.push("separator");
    if (S.lvl.on && !raw && r.enabled && !activeAt(r, S.lvl.level)) cls.push("inactive");
    const todo = todoNote(r);
    if (todo) cls.push("todo");
    const badge = raw ? h("span", { class: "badge" }, "RAW")
      : isSeparator(r) ? null : h("span", { class: "badge " + (r.type === "HIDE" ? "hide" : "show") }, r.type);
    const li = h("li", {
      class: cls.join(" "), draggable: "true", "data-i": i,
      onclick: () => { S.sel = i; renderList(); renderEditor(); },
      ondragstart: (e) => { dragFrom = i; e.dataTransfer.effectAllowed = "move"; },
      ondragend: () => { dragFrom = null; },
      ondragover: (e) => {
        if (dragFrom == null) return;   // text or files dragged in: not a rule move
        e.preventDefault();
        const after = dropAfter(li, e);
        li.classList.toggle("drop-after", after); li.classList.toggle("drop-before", !after);
      },
      ondragleave: () => li.classList.remove("drop-after", "drop-before"),
      ondrop: (e) => {
        li.classList.remove("drop-after", "drop-before");
        if (dragFrom == null) return;
        e.preventDefault();
        const from = dragFrom;
        dragFrom = null;
        moveRule(from, i + (dropAfter(li, e) ? 1 : 0));
      },
    },
    h("span", { class: "rule-idx" }, i + 1),
    raw ? h("span") : h("input", { type: "checkbox", checked: r.enabled, title: "enabled",
      onclick: (e) => e.stopPropagation(),
      onchange: (e) => mutate(() => { r.enabled = e.target.checked; }) }),
    ruleSwatch(r),
    h("div", { class: "rule-main" },
      h("div", { class: "rule-name", title: r.name }, todo ? h("span", { class: "badge todo", title: `Optional, for your build: ${todo}` }, "to fill in") : null,
        badge, r.name || (raw ? "(unrecognised rule, kept as is)" : "(unnamed)")),
      raw || isSeparator(r) ? null : h("div", { class: "rule-chips" }, r.conditions.map((c) => h("span", { class: "chip-s" }, condSummary(c))))));
    put(ol, li);
  });
}

function moveRule(from, to) {
  if (from == null || !S.doc) return;
  if (to > from) to -= 1;
  if (to === from) { renderList(); return; }
  mutate(() => {
    const [r] = S.doc.rules.splice(from, 1);
    S.doc.rules.splice(to, 0, r);
    S.sel = to;
  }, { editor: true });
}

function scrollToSel() {
  const li = document.querySelector(`.rule-row[data-i="${S.sel}"]`);
  if (li) li.scrollIntoView({ block: "nearest" });
}

/* ---------- rule editor ---------- */

function palette(colors, current, onPick, { allowDefault = true, defaultLabel = "default" } = {}) {
  return h("div", { class: "palette" },
    allowDefault ? h("span", { class: "swatch none" + (current == null ? " on" : ""), title: defaultLabel, onclick: () => onPick(null) }) : null,
    colors.map((c, i) => h("span", { class: "swatch" + (current === i ? " on" : ""), style: { background: c }, title: `${i}`, onclick: () => onPick(i) })));
}

function chipToggle(label, on, onToggle, extra, countKey) {
  return h("span", { class: "chip" + (on ? " on" : ""), onclick: onToggle }, label,
    extra != null || countKey ? h("span", { class: "n", "data-count": countKey }, extra ?? "") : null);
}

function numInput(value, onSet, { min, max, nullable = false, width } = {}) {
  return h("input", { type: "number", value: value ?? "", min, max, placeholder: nullable ? "any" : null, style: width ? { width } : null,
    onchange: (e) => {
      const v = e.target.value.trim();
      onSet(v === "" ? (nullable ? null : 0) : Number(v));
    } });
}

function rulePreviewLabel(r) {
  const rarity = r.conditions.find((c) => c.type === "RarityCondition" && !c.raw)?.rarity?.[0] || "RARE";
  return labelPreview({ show: r.type !== "HIDE", recolor: r.recolor, color: r.color, emphasized: r.emphasized,
    beam_override: r.beam_override, beam_size: r.beam_size, beam_color: r.beam_color }, rarity, "Item name");
}

function labelPreview(look, rarity, text) {
  const color = look.recolor ? filterColor(look.color) : rarityColor(rarity);
  const sizes = { LARGEST: 80, VERYLARGE: 68, LARGE: 56, MEDIUM: 44, SMALL: 32, VERYSMALL: 22, SMALLEST: 14 };
  const beam = look.show && look.beam_override && look.beam_size !== "NONE"
    ? h("div", { class: "beam", style: { height: `${sizes[look.beam_size] || 0}px`, background: `linear-gradient(${beamColor(look.beam_color)}, transparent)` } })
    : null;
  return h("div", { class: "label-preview" }, beam,
    h("div", { class: "ground-label" + (look.emphasized ? " emph" : "") + (look.show ? "" : " hidden-item"), style: { color } }, text),
    h("span", { class: "hint" }, look.show ? (look.recolor ? "recoloured" : `${cap(rarity)} default colour`) : "hidden"));
}

function renderEditor() {
  const ed = $("#editor");
  ed.replaceChildren();
  if (!S.doc || S.sel < 0 || S.sel >= S.doc.rules.length) {
    put(ed, h("div", { class: "empty" }, S.doc ? "Select a rule to edit it." : ""));
    return;
  }
  const r = S.doc.rules[S.sel];
  if (isRaw(r)) {
    put(ed, h("h2", {}, `Rule ${S.sel + 1}: unrecognised layout`),
      h("p", { class: "hint" }, "This rule has elements this editor doesn't know. It is written back exactly as it was; edit the XML only if you know the format."),
      h("textarea", { value: r.raw, style: { minHeight: "400px" }, onchange: (e) => mutate(() => { r.raw = e.target.value; }) }));
    return;
  }
  const refreshList = () => renderList();
  put(ed, 
    h("h2", {}, `Rule ${S.sel + 1} of ${S.doc.rules.length}`),
    h("input", { class: "field-name", value: r.name, placeholder: "Rule name (empty = the game shows a generated description)",
      oninput: (e) => mutate(() => { r.name = e.target.value; }, { typing: true }) }),
    h("div", { class: "row" },
      h("div", { class: "seg" },
        ["SHOW", "HIDE"].map((t) => h("button", { class: r.type === t ? "on" : "", onclick: () => mutate(() => { r.type = t; }, { editor: true }) }, cap(t)))),
      h("label", {}, h("input", { type: "checkbox", checked: r.enabled, onchange: (e) => mutate(() => { r.enabled = e.target.checked; }) }), "Enabled"),
      isSeparator(r) ? h("span", { class: "hint" }, "No conditions: matches every item (a disabled one is just a section header).") : null),
    todoNote(r) ? h("div", { class: "todo-note" }, h("span", { class: "badge todo" }, "to fill in"),
      h("span", {}, `Optional, for your build: ${todoNote(r)}.`)) : null);

  // appearance
  put(ed, h("h3", {}, "Appearance"));
  if (r.type === "HIDE") {
    put(ed, h("p", { class: "hint" }, "Hidden items don't use colour, sound or beam settings."));
  }
  put(ed, 
    h("div", { class: "row" }, h("span", { class: "hint", style: { width: "80px" } }, "Text colour"),
      palette(S.meta.palette.filter, r.recolor ? r.color : null, (i) => mutate(() => {
        if (i == null) r.recolor = false; else { r.recolor = true; r.color = i; }
      }, { editor: true }))),
    h("div", { class: "row" },
      h("label", {}, h("input", { type: "checkbox", checked: r.emphasized, onchange: (e) => mutate(() => { r.emphasized = e.target.checked; }, { editor: true }) }), "Emphasized"),
      h("label", { title: "0 = default drop sound, 1 = no sound, 2+ = the game's loot-filter sound list" }, "Sound", numInput(r.sound, (v) => mutate(() => { r.sound = v; }), { min: 0 })),
      h("label", { title: "0 = default; other numbers as picked in-game" }, "Map icon", numInput(r.map_icon, (v) => mutate(() => { r.map_icon = v; }), { min: 0 }))),
    h("div", { class: "row" },
      h("label", {}, h("input", { type: "checkbox", checked: r.beam_override, onchange: (e) => mutate(() => { r.beam_override = e.target.checked; }, { editor: true }) }), "Beam override"),
      h("select", { disabled: !r.beam_override, onchange: (e) => mutate(() => { r.beam_size = e.target.value; }, { editor: true }) },
        S.meta.enums.beam_sizes.map((b) => h("option", { value: b, selected: b === r.beam_size }, cap(b))))),
    r.beam_override ? h("div", { class: "row" }, h("span", { class: "hint", style: { width: "80px" } }, "Beam colour"),
      palette(S.meta.palette.beam, r.beam_color, (i) => mutate(() => { r.beam_color = i; }, { editor: true }), { allowDefault: false })) : null,
    rulePreviewLabel(r));

  // conditions
  put(ed, h("h3", {}, "Conditions (all must match)"));
  if (!r.conditions.length) put(ed, h("p", { class: "hint" }, "No conditions."));
  r.conditions.forEach((c, ci) => put(ed, conditionCard(r, c, ci, refreshList)));
  const types = [...Object.keys(COND_LABELS)];
  const addSel = h("select", {}, h("option", { value: "" }, "+ Add condition…"),
    types.map((t) => h("option", { value: t }, condLabel(t))));
  addSel.addEventListener("change", () => {
    if (!addSel.value) return;
    const type = addSel.value;
    mutate(() => { r.conditions.push(newCondition(type)); }, { editor: true });
  });
  put(ed, h("div", { class: "row" }, addSel));
}

function conditionCard(rule, c, ci, refreshList) {
  const card = h("div", { class: "cond" },
    h("div", { class: "cond-head" }, h("b", {}, condLabel(c.type)), h("span", { class: "hint" }, condSummary(c)),
      h("span", { class: "spacer" }),
      h("button", { title: "Move up", disabled: ci === 0, onclick: () => mutate(() => { rule.conditions.splice(ci - 1, 0, rule.conditions.splice(ci, 1)[0]); }, { editor: true }) }, "▲"),
      h("button", { title: "Remove condition", onclick: () => mutate(() => { rule.conditions.splice(ci, 1); }, { editor: true }) }, "✕")));
  const body = conditionBody(rule, c);
  put(card, body);
  return card;
}

function conditionBody(rule, c) {
  const re = { editor: true };
  if (c.raw) {
    return h("div", {}, h("p", { class: "hint" }, "Layout not recognised; kept as raw XML."),
      h("textarea", { value: c.raw, onchange: (e) => mutate(() => { c.raw = e.target.value; }) }));
  }
  const toggleIn = (arr, v) => { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); };
  switch (c.type) {
    case "RarityCondition":
      return h("div", { class: "chips" }, S.meta.enums.rarities.map((rr) =>
        chipToggle(cap(rr), c.rarity.includes(rr), () => mutate(() => {
          toggleIn(c.rarity, rr);
          c.rarity.sort((a, b) => S.meta.enums.rarities.indexOf(a) - S.meta.enums.rarities.indexOf(b));
        }, re))));
    case "SubTypeCondition": return subtypeEditor(rule, c);
    case "AffixCondition": return affixEditor(rule, c);
    case "CharacterLevelCondition":
      return h("div", { class: "row" }, "From level", numInput(c.min, (v) => mutate(() => { c.min = v; }, re), { min: 0, max: 100 }),
        "to", numInput(c.max, (v) => mutate(() => { c.max = v; }, re), { min: 0, max: 100 }), h("span", { class: "hint" }, "inclusive"));
    case "PotentialCondition":
      return h("div", {}, [["lp", "Legendary potential"], ["ww", "Weaver's will"], ["wt", "Weaver's touch"], ["fp", "Forging potential"]].map(([k, label]) =>
        h("div", { class: "row" }, h("span", { style: { width: "150px" } }, label),
          "min", numInput(c[`${k}_min`], (v) => mutate(() => { c[`${k}_min`] = v; }, re), { min: 0, nullable: true }),
          "max", numInput(c[`${k}_max`], (v) => mutate(() => { c[`${k}_max`] = v; }, re), { min: 0, nullable: true }))));
    case "ClassCondition":
      return h("div", {}, h("div", { class: "chips" }, S.meta.enums.classes.map((cl) =>
        chipToggle(cl, c.classes.includes(cl), () => mutate(() => {
          toggleIn(c.classes, cl);
          c.classes.sort((a, b) => S.meta.enums.classes.indexOf(a) - S.meta.enums.classes.indexOf(b));
        }, re)))), h("p", { class: "hint" }, "Matches class-specific items of the selected classes; none selected = any item."),
        !c.classes.length && rule.type === "HIDE" && rule.enabled
          ? h("p", { class: "warn" }, "⚠ With no class selected this hide rule hides every item its other conditions match.") : null);
    case "UniqueModifiersCondition": return uniquesEditor(c, rule);
    case "CorruptionCondition":
      return h("select", { onchange: (e) => mutate(() => { c.corruption = e.target.value; }, re) },
        S.meta.enums.corruption.map((v) => h("option", { value: v, selected: v === c.corruption }, v.replace(/([a-z])([A-Z])/g, "$1 $2"))));
    case "FactionCondition":
      // The game offers the two trade factions; others only show up when a loaded filter already has them.
      return h("div", { class: "chips" }, [...new Set([...S.meta.enums.factions, ...c.factions])].map((f) =>
        chipToggle(factionLabel(f), c.factions.includes(f), () => mutate(() => { toggleIn(c.factions, f); }, re))));
    case "AffixCountCondition":
      return h("div", {},
        h("div", { class: "row" }, "Prefixes", numInput(c.prefix_min, (v) => mutate(() => { c.prefix_min = v; }, re), { nullable: true }), "to",
          numInput(c.prefix_max, (v) => mutate(() => { c.prefix_max = v; }, re), { nullable: true })),
        h("div", { class: "row" }, "Suffixes", numInput(c.suffix_min, (v) => mutate(() => { c.suffix_min = v; }, re), { nullable: true }), "to",
          numInput(c.suffix_max, (v) => mutate(() => { c.suffix_max = v; }, re), { nullable: true })),
        h("div", { class: "row" }, "Sealed", h("select", { onchange: (e) => mutate(() => { c.sealed = e.target.value; }, re) },
          S.meta.enums.sealed.map((v) => h("option", { value: v, selected: v === c.sealed }, v)))));
    case "LevelCondition":
      return h("div", { class: "row" },
        h("select", { onchange: (e) => mutate(() => { c.level_type = e.target.value; }, re) },
          S.meta.enums.level_types.map((v) => h("option", { value: v, selected: v === c.level_type }, cap(v.replaceAll("_", " "))))),
        numInput(c.threshold, (v) => mutate(() => { c.threshold = v; }, re), { min: 0 }));
    default: {
      const fc = S.meta.enums.flag_conditions[c.type];
      if (!fc) return h("p", { class: "hint" }, "No editor for this condition.");
      return h("div", { class: "chips" }, fc.flags.map((f) =>
        chipToggle(f.replace(/([a-z])([A-Z0-9])/g, "$1 $2"), c.flags.includes(f), () => mutate(() => { toggleIn(c.flags, f); }, re))));
    }
  }
}

/** Class bits a rule's Class Requirement condition selects (0: none, or no such condition). */
function ruleClassBits(rule) {
  const cc = rule.conditions.find((x) => x.type === "ClassCondition" && !x.raw);
  return (cc?.classes || []).reduce((bits, cl) => bits | (1 << S.meta.enums.classes.indexOf(cl)), 0);
}

function subtypeEditor(rule, c) {
  const re = { editor: true };
  const wrap = h("div", {});
  for (const [cat, bases] of basesByCategory()) {
    put(wrap, h("div", { class: "group-label" }, cat),
      h("div", { class: "chips" }, bases.map((b) => chipToggle(b.name, c.types.includes(b.type), () => mutate(() => {
        const i = c.types.indexOf(b.type);
        if (i >= 0) c.types.splice(i, 1); else c.types.push(b.type);
        c.subtypes = [];   // the game resets the base selection when the types change
      }, re)))));
  }
  if (c.types.length === 1) {
    const base = M.base.get(c.types[0]);
    // With a Class Requirement, the game matches items whose class requirement is all within the
    // selected classes (ClassCondition). Class bases have their own; a legendary on a generic base
    // takes the class of its first single-class affix (ItemData.CalculateLevelAndClassRequirement),
    // so on types those affixes roll on (helmets, body armours, relics) generic bases can match too.
    const bits = ruleClassBits(rule);
    const classAffixTypes = (S.classAffixTypes ||= new Set(Object.values(S.meta.class_affixes).flat()
      .flatMap((id) => M.affix.get(id)?.rolls_on || [])));
    const legendaryToo = !!base && classAffixTypes.has(base.id);
    const fits = (s) => !bits || (s.class ? (s.class & bits) === s.class : legendaryToo);
    const all = [...(base?.subtypes || [])].sort((a, b) => a.level - b.level || a.id - b.id);
    const subs = all.filter(fits);
    const known = new Set(all.map((s) => s.id));
    const ruledOut = c.subtypes.filter((id) => known.has(id) && !subs.some((s) => s.id === id));
    const unknown = c.subtypes.filter((id) => !known.has(id));
    const classNames = S.meta.enums.classes.filter((cl, i) => bits & (1 << i)).join(" / ");
    put(wrap, h("div", { class: "group-label" }, `Bases of ${base?.name}${bits ? ` for ${classNames}` : ""} (none ticked = all)`),
      bits ? h("p", { class: "hint" }, legendaryToo
        ? `With the Class Requirement condition, ${classNames} bases match, and other bases only as legendaries with a ${classNames} affix.`
        : subs.length ? `With the Class Requirement condition only ${classNames} bases can match, so only they are listed.`
          : `No ${base?.name} base is ${classNames}-specific: with the Class Requirement condition this rule matches no ${base?.name}.`) : null,
      ruledOut.length ? h("p", { class: "warn" }, `⚠ ${ruledOut.length} ticked base${ruledOut.length > 1 ? "s" : ""} can't match the selected classes `
        + `(${ruledOut.map((id) => all.find((s) => s.id === id)?.name || `#${id}`).join(", ")}). `,
      h("button", { onclick: () => mutate(() => { c.subtypes = c.subtypes.filter((id) => !ruledOut.includes(id)); }, re) },
        ruledOut.length > 1 ? "Remove them" : "Remove it")) : null,
      unknown.length ? h("p", { class: "hint" }, `${unknown.length} ticked base${unknown.length > 1 ? "s aren't" : " isn't"} in this game data `
        + `(#${unknown.join(", #")}): kept as they are.`) : null,
      h("div", { class: "row" },
        h("button", { disabled: !subs.some((s) => s.drops), onclick: () => mutate(() => { c.subtypes = subs.filter((s) => s.drops).map((s) => s.id); }, re) }, "All droppable"),
        h("button", { onclick: () => mutate(() => { c.subtypes = []; }, re) }, "Clear")),
      h("div", { class: "bases" }, subs.map((s) => withBaseTip(h("label", { class: s.drops ? "" : "nodrop" },
        h("input", { type: "checkbox", checked: c.subtypes.includes(s.id), onchange: () => mutate(() => {
          const i = c.subtypes.indexOf(s.id);
          if (i >= 0) c.subtypes.splice(i, 1); else c.subtypes.push(s.id);
        }) }),
        s.name, h("span", { class: "lvl" }, `lvl ${s.level}`)), c.types[0], s))));
  } else if (c.types.length > 1) {
    put(wrap, h("p", { class: "hint" }, "Bases can only be picked with exactly one item type (with several, the game ignores bases)."));
  }
  return wrap;
}

function ruleTypeIds(rule) {
  const ids = new Set();
  for (const c of rule.conditions) {
    if (c.type === "SubTypeCondition" && !c.raw) c.types.forEach((t) => { const b = M.base.get(t); if (b) ids.add(b.id); });
  }
  return ids;
}

/* ---------- affix values as the game shows them ---------- */

/** For a rule that targets omen idols only (one idol type, only its omen bases picked): the ids
 *  of the affixes those omen idols roll (they add the 4x1 / 1x4 / 2x2 affixes and use the omen
 *  modifier instead of the idol type's). null for any other rule. */
/** Affixes the omen bases an idol rule can match roll on top of its type's own (no bases picked:
 *  every omen base of the type; mixed: the picked omen ones) - null when it matches none. */
function ruleOmenExtra(rule) {
  const c = rule.conditions.find((x) => x.type === "SubTypeCondition" && !x.raw);
  if (!c || c.types.length !== 1) return null;
  const kinds = S.meta.idol_kinds.filter((k) => k.variant === "omen" && k.type === c.types[0]
    && (!c.subtypes?.length || c.subtypes.some((id) => k.subtypes.includes(id))));
  return kinds.length ? new Set(kinds.flatMap((k) => k.pool.map((p) => p.id))) : null;
}

function ruleOmenPool(rule) {
  const c = rule.conditions.find((x) => x.type === "SubTypeCondition" && !x.raw);
  if (!c || c.types.length !== 1 || !c.subtypes?.length) return null;
  const base = M.base.get(c.types[0]);
  if (!base || !c.subtypes.every((id) => base.subtypes.find((s) => s.id === id)?.omen)) return null;
  const kinds = S.meta.idol_kinds.filter((k) => k.variant === "omen" && k.type === c.types[0]
    && c.subtypes.some((id) => k.subtypes.includes(id)));
  return new Set(kinds.flatMap((k) => k.pool.map((p) => p.id)));
}

/** Round half to even in single precision, as the game rounds values. */
function roundEven(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r;
}

/** One value's magnitude the way the tooltip prints it (no sign / % yet). */
function fmtNumber(v, line) {
  const f = Math.round(1 / line.step);
  const x = roundEven(Math.fround(Math.fround(v) * f)) / f * line.mult;
  return String(+x.toFixed(3));
}

/** Signed value or range: "+4%", "+4-5%", "-5 to -10"; a and b are fmtNumber texts (or "x"). */
function valueRange(line, a, b = a) {
  const pct = line.percent ? "%" : "";
  if (a === b) return `${line.sign}${a}${pct}`;
  if (line.sign === "-") return `-${a}${pct} to -${b}${pct}`;
  return `${line.sign}${a}-${b}${pct}`;
}

/** "+4% Cold Penetration": valueText goes where "{0}" is, else before the text (after it in
 *  languages that put values last); stats the game shows without a value stay text only. */
function lineText(line, valueText) {
  if (line.hide) return line.text.replace(/\s*\{0\}\s*/g, " ").trim();   // shown without its value
  if (line.text.includes("{0}")) return line.text.replace("{0}", valueText);
  return S.meta.value_after ? `${line.text} ${valueText}` : `${valueText} ${line.text}`;
}

/** A tier's range "+4-5%", or the single value. */
function tierRangeText(line, tier, scale) {
  const [lo, hi] = line.tiers[tier];
  if (line.signed) {   // a unique mod rolling across zero: "-20% to +50%"
    const pct = line.percent ? "%" : "";
    const one = (v) => `${v < 0 ? "-" : line.sign === "+" ? "+" : ""}${fmtNumber(Math.abs(scaled(v, scale)), line)}${pct}`;
    return `${one(lo)} to ${one(hi)}`;
  }
  return valueRange(line, fmtNumber(scaled(lo, scale), line), fmtNumber(scaled(hi, scale), line));
}

/** Value scale on an item type: (1 + type modifier) / (1 + the affix's standard modifier); omen
 *  idols use the omen modifier. 1 when the affix doesn't roll on that type. */
function affixScale(affix, typeIds, omen = false) {
  if (!typeIds || typeIds.size !== 1) return 1;
  const id = [...typeIds][0];
  const base = M.baseById.get(id);
  if (!base) return 1;
  if (!omen && affix.rolls_on && !affix.rolls_on.includes(id)) return 1;
  const mod = omen ? (S.meta.omen_affix_mod ?? 0) : base.affix_mod;
  const std = affix.std || 0;
  if (mod == null || mod === std) return 1;
  // Affix.getModifier, in single precision like the game: (1 + mod) / (1 + std) - 1, then 1 + that
  const f = Math.fround;
  return f(1 + f(f(f(mod + 1) / f(std + 1)) - 1));
}

/** A roll on another item type: roll x scale, in single precision like the game. */
const scaled = (v, scale) => (scale === 1 ? v : Math.fround(Math.fround(v) * scale));

/** Tiers a rule's advanced tier comparison allows, as [lo, hi] (1-based), null = any, [] = none. */
function conditionTiers(c, count) {
  if (!c || !c.advanced || c.comparsion === "ANY") return null;
  const v = Math.round(Number(c.comparsion_value) || 0);
  const [lo, hi] = { EQUAL: [v, v], LESS: [1, v - 1], LESS_OR_EQUAL: [1, v], MORE: [v + 1, count], MORE_OR_EQUAL: [v, count] }[c.comparsion] || [1, count];
  const range = [Math.max(1, lo), Math.min(count, hi)];
  return range[0] > range[1] ? [] : range;
}

/** What the affix looks like: "+x% Cold Penetration" (values on hover), a single tier's values,
 *  or, with tiers selected, "+(min at lowest/min at highest)-(max at lowest/max at highest)". */
function affixValueSummary(affix, tiers, scale) {
  if (!affix.lines?.length) return "";
  if (tiers && !tiers.length) return "no tier matches";
  return affix.lines.map((line) => {
    const n = line.tiers.length;
    const [lo, hi] = tiers ? [tiers[0], Math.min(n, tiers[1])] : (n === 1 ? [1, 1] : [0, 0]);
    if (!n || !lo || lo > hi) return lineText(line, valueRange(line, "x"));
    if (lo === hi) return lineText(line, tierRangeText(line, lo - 1, scale));
    const v = (t, i) => fmtNumber(scaled(line.tiers[t - 1][i], scale), line);
    return lineText(line, valueRange(line, `(${v(lo, 0)}/${v(hi, 0)})`, `(${v(lo, 1)}/${v(hi, 1)})`));
  }).join(" / ");
}

let tipEl = null;
function hideTip() { if (tipEl) tipEl.style.display = "none"; }
/** Shows content at e's position: beside the mouse, or (touch) above the finger, where the hand doesn't cover it. */
function showTip(e, content, touch = false) {
  if (!tipEl) { tipEl = h("div", { class: "tip" }); document.body.append(tipEl); }
  fill(tipEl, content);
  tipEl.style.display = "block";
  const pad = 14, r = tipEl.getBoundingClientRect();
  let x = e.clientX + pad, y = e.clientY + pad;
  if (touch) {
    x = Math.min(e.clientX - r.width / 2, innerWidth - r.width - 8);
    y = e.clientY - r.height - 3 * pad;
    if (y < 8) y = e.clientY + 3 * pad;   // no room above: below the finger
  } else if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  // Positions are in screen pixels; the page may be zoomed (large screens, see app.css).
  const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  tipEl.style.left = `${Math.max(8, x) / z}px`; tipEl.style.top = `${Math.max(8, y) / z}px`;
}

/** An idol altar's idol grid (rows of 0 = no slot, 1 = idol slot, 2 = refracted slot). */
function altarGrid(grid, cell = 14) {
  return h("span", { class: "altar-grid", style: { gridTemplateColumns: `repeat(${grid[0].length}, ${cell}px)` } },
    grid.flat().map((v) => h("i", { class: ["none", "slot", "refracted"][v], style: { width: `${cell}px`, height: `${cell}px` } })));
}

/** A base's stats, as the item tooltip lists them: level and class requirement, implicits with the
 *  range an item rolls them in, a weapon's base attack rate (and its added range, which the game
 *  doesn't show), an idol altar's idol slots. */
function baseTip(type, s) {
  const classes = S.meta.enums.classes.filter((c, i) => s.class & (1 << i));
  const num = (v) => String(+v.toFixed(2));
  return h("div", { class: "base-tip" },
    h("div", { class: "tip-title" }, s.name),
    h("div", { class: "hint" }, [typeName(type), `Requires Level ${s.level}`, classes.length ? `${classes.join(" / ")} only` : null]
      .filter(Boolean).join(" · ")),
    s.implicits?.length
      ? [h("div", { class: "tip-head" }, "Implicits"), s.implicits.map((line) => h("div", { class: "tip-line" }, lineText(line, tierRangeText(line, 0, 1))))]
      : h("div", { class: "hint" }, s.implicits ? "No implicits" : "Implicits not extracted"),
    s.attack_rate != null ? h("div", { class: "tip-line" }, `Base attack rate ${num(s.attack_rate)}`,
      s.range ? h("span", { class: "hint" }, ` · range ${s.range > 0 ? "+" : ""}${num(s.range)}`) : null) : null,
    s.grid ? [h("div", { class: "tip-head" }, "Idol slots"),
      h("div", { class: "row" }, altarGrid(s.grid), h("span", { class: "hint" },
        `${s.grid.flat().filter(Boolean).length} slots, ${s.grid.flat().filter((v) => v === 2).length} refracted`))] : null,
    s.drops ? null : h("div", { class: "bad" }, "Cannot drop"));
}
const TIPS = new WeakMap();   // element -> () => its tooltip's content (withTip)

/** The innermost element from node up that has a tooltip: a withTip one or, with titles, one with a title. */
function tipOwner(node, titles = false) {
  for (let el = node; el; el = el.parentElement) {
    if (TIPS.has(el) || (titles && el.getAttribute?.("title"))) return el;
  }
  return null;
}

/** Shows content() as a tooltip while the mouse is over el (hidden on click: el is usually re-rendered).
 *  Touch screens have no hover: there, pressing and holding el shows it (wireTouchTips). */
function withTip(el, content) {
  TIPS.set(el, content);
  el.addEventListener("pointermove", (e) => { if (e.pointerType !== "touch" && tipOwner(e.target) === el) showTip(e, content()); });
  el.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") hideTip(); });
  el.addEventListener("click", hideTip);
  return el;
}

/** Touch screens: pressing and holding an element shows its tooltip - its withTip one, else its title
 *  (what a button does) - until the next touch. Lifting that finger doesn't click; scrolling cancels. */
function wireTouchTips() {
  const HOLD_MS = 450, SLOP = 10;
  let timer = null, at = null, held = false, swallowUntil = 0;
  const cancel = () => { clearTimeout(timer); timer = null; };
  const swallowing = () => held || performance.now() < swallowUntil;
  const release = () => { cancel(); if (held) { held = false; swallowUntil = performance.now() + 700; } };
  document.addEventListener("pointerdown", (e) => {
    swallowUntil = 0;   // a new press (touch or mouse) does what it does
    if (e.pointerType !== "touch") return;
    hideTip(); cancel(); held = false;   // and a touch closes the shown tip
    // Text fields keep their own long press (select, paste).
    const owner = e.isPrimary && !e.target.closest("input:not([type=checkbox], [type=radio]), textarea") && tipOwner(e.target, true);
    if (!owner) return;
    if (!store.get("touch-tip-hint", false)) {
      store.set("touch-tip-hint", true);
      toast("On a touch screen, press and hold for an item's or affix's details and what a button does (what hovering shows with a mouse).");
    }
    at = { clientX: e.clientX, clientY: e.clientY };
    timer = setTimeout(() => {
      timer = null; held = true;
      getSelection()?.removeAllRanges();
      // An element with both (e.g. a base chip marked "not a Sentinel base") shows its title under the tooltip,
      // as a mouse would get both.
      const tip = TIPS.get(owner), title = owner.getAttribute("title");
      showTip(at, tip ? [tip(), title ? h("div", { class: "tip-text tip-note" }, title) : null] : h("div", { class: "tip-text" }, title), true);
    }, HOLD_MS);
  }, true);
  document.addEventListener("pointermove", (e) => {
    if (timer && e.pointerType === "touch" && Math.hypot(e.clientX - at.clientX, e.clientY - at.clientY) > SLOP) cancel();
  }, true);
  for (const type of ["pointerup", "pointercancel"]) {
    document.addEventListener(type, (e) => { if (e.pointerType === "touch") release(); }, true);
  }
  // The hold's own click, and the browser's long-press menu and text selection.
  document.addEventListener("click", (e) => { if (swallowing()) { e.preventDefault(); e.stopPropagation(); } }, true);
  for (const type of ["contextmenu", "selectstart"]) {
    document.addEventListener(type, (e) => { if (timer || swallowing()) { e.preventDefault(); e.stopPropagation(); } }, true);
  }
  document.addEventListener("scroll", () => { if (!timer && !held) hideTip(); }, true);
}

/** Shows an affix's tier table as el's tooltip - its values per tier, on the item type when typeIds names exactly one. */
function withAffixTip(el, a, typeIds = null) {
  if (!a?.lines?.length) return el;
  return withTip(el, () => affixTierTable(a, null, affixScale(a, typeIds), typeIds));
}

/** Shows baseTip as el's tooltip. */
function withBaseTip(el, type, s) {
  return withTip(el, () => baseTip(type, s));
}

/** Per-tier table: one row per tier, one column per stat line; the selected tiers highlighted. */
function affixTierTable(affix, tiers, scale, typeIds, omen = false) {
  const n = Math.max(0, ...affix.lines.map((l) => l.tiers.length));
  const id = typeIds && typeIds.size === 1 ? [...typeIds][0] : null;
  const base = id != null ? M.baseById.get(id) : null;
  const rolls = base && (omen || !affix.rolls_on || affix.rolls_on.includes(id));
  const factor = scale !== 1 ? ` (x${+scale.toFixed(3)} its usual item type)` : "";
  const note = !base ? "values on the affix's usual item type; other item types scale them"
    : rolls ? `values on ${omen ? "omen " : ""}${base.name}${factor}`
      : `doesn't roll on ${base.name}; values on its usual item type`;
  return h("div", {},
    h("div", { class: "tip-title" }, affix.name),
    h("table", { class: "tier-table" },
      h("tr", {}, h("th", {}, "Tier"), affix.lines.map((l) => h("th", {}, lineText(l, valueRange(l, "x"))))),
      Array.from({ length: n }, (_, t) => h("tr", { class: tiers?.length && t + 1 >= tiers[0] && t + 1 <= tiers[1] ? "on" : "" },
        h("td", {}, `T${t + 1}`), affix.lines.map((l) => h("td", {}, l.hide ? "✓" : l.tiers[t] ? tierRangeText(l, t, scale) : "-"))))),
    h("div", { class: "hint" }, note));
}

/** The value column: summary text, per-tier table as its tooltip. */
function affixValueCell(affix, { tiers = null, typeIds = null, omen = false } = {}) {
  if (!affix?.lines?.length) return h("span", { class: "aval" });
  const scale = affixScale(affix, typeIds, omen);
  return withTip(h("span", { class: "aval" }, affixValueSummary(affix, tiers, scale)), () => affixTierTable(affix, tiers, scale, typeIds, omen));
}

/** Searchable add-list. items: [{id, label, meta, group, alt?, cell?}], selected: Set of ids, onAdd(ids). */

function searchPicker(items, isSelected, onAdd, placeholder, { query = "", onQuery = null } = {}) {
  const results = h("div", { class: "picker" });
  const input = h("input", { type: "search", placeholder, style: { flex: 1 }, value: query });
  let shown = [];
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    shown = items.filter((it) => !isSelected(it.id) && (!q || [it.label, it.alt, it.group].some((s) => (s || "").toLowerCase().includes(q))));
    results.replaceChildren();
    let group = null;
    for (const it of shown.slice(0, 400)) {
      if (it.group !== group) { group = it.group; if (group) put(results, h("div", { class: "grp" }, group)); }
      const opt = h("div", { class: "opt" + (it.cell ? " with-value" : ""), onclick: () => { hideTip(); onAdd([it.id]); } },
        h("span", {}, it.label, it.pill ? it.pill() : null), h("span", { class: "meta" }, it.meta || ""), it.cell ? it.cell() : null);
      put(results, it.tip ? withTip(opt, it.tip) : opt);
    }
    if (shown.length > 400) put(results, h("div", { class: "opt hint" }, `…${shown.length - 400} more, refine the search`));
    if (!shown.length) put(results, h("div", { class: "opt hint" }, "nothing to add"));
  };
  input.addEventListener("input", () => { onQuery?.(input.value); draw(); });
  draw();
  return h("div", {}, h("div", { class: "row" }, input,
    h("button", { title: "Add every entry listed below", onclick: () => onAdd(shown.map((s) => s.id)) }, "Add all listed")), results);
}

/** Copy / paste buttons for an affix list. The copied list is kept (in this browser) until something
 *  else is copied, so it also serves as a set of affixes to start new affix rules or BiS slots with.
 *  paste(ids) adds the ones that fit; refresh() redraws after copying. */
function affixClipboardRow(current, from, paste, refresh) {
  const clip = store.get("affix-clipboard", null);
  const n = clip?.ids?.length || 0;
  return h("div", { class: "row clip-row" },
    h("button", { disabled: !current.length, title: "Copy this list of affixes - paste it into another affix rule or BiS slot",
      onclick: () => { store.set("affix-clipboard", { ids: [...current], from }); toast(`${current.length} affixes copied.`); refresh(); } }, "Copy affixes"),
    h("button", { disabled: !n, title: n ? `Add the copied affixes that can roll here (copied from ${clip.from})` : "Nothing copied yet",
      onclick: () => { const now = store.get("affix-clipboard", null); if (now?.ids?.length) paste(now.ids); } }, n ? `Paste ${n} affixes` : "Paste affixes"),
    n ? h("span", { class: "hint" }, `copied from ${clip.from}`) : null);
}

function affixEditor(rule, c) {
  const re = { editor: true };
  const typeIds = ruleTypeIds(rule), omenPool = ruleOmenPool(rule), omenExtra = omenPool ? null : ruleOmenExtra(rule);
  const omenOf = (a) => !!omenPool?.has(a.id);
  const showAll = SHOW_ALL_AFFIXES.has(c);
  const tiersOf = (a) => conditionTiers(c, Math.max(1, ...(a.lines || []).map((l) => l.tiers.length)));
  const listed = S.meta.affixes
    .filter((a) => showAll || (omenPool ? omenPool.has(a.id) : !typeIds.size || a.rolls_on.some((t) => typeIds.has(t)) || omenExtra?.has(a.id)))
    .sort(compareAffixes);
  const sel = new Set(c.affixes);
  const f = AFFIX_PICKER.get(c) || { ...newAffixFilter(), q: "" };
  AFFIX_PICKER.set(c, f);
  const pickerBox = h("div", {});
  const drawPicker = () => {
    const items = listed.filter(affixShownBy(f)).map((a) => ({ id: a.id, label: a.name, alt: `${a.en_name || ""} ${a.internal_name || ""}`,
      group: f.sort === "name" ? "" : affixGroup(a), meta: a.idol ? "idol" : "", pill: () => affixPill(a),
      cell: () => affixValueCell(a, { tiers: tiersOf(a), typeIds, omen: omenOf(a) }) }));
    if (f.sort === "name") items.sort((x, y) => x.label.localeCompare(y.label));
    fill(pickerBox, searchPicker(items, (id) => sel.has(id), (ids) => mutate(() => { c.affixes = [...c.affixes, ...ids.filter((i) => !sel.has(i))]; }, re),
      f.cats.size ? "Search the ticked categories…" : "Search affixes to add…", { query: f.q, onQuery: (q) => { f.q = q; } }));
  };
  const filterBar = affixFilterBar(f, listed.filter((a) => !sel.has(a.id)), drawPicker, listed);
  drawPicker();
  return h("div", {},
    h("div", { class: "selected-list" }, c.affixes.length ? groupedChips(c.affixes, (id) => {
      const a = M.affix.get(id);
      const chip = h("span", { class: "chip on" }, affixName(id), affixPill(id),
        h("button", { title: "remove", onclick: () => { hideTip(); mutate(() => { c.affixes = c.affixes.filter((x) => x !== id); }, re); } }, "×"));
      return a?.lines?.length ? withTip(chip, () => affixTierTable(a, tiersOf(a), affixScale(a, typeIds, omenOf(a)), typeIds, omenOf(a))) : chip;
    })
      : h("span", { class: "hint" }, "No affixes listed: any affix counts.")),
    c.affixes.length ? h("div", { class: "row" }, h("button", { onclick: () => mutate(() => { c.affixes = []; }, re) }, "Remove all")) : null,
    affixClipboardRow(c.affixes, rule.name ? `"${rule.name}"` : `rule ${S.doc.rules.indexOf(rule) + 1}`, (ids) => {
      const fits = ids.filter((id) => {
        const a = M.affix.get(id);
        return a && (showAll || (omenPool ? omenPool.has(id) : !typeIds.size || a.rolls_on.some((t) => typeIds.has(t)) || omenExtra?.has(id)));
      });
      const add = fits.filter((id) => !c.affixes.includes(id));
      if (add.length) mutate(() => { c.affixes = [...c.affixes, ...add]; }, re);
      toast(`${add.length} affixes pasted` + (ids.length > fits.length ? `; ${ids.length - fits.length} can't roll on this rule's item types` : "")
        + (fits.length > add.length ? `; ${fits.length - add.length} were there already` : "") + ".");
    }, renderEditor),
    h("div", { class: "row" },
      h("label", {}, "At least", numInput(c.min_on_same_item, (v) => mutate(() => { c.min_on_same_item = Math.max(0, v); }, re), { min: 0, max: 6, width: "52px" }), "of them on the item"),
      h("label", { title: "Tier comparisons, as the in-game advanced mode" }, h("input", { type: "checkbox", checked: c.advanced, onchange: (e) => mutate(() => { c.advanced = e.target.checked; }, re) }), "Advanced")),
    c.advanced ? h("div", { class: "row" },
      "Each affix tier", h("select", { onchange: (e) => mutate(() => { c.comparsion = e.target.value; }, re) },
        S.meta.enums.comparsion.map((v) => h("option", { value: v, selected: v === c.comparsion }, v === "ANY" ? "any" : opText(v)))),
      numInput(c.comparsion_value, (v) => mutate(() => { c.comparsion_value = v; }, re), { min: 0, max: 8, width: "52px" }),
      "Combined tiers", h("select", { onchange: (e) => mutate(() => { c.combined_comparsion = e.target.value; }, re) },
        S.meta.enums.comparsion.map((v) => h("option", { value: v, selected: v === c.combined_comparsion }, v === "ANY" ? "any" : opText(v)))),
      numInput(c.combined_value, (v) => mutate(() => { c.combined_value = v; }, re), { min: 0, max: 60, width: "52px" })) : null,
    h("div", { class: "row" }, h("label", { class: "hint" },
      h("input", { type: "checkbox", checked: showAll, onchange: (e) => { if (e.target.checked) SHOW_ALL_AFFIXES.add(c); else SHOW_ALL_AFFIXES.delete(c); renderEditor(); } }),
      typeIds.size ? "list affixes for every item type (not only this rule's)" : "this rule has no item type: every affix is listed")),
    h("div", { class: "group-label" }, "Add affixes - quick filter by category"), filterBar, pickerBox);
}

/* A unique's roll (0-255, what a filter's roll range stores) as its value, and back - as the game
 * does: EpochExtensions.AscendingValueAfterPropertyRounding (the range in steps of the stat's
 * rounding, floor(lo + (hi - lo + 1) * roll / 255), capped at hi; a mod whose max isn't above its
 * value doesn't change with the roll) and Get{Lowest,Highest}RollThatResultsInValue (a typed value
 * rounds to the nearest level: the first roll of the highest level <= value + step / 2, the last
 * roll whose value is <= value + step / 2). Lines are a unique's rolls (vmin / vmax / step). */
function rollValue(line, roll) {
  const f = Math.round(1 / line.step);
  const lo = roundEven(Math.fround(Math.fround(line.vmin) * f)), hi = roundEven(Math.fround(Math.fround(line.vmax) * f));
  if (hi <= lo) return lo / f;
  const v = Math.floor(Math.fround(Math.fround((hi - lo + 1) * Math.fround(roll / 255)) + lo));
  return Math.min(v, hi) / f;
}
const nearly = (a, b) => Math.abs(a - b) <= Math.max(1e-6 * Math.max(Math.abs(a), Math.abs(b)), 1e-9);
// In single precision, as the game computes (subss / comiss): exact midpoints round the way its floats do.
function lowestRoll(line, v) {
  const f = Math.fround, half = f(f(line.step) * 0.5);
  let best = 0, prev = null;
  for (let r = 0; r <= 255; r++) {
    const val = f(rollValue(line, r));
    if (val === prev) continue;
    if (f(val - half) > v) break;
    best = r; prev = val;
  }
  return best;
}
function highestRoll(line, v) {
  const f = Math.fround, half = f(f(line.step) * 0.5);
  for (let r = 255; r >= 0; r--) {
    const val = f(rollValue(line, r));
    if (f(val - half) <= v && f(half + v) >= val) return r;
  }
  return 0;
}
/** Whether a stored roll range limits anything (the game writes empty or 0-255 entries for every roll). */
const restricts = (r) => (r.min != null && r.min > 0) || (r.max != null && r.max < 255);

/** A unique's description line: the game's "[min,max,roll]" value marks as "min-max". */
const uniqueDescText = (text) => text
  .replace(/\s*[(（]\s*\[[^\]]*,\s*c\b[^\]]*\][^)）]*[)）]/g, "")   // "([1,c,5])": the value at the character's level, unknown here
  .replace(/\[[^\[\]]*,\s*c\b[^\[\]]*\]/g, "")
  // As UniqueModParser: ([+-])?\[([^\[]+)\](%)? whose inside has "min, max, roll" anywhere becomes the
  // whole match's replacement - words inside go ("[на 10, 15, 0]%"), so does a stray "]" ("[22,36,3]%]")
  .replace(/([+-]?)\[([^\[]+)\](%?)/g, (m, sign, inner, pct) => {
    const r = inner.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    return r ? `${sign}${r[1] === r[2] ? r[1] : `${r[1]}-${r[2]}`}${pct}` : m;
  })

/** A unique's stats, as its tooltip lists them: base, level, LP level, the base's implicits, its modifiers and lore. */
function uniqueTip(u) {
  const base = M.baseById.get(u.base_type);
  const sub = base?.subtypes.find((s) => s.id === u.sub_type);
  return h("div", { class: "base-tip unique-tip" },
    h("div", { class: "tip-title" + (u.is_set ? " set" : "") }, u.name),
    h("div", { class: "hint" }, [base?.name, sub?.name, `Requires Level ${u.level}`,
      u.weavers_will ? "Weaver's Will" : `LP level ${u.lpl}`, u.is_set ? "set item" : null].filter(Boolean).join(" · ")),
    sub?.implicits?.length ? [h("div", { class: "tip-head" }, "Implicits"),
      sub.implicits.map((line) => h("div", { class: "tip-line" }, lineText(line, tierRangeText(line, 0, 1))))] : null,
    u.tooltip?.length ? [h("div", { class: "tip-head" }, "Modifiers"),
      u.tooltip.map((l) => ("desc" in l
        ? h("div", { class: "tip-line" + (l.set ? " set" : "") }, (l.set ? `(${l.set} set pieces) ` : "") + uniqueDescText(l.text))
        : h("div", { class: "tip-line" }, lineText(l, tierRangeText(l, 0, 1)))))] : h("div", { class: "hint" }, "Modifiers not extracted"),
    u.lore ? h("div", { class: "lore" }, u.lore) : null);
}
function withUniqueTip(el, u) {
  return u ? withTip(el, () => uniqueTip(u)) : el;
}

/** Per-condition picker state: item types to list (none = all), the "show only" filter and the search text. */
const UNIQUE_PICKER = new WeakMap();
/** The uniques picker's "show only" filters: [key, label, test]. A build slot's picker starts with its
 *  section's one switched on (meta.build_slot_filters: the Weaver's Will and primordial slots). */
const UNIQUE_KINDS = [["weaver", "Weaver's Will", (u) => u.weavers_will], ["primordial", "Primordial", (u) => u.is_primordial]];

/** A picked unique with its required roll ranges: one per roll, as in-game - the rolls the game's
 *  picker offers, hidden effect rolls included; each mod on a roll converts in its own units. */
function pickedUnique(c, u, re) {
  const meta = M.unique.get(u.id);
  const groups = new Map();
  for (const l of meta?.rolls || []) (groups.get(l.roll_id) || groups.set(l.roll_id, []).get(l.roll_id)).push(l);
  const entry = (rid) => u.rolls.find((r) => r.roll === rid);
  const descText = (i) => uniqueDescText(meta.tooltip?.find((t) => t.desc === i)?.text || "");
  // As UniqueModifierDataUI: a typed bound is clamped to the mod's range; a min above the max raises
  // the max, a max below the min is raised back to the min; then each bound becomes a roll.
  const setBound = (rid, line, which, text) => mutate(() => {
    let r = entry(rid);
    if (!r) { r = { roll: rid, min: null, max: null }; u.rolls.push(r); }
    const f = Math.fround, lo = f(rollValue(line, 0)), hi = f(rollValue(line, 255));
    let minV = r.min == null ? lo : f(rollValue(line, r.min)), maxV = r.max == null ? hi : f(rollValue(line, r.max));
    const typed = parseFloat(String(text).replace(",", "."));
    const v = Number.isNaN(typed) ? null : Math.min(hi, Math.max(lo, f(f(typed) / f(line.mult))));
    if (which === "min") {
      minV = v ?? lo;
      if (minV > maxV) maxV = minV;
    } else {
      maxV = v ?? hi;
      if (minV > maxV) maxV = minV;
    }
    r.min = nearly(minV, lo) ? null : lowestRoll(line, minV);
    r.max = nearly(maxV, hi) ? null : highestRoll(line, maxV);
    if (r.min == null && r.max == null) u.rolls.splice(u.rolls.indexOf(r), 1);
  }, re);
  const set = (S.uniqOpen ||= new Set());
  const limited = u.rolls.filter(restricts).length;
  const summary = h("summary", {}, withUniqueTip(h("span", { class: "uniq-name" }, uniqueName(u.id)), meta),
    h("span", { class: "hint" }, groups.size ? ` · ${limited ? `${limited} of ${groups.size} rolls limited` : `${groups.size} rolls, any`}` : " · no rolls"),
    h("button", { class: "uniq-x", title: "remove", onclick: (e) => { e.preventDefault(); hideTip(); mutate(() => { c.uniques = c.uniques.filter((x) => x !== u); }, re); } }, "×"));
  return h("details", { class: "uniq-picked", open: set.has(u.id) || null, ontoggle: (e) => set[e.target.open ? "add" : "delete"](u.id) },
    summary,
    groups.size ? h("div", { class: "uniq-rolls" }, [...groups].map(([rid, lines]) => {
      const r = entry(rid);
      const seen = new Set();   // several hidden mods behind one described effect: one row (they move together)
      const shownLines = lines.filter((l) => { const k = l.desc != null ? `d${l.desc}` : `${l.text}|${l.vmin}|${l.vmax}`; return !seen.has(k) && seen.add(k); });
      return h("div", { class: "uniq-roll-group" }, shownLines.map((line) => {
        const label = line.desc != null ? descText(line.desc) : lineText(line, tierRangeText(line, 0, 1));
        const shown = (b) => (b == null ? "" : fmtNumber(rollValue(line, b), line));
        const input = (which) => h("input", { type: "text", inputmode: "decimal", size: 6, value: shown(r?.[which]),
          placeholder: fmtNumber(which === "min" ? line.vmin : line.vmax, line),
          onchange: (e) => setBound(rid, line, which, e.target.value.trim()) });
        return h("div", { class: "uniq-roll" },
          h("span", { class: "uniq-mod" }, label, line.hidden ? h("span", { class: "hint" }, " (hidden stat)") : null),
          line.varies ? [h("label", {}, "at least", input("min")), h("label", {}, "at most", input("max"))]
            : h("span", { class: "hint" }, "fixed value"),
          h("span", { class: "hint" }, r && restricts(r) ? `rolls ${r.min ?? 0}-${r.max ?? 255}` : "any roll"));
      }), shownLines.length > 1 ? h("div", { class: "hint" }, "These share one roll: limiting one limits them all.") : null);
    }), h("p", { class: "hint" }, "Values as the tooltip shows them (empty = no limit); the filter stores them as rolls 0-255, converted as the game does."))
      : h("p", { class: "hint" }, "Nothing on it rolls."));
}

function uniquesEditor(c, rule) {
  const re = { editor: true };
  const state = UNIQUE_PICKER.get(c) || { types: new Set(), q: "", kind: S.meta.build_slot_filters?.[rule?.name] || null };
  UNIQUE_PICKER.set(c, state);
  const sel = new Set(c.uniques.map((u) => u.id));
  const listed = S.meta.uniques.filter((u) => !u.hidden);   // as in-game: no uniques hidden from players
  const ofKind = (u) => !state.kind || UNIQUE_KINDS.find(([k]) => k === state.kind)?.[2](u);
  const items = listed
    .map((u) => ({ id: u.id, u, label: u.name, alt: u.en_name, group: u.base_type_name || "", type: u.base_type,
      meta: `${u.is_set ? "set · " : ""}${u.weavers_will ? "WW · " : ""}${u.is_primordial ? "primordial · " : ""}`
        + `${u.is_cocooned ? "cocooned · " : ""}LPL ${u.lpl}`, tip: () => uniqueTip(u) }))
    .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
  const chipsBox = h("div", { class: "uniq-types" }), pickerBox = h("div", {});
  const drawPicker = () => fill(pickerBox, searchPicker(items.filter((it) => ofKind(it.u) && (!state.types.size || state.types.has(it.type))),
    (id) => sel.has(id), (ids) => mutate(() => {
      c.uniques = [...c.uniques, ...ids.filter((i) => !sel.has(i)).map((id) => ({ id, rolls: [] }))];
    }, re), "Search uniques / sets to add…", { query: state.q, onQuery: (q) => { state.q = q; } }));
  const drawChips = () => {
    chipsBox.replaceChildren();
    const counts = new Map();   // per item type, of the uniques the "show only" filter leaves
    for (const u of listed) if (ofKind(u)) counts.set(u.base_type, (counts.get(u.base_type) || 0) + 1);
    put(chipsBox,
      h("div", { class: "chips compact" }, h("span", { class: "hint cat" }, "Show only"),
        UNIQUE_KINDS.map(([k, label, test]) => chipToggle(`${label} uniques`, state.kind === k, () => {
          state.kind = state.kind === k ? null : k;
          drawChips(); drawPicker();
        }, `${listed.filter(test).length}`))),
      basesByCategory().map(([cat, bases]) => {
        const here = bases.filter((b) => counts.get(b.id) || state.types.has(b.id));
        return here.length ? h("div", { class: "chips compact" }, h("span", { class: "hint cat" }, cat),
          here.map((b) => chipToggle(b.name, state.types.has(b.id), () => {
            if (state.types.has(b.id)) state.types.delete(b.id); else state.types.add(b.id);
            drawChips(); drawPicker();
          }, `${counts.get(b.id) || 0}`))) : null;
      }),
      state.types.size ? h("button", { onclick: () => { state.types.clear(); drawChips(); drawPicker(); } }, "All types") : null);
  };
  drawChips();
  drawPicker();
  const rolled = c.uniques.filter((u) => u.rolls.some(restricts)).length;
  return h("div", {},
    c.uniques.length ? h("div", { class: "uniq-list" }, c.uniques.map((u) => pickedUnique(c, u, re)))
      : h("span", { class: "hint" }, "Empty: add uniques here or in-game."),
    rolled ? h("p", { class: "hint" }, `${rolled} of them need certain rolls: open one to see or change its roll ranges.`) : null,
    c.uniques.length ? h("div", { class: "row" }, h("button", { onclick: () => mutate(() => { c.uniques = []; }, re) }, "Remove all")) : null,
    h("div", { class: "group-label" }, "Add uniques - quick filters"), chipsBox, pickerBox);
}

/* ---------- rule list actions ---------- */

function addRule() {
  if (!S.doc) return;
  mutate(() => {
    const at = S.sel >= 0 ? S.sel + 1 : S.doc.rules.length;
    S.doc.rules.splice(at, 0, newRule("New rule"));
    S.sel = at;
  }, { editor: true });
  scrollToSel();
}
function dupRule() {
  if (!S.doc || S.sel < 0) return;
  mutate(() => {
    const copy = structuredClone(S.doc.rules[S.sel]);
    if (!isRaw(copy)) copy.name = copy.name ? `${copy.name} (copy)` : "";
    S.doc.rules.splice(S.sel + 1, 0, copy);
    S.sel += 1;
  }, { editor: true });
  scrollToSel();
}
function delRule() {
  if (!S.doc || S.sel < 0) return;
  mutate(() => {
    S.doc.rules.splice(S.sel, 1);
    clampSel();
  }, { editor: true });
}
function stepRule(d) {
  if (!S.doc || S.sel < 0) return;
  const to = S.sel + d;
  if (to < 0 || to >= S.doc.rules.length) return;
  mutate(() => {
    const [r] = S.doc.rules.splice(S.sel, 1);
    S.doc.rules.splice(to, 0, r);
    S.sel = to;
  }, { editor: true });
  scrollToSel();
}

/* ---------- character level (shared by all tabs) ---------- */

function setLevel(v, fromTab) {
  S.lvl.level = Math.max(1, Math.min(100, Number(v) || 1));
  $("#lvl-range").value = S.lvl.level;
  $("#lvl-num").value = S.lvl.level;
  if (S.lvl.on) renderList();
  if (fromTab === "leveling") updateLevCursor(); else renderLevPreview();
  if (fromTab === "test") { const n = $("#test-lvl"); if (n) n.value = S.lvl.level; } else renderTestForm();
  testSoon();
}

/* ---------- leveling generator ---------- */

const STYLE_KINDS = [
  ["weapon_affix", "Weapon / off-hand base with a build affix"],
  ["weapon_base", "Weapon / off-hand base, any affixes"],
  ["gear", "Armour with enough build affixes"],
  ["gear_single", "Armour with one build affix (early levels)"],
  ["jewelry", "Jewelry / belt with a build affix"],
  ["good_base", "Good base, any slot (until the cap)"],
];
const STYLE_DEFAULTS = { weapon_affix: { color: 14, emphasized: true }, weapon_base: {}, gear: { color: 13, emphasized: true }, gear_single: {},
  jewelry: { color: 13 }, good_base: { color: 15, emphasized: true } };
const GEAR_ARMOUR = ["HELMET", "BODY_ARMOR", "BOOTS", "GLOVES"];
const GEAR_JEWELRY = ["BELT", "AMULET", "RING", "RELIC"];
const TOGGLE_GROUPS = [["damage", "Damage type"], ["focus", "Build focus"], ["attributes", "Attributes"], ["defence", "Defence & utility"]];
/** Kinds of gear with their own affix toggles (their option key and item types come with the game data). */
const LEV_SECTIONS = [["weapons", "Weapons"], ["offhands", "Off-hands"], ["armour", "Armour"], ["jewelry", "Jewelry & belts"]];
const sectionKey = (s) => S.meta.sections[s].key;
const sectionTypeIds = (s) => new Set(S.meta.sections[s].types.map((t) => M.base.get(t)?.id));

/** Where affixes roll (base type ids), in slot order; a complete weapon or armour set is named as one. */
function whereText(typeIds) {
  const types = new Set([...typeIds].map((id) => M.baseById.get(id)?.type));
  const groups = [[S.meta.enums.weapons, "every weapon"], [S.meta.enums.offhands], [GEAR_ARMOUR, "all armour"], [GEAR_JEWELRY]];
  return groups.flatMap(([list, all]) => {
    const hit = list.filter((t) => types.has(t));
    return all && hit.length === list.length ? [all] : hit.map(typeName);
  }).join(", ") || "no gear";
}

/** Base type ids of section `s` that a toggle's affixes roll on, for class `cls` (none: the toggle isn't offered there). */
function toggleRolls(key, s, cls) {
  const ids = sectionTypeIds(s);
  return (S.meta.toggle_rolls_on[cls || ""]?.[key] || []).filter((id) => ids.has(id));
}

/** Item types each kind of gear generates rules for. */
function levSlots(o) {
  const isOff = (t) => S.meta.enums.offhands.includes(t);
  return { weapons: o.weapons.filter((t) => !isOff(t)), offhands: [...new Set([...o.weapons.filter(isOff), ...o.offhands])],
    armour: o.armour ? GEAR_ARMOUR : [], jewelry: o.jewelry ? GEAR_JEWELRY : [] };
}

/** The options sent to the server for class `cls`: class affix picks stay stored for every class, only cls's go. */
function levBody(cls = levOpts().character_class) {
  const o = levOpts();
  const fits = new Set(S.meta.class_affixes[cls] || []);
  return { ...o, character_class: cls, class_affixes: (o.class_affixes || []).filter((id) => fits.has(id)) };
}

function levOpts() {
  if (!S.lev.opts) {
    const stored = store.get("lev-opts", {}) || {};
    S.lev.opts = withDefaults(S.meta.leveling_defaults, stored);
    if ("damage" in stored && !("weapon_affixes" in stored)) {
      // saved before each kind of gear had its own toggles: they all start from the shared ones, weapons without defences
      const shared = Object.fromEntries(TOGGLE_GROUPS.map(([g]) => [g, [...(stored[g] || [])]]));
      if (shared.defence.includes("attributes")) {   // v0.1.0's all-attributes toggle
        shared.defence = shared.defence.filter((k) => k !== "attributes");
        shared.attributes = S.meta.toggles.filter((t) => t.group === "attributes").map((t) => t.key);
      }
      if (shared.defence.includes("armour") && !shared.defence.includes("endurance")) {   // v0.2.0's armour took endurance too
        shared.defence.splice(shared.defence.indexOf("armour") + 1, 0, "endurance");
      }
      shared.exclude = [];
      for (const [s] of LEV_SECTIONS) {
        S.lev.opts[sectionKey(s)] = structuredClone(s === "weapons" ? { ...shared, defence: [], defensive: false } : shared);
      }
      // as the server reads such settings: single attributes (which don't roll on weapons) meant All Attributes there
      const w = S.lev.opts.weapon_affixes;
      if (w.attributes.length) w.attributes = ["all_attributes"];
    }
    for (const [s] of LEV_SECTIONS) {   // every section with its lists (older or broken saves may lack them)
      const sec = (S.lev.opts[sectionKey(s)] ||= {});
      for (const [g] of TOGGLE_GROUPS) if (!Array.isArray(sec[g])) sec[g] = [];
      if (!Array.isArray(sec.exclude)) sec.exclude = [];
      if (s === "weapons") sec.defensive = !!sec.defensive;
    }
  }
  return S.lev.opts;
}

function levChanged() {
  store.set("lev-opts", S.lev.opts);
  renderLevForm();
  levelingSoon();
}

const levelingSoon = debounce(runLeveling, 250);

async function runLeveling() {
  if (!S.meta) return;
  try {
    const body = { options: levBody() };
    if (S.doc) body.rules = S.doc.rules;
    S.lev.result = await api("/api/leveling", body);
    S.lev.error = null;
    document.querySelectorAll("[data-count]").forEach((el) => {
      const [s, key] = el.dataset.count.split(":");
      const n = S.lev.result.picked[s]?.[key];
      el.textContent = n ? n.length : "";
    });
  } catch (e) {
    S.lev.result = null;
    S.lev.error = e.message;
  }
  renderLevPreview();
}

function renderLevForm() {
  const o = levOpts();
  const f = $("#lev-form");
  f.replaceChildren();
  const toggleList = (arr, v) => { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); levChanged(); };
  const slots = levSlots(o);
  const typeChips = (types, list) => h("div", { class: "chips" }, types.map((t) => chipToggle(typeName(t), list.includes(t), () => toggleList(list, t))));

  put(f, h("h3", {}, "Build"),
    h("div", { class: "row" }, h("label", {}, "Class",
      h("select", { onchange: (e) => { o.character_class = e.target.value; levChanged(); } },
        h("option", { value: "" }, "any (no class-specific affixes)"),
        S.meta.enums.classes.map((c) => h("option", { value: c, selected: c === o.character_class }, c))))),
    h("p", { class: "hint" }, "A class adds its class-specific affixes and bases, and drops affixes it can't roll."),
    h("div", { class: "row" },
      h("label", {}, "Weapon / off-hand windows of", numInput(o.step, (v) => { o.step = v; levChanged(); }, { min: 1, max: 100, width: "56px" }), "levels;"),
      h("label", {}, "every rule off from level", numInput(o.cap, (v) => { o.cap = v; levChanged(); }, { min: 1, max: 100, width: "56px" }))),
    h("div", { class: "group-label" }, "Rarity"),
    h("div", { class: "chips" }, S.meta.enums.rarities.map((r) => chipToggle(cap(r), o.rarity.includes(r), () => toggleList(o.rarity, r)))),
    h("p", { class: "hint" }, "Each kind of gear below picks its own affixes. A toggle adds every ordinary gear affix it names "
      + "(e.g. Physical: \"… Physical Damage\", \"Physical Penetration\") that can roll on that gear; toggles with nothing that rolls there "
      + "aren't offered. Hover a toggle (touch screen: press and hold it) to see where its affixes roll. Good bases get their own rule, on until the cap (then the BiS rules take over)."));

  put(f, h("h3", {}, "Weapons"), typeChips(S.meta.enums.weapons, o.weapons),
    h("div", { class: "row" }, h("label", {}, "Weapon and off-hand rules",
      h("select", { onchange: (e) => { o.weapon_mode = e.target.value; levChanged(); } },
        [["highlight", "highlight bases with a build affix, show the rest"], ["require", "only bases with a build affix"], ["bases", "all bases, ignore affixes"]]
          .map(([v, l]) => h("option", { value: v, selected: v === o.weapon_mode }, l))))),
    h("p", { class: "hint" }, "Bases are batched by level requirement; each batch's rule is on until the next batch takes over."),
    sectionAffixes(o, "weapons", toggleList), classAffixPicker(o, "weapons", toggleList), goodBases(o, slots.weapons, toggleList));

  put(f, h("h3", {}, "Off-hands"), typeChips(S.meta.enums.offhands, o.offhands),
    sectionAffixes(o, "offhands", toggleList), classAffixPicker(o, "offhands", toggleList), goodBases(o, slots.offhands, toggleList));

  // armour and jewelry are one rule set each: the heading's checkbox switches it on
  const switchHead = (label, key) => h("h3", {}, h("label", { class: "section-toggle" },
    h("input", { type: "checkbox", checked: o[key], onchange: () => { o[key] = !o[key]; levChanged(); } }), label));
  put(f, switchHead("Armour", "armour"), o.armour ? [
    h("div", { class: "row" },
      h("label", {}, "Shown with", numInput(o.gear_min_affixes, (v) => { o.gear_min_affixes = v; levChanged(); }, { min: 1, max: 4, width: "52px" }), "+ build affixes,"),
      h("label", {}, "with 1 below level", numInput(o.single_affix_until, (v) => { o.single_affix_until = v; levChanged(); }, { min: 0, max: 100, width: "56px" }))),
    sectionAffixes(o, "armour", toggleList), classAffixPicker(o, "armour", toggleList), goodBases(o, slots.armour, toggleList),
  ] : h("p", { class: "hint" }, "Off: no rules for helmets, body armours, boots and gloves."));

  put(f, switchHead("Jewelry & belts", "jewelry"), o.jewelry ? [
    h("p", { class: "hint" }, "Their base matters little and their best bases come early: each one with a build affix shows until the cap."),
    sectionAffixes(o, "jewelry", toggleList), classAffixPicker(o, "jewelry", toggleList), goodBases(o, slots.jewelry, toggleList),
  ] : h("p", { class: "hint" }, "Off: no rules for amulets, rings, relics and belts."));

  put(f, h("h3", {}, "Look"));
  for (const [kind, label] of STYLE_KINDS) {
    const st = { ...STYLE_DEFAULTS[kind], ...(o.style?.[kind] || {}) };
    const setStyle = (patch) => {
      o.style = o.style || {};
      const next = { ...st, ...patch };   // color null = no recolour (the default swatch)
      o.style[kind] = next;
      levChanged();
    };
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "row" }, palette(S.meta.palette.filter, st.color == null || st.color < 0 ? null : st.color, (i) => setStyle({ color: i })),
        h("label", {}, h("input", { type: "checkbox", checked: !!st.emphasized, onchange: (e) => setStyle({ emphasized: e.target.checked }) }), "emphasized")));
  }
  put(f, h("h3", {}, "Naming"),
    h("div", { class: "row" }, h("label", {}, "Rule prefix", h("input", { value: o.rule_prefix, size: 6, onchange: (e) => { o.rule_prefix = e.target.value; levChanged(); } })),
      h("label", {}, "Header", h("input", { value: o.header, size: 30, onchange: (e) => { o.header = e.target.value; levChanged(); } }))),
    h("p", { class: "hint" }, "Rules starting with the prefix are the generated section: applying again replaces them in place."),
    h("div", { class: "row" },
      h("button", { onclick: () => { S.lev.opts = structuredClone(S.meta.leveling_defaults); levChanged(); } }, "Reset to config.toml"),
      h("button", { onclick: showToml }, "Copy as config.toml")));
}

const normName = (x) => String(x).toLowerCase().replace(/[^a-z0-9]/g, "");
/** Whether a kind of gear's exclude list names the affix: by id, or by its English name - the game's or the
 *  affix's own (config.toml). */
const affixNames = (a) => new Set([normName(a.en_name || a.name), normName(a.internal_name || a.en_name || a.name)]);
function excludes(sec, a) {
  const n = affixNames(a);
  return (sec.exclude || []).some((e) => e === a.id || (typeof e === "string" && n.has(normName(e))));
}
function unexclude(sec, a) {
  const n = affixNames(a);
  sec.exclude = (sec.exclude || []).filter((e) => e !== a.id && !(typeof e === "string" && n.has(normName(e))));
}

/** A kind of gear's affix toggles: only those with affixes that roll on it, with what its rules take as counts. */
function sectionAffixes(o, s, toggleList) {
  const picks = o[sectionKey(s)];
  const used = S.lev.result?.picked?.[s] || {};
  const wrap = h("div", { class: "section-affixes" },
    h("div", { class: "row" }, h("b", {}, "Affixes"), h("span", { class: "spacer" }),
      (() => {   // the copy runs from the button: browsing the list with the keyboard changes nothing
        const from = h("select", {}, h("option", { value: "" }, "Copy toggles from…"),
          LEV_SECTIONS.filter(([x]) => x !== s).map(([x, label]) => h("option", { value: x }, label)));
        return [from, h("button", { onclick: () => {
          const src = from.value ? o[sectionKey(from.value)] : null;
          if (!src) { toast("Pick the kind of gear to copy the toggles from first."); return; }
          for (const [g] of TOGGLE_GROUPS) picks[g] = [...(src[g] || [])];
          if (s === "weapons" && picks.attributes.length) picks.attributes = ["all_attributes"];   // single ones don't roll on weapons
          if (s === "weapons" && !picks.defensive) picks.defence = [];   // hidden (and unused) while defensive affixes are off
          levChanged();
        } }, "Copy")];
      })()));
  for (const [g, label] of TOGGLE_GROUPS) {
    if (s === "weapons" && g === "defence") {
      put(wrap, h("label", { class: "row" }, h("input", { type: "checkbox", checked: !!picks.defensive,
        onchange: (e) => { picks.defensive = e.target.checked; levChanged(); } }), "Include defensive affixes",
      h("span", { class: "hint" }, "health on kill / hit, leech, dodge, mana … - rarely worth a weapon's affix slot")));
      if (!picks.defensive) continue;
    }
    const toggles = S.meta.toggles.filter((t) => t.group === g && toggleRolls(t.key, s, o.character_class).length);
    if (!toggles.length) continue;
    put(wrap, h("div", { class: "group-label" }, label),
      h("div", { class: "chips" }, toggles.map((t) => {
        const chip = chipToggle(t.label, picks[g].includes(t.key), () => toggleList(picks[g], t.key), used[t.key] ? `${used[t.key].length}` : "", `${s}:${t.key}`);
        chip.title = `Its affixes roll on: ${whereText(toggleRolls(t.key, s, o.character_class))}`;
        return chip;
      })));
  }
  return wrap;
}

/** The class's class-specific affixes (skill levels ...) that roll on a kind of gear, grouped by where; ticked ones count as build affixes. */
function classAffixPicker(o, s, toggleList) {
  const cls = o.character_class;
  const ids = sectionTypeIds(s);
  const order = [...S.meta.enums.weapons, ...S.meta.enums.offhands, ...GEAR_ARMOUR, ...GEAR_JEWELRY];
  const slotRank = (a) => Math.min(...a.rolls_on.map((id) => order.indexOf(M.baseById.get(id)?.type)).filter((i) => i >= 0));
  const choices = (S.meta.class_affixes[cls] || []).map((id) => M.affix.get(id)).filter((a) => a && a.rolls_on.some((id) => ids.has(id)))
    .sort((a, b) => slotRank(a) - slotRank(b) || a.rolls_on.length - b.rolls_on.length || a.name.localeCompare(b.name));
  if (!choices.length) return null;
  const groups = new Map();
  for (const a of choices) {
    const where = whereText(a.rolls_on);
    if (!groups.has(where)) groups.set(where, []);
    groups.get(where).push(a);
  }
  const picked = new Set(o.class_affixes);
  const mine = choices.filter((a) => picked.has(a.id));
  const box = h("div", {});
  S.lev.classSearch ||= {};
  const search = h("input", { type: "search", placeholder: `Filter ${cls} affixes…`, style: { flex: 1 }, value: S.lev.classSearch[s] || "" });
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    S.lev.classSearch[s] = search.value;
    box.replaceChildren();
    for (const [where, list] of groups) {
      const shown = list.filter((a) => !q || [a.name, a.en_name, a.internal_name].some((x) => (x || "").toLowerCase().includes(q)));
      if (!shown.length) continue;
      put(box, h("div", { class: "pool-group" },
        h("div", { class: "grp-head" }, h("span", {}, `${where} (${list.length})`)),
        h("div", { class: "pool-cols" }, shown.map((a) => {
          const out = picked.has(a.id) && excludes(o[sectionKey(s)], a);   // picked, but this gear leaves it out
          return withAffixTip(h("label", { class: out ? "excluded" : "", title: out ? "Picked, but left out of this gear's rules - tick to count it again" : "" },
            h("input", { type: "checkbox", checked: picked.has(a.id) && !out, onchange: (e) => {
              if (out) unexclude(o[sectionKey(s)], a);                // count it here again, keep the pick
              else if (e.target.checked) {                            // a new pick: any earlier exclusion of it goes
                for (const [sec] of LEV_SECTIONS) unexclude(o[sectionKey(sec)], a);
                o.class_affixes.push(a.id);
              } else o.class_affixes = o.class_affixes.filter((x) => x !== a.id);
              levChanged();
            } }),
            affixName(a.id), affixPill(a), out ? h("span", { class: "hint" }, " (left out here)") : null,
            h("span", { class: "hint lvl", title: "lowest item level it rolls on" }, `lvl ${a.level}`)),
          a, new Set(a.rolls_on.filter((id) => ids.has(id))));
        }))));
    }
    if (!box.children.length) put(box, h("p", { class: "hint" }, "No affix matches."));
  };
  search.addEventListener("input", draw);
  draw();
  S.lev.openClass ||= {};
  return h("details", { class: "class-affixes", open: S.lev.openClass[s] || null, ontoggle: (e) => { S.lev.openClass[s] = e.target.open; } },
    h("summary", {}, `${cls} affixes`, h("span", { class: "hint" }, ` · ${mine.length
      ? mine.map((a) => affixName(a.id) + (excludes(o[sectionKey(s)], a) ? " (left out here)" : "")).join(", ") : "none picked"}`)),
    h("p", { class: "hint" }, "Skill levels and other class-specific affixes that roll here, by where. Ticked ones count as build affixes on those items."),
    h("div", { class: "row" }, search,
      h("button", { disabled: !mine.length, onclick: () => { o.class_affixes = o.class_affixes.filter((id) => !mine.some((a) => a.id === id)); levChanged(); } }, "Clear")),
    box);
}

/** Good bases for the item types in use: other classes' bases stay in the list (the defaults name every class's good relics) but aren't shown or used. */
function goodBases(o, types, toggleList) {
  if (!types.length) return null;
  const cls = S.meta.enums.classes.indexOf(o.character_class);
  return h("div", {}, h("div", { class: "group-label", title: "Each type's ticked bases get their own rule above the rest - still with a build affix, but on until the cap. Class bases count only for the chosen class." }, "Good bases"),
    types.map((t) => {
      const good = (o.good_bases[t] ||= []);
      const subs = [...(M.base.get(t)?.subtypes || [])]
        .filter((s) => (cls < 0 || !s.class || s.class & (1 << cls)) && (good.includes(s.en_name) || (s.drops && s.level < o.cap)))
        .sort((a, b) => a.level - b.level || a.id - b.id);
      const names = subs.filter((s) => good.includes(s.en_name)).map((s) => s.name);
      return h("details", { class: "good-bases", open: S.lev.openGood?.has(t) || null,
        ontoggle: (e) => { (S.lev.openGood ||= new Set())[e.target.open ? "add" : "delete"](t); } },
      h("summary", {}, typeName(t), h("span", { class: "hint" }, ` · ${names.length ? names.join(", ") : "none"}`)),
      h("div", { class: "chips" }, subs.map((s) => withBaseTip(chipToggle(s.name, good.includes(s.en_name), () => toggleList(good, s.en_name), `${s.level}`), t, s))));
    }));
}

function tomlVal(v) {
  if (Array.isArray(v)) return `[${v.map(tomlVal).join(", ")}]`;
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "object" && v) return `{ ${Object.entries(v).map(([k, x]) => `${k} = ${tomlVal(x)}`).join(", ")} }`;
  return String(v);
}

function showToml() {
  const named = (ids) => (ids || []).map((id) => (typeof id === "number" ? M.affix.get(id)?.en_name || id : id));
  const o = { ...levOpts(), class_affixes: named(levBody().class_affixes) };
  for (const [s] of LEV_SECTIONS) o[sectionKey(s)] = { ...o[sectionKey(s)], exclude: named(o[sectionKey(s)]?.exclude) };
  o.style = Object.fromEntries(Object.entries(o.style || {}).map(([k, st]) => [k, st.color === null ? { ...st, color: -1 } : st]));   // -1: no recolour
  const keys = ["rule_prefix", "header", "character_class", "class_affixes", ...LEV_SECTIONS.map(([s]) => sectionKey(s)), "weapons", "offhands", "step", "cap",
    "weapon_mode", "armour", "jewelry", "gear_min_affixes", "single_affix_until", "good_bases", "rarity", "style"];
  const text = ["[leveling]", "enabled = true", ...keys.map((k) => `${k} = ${tomlVal(o[k] ?? "")}`)].join("\n");
  const dlg = $("#dlg");
  const ta = h("textarea", { value: text, style: { minHeight: "320px", minWidth: "560px" } });
  fill(dlg, h("h3", {}, "[leveling] section for config.toml"),
    h("p", { class: "hint" }, "Replace the [leveling] section in config.toml with this to get the same rules from `python -m lefilter build`."),
    ta, h("div", { class: "row" },
      h("button", { onclick: async () => { try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { ta.select(); } } }, "Copy"),
      h("button", { class: "primary", onclick: () => dlg.close() }, "Close")));
  dlg.showModal();
}

const subName = (type, b) => M.base.get(type)?.subtypes.find((s) => s.id === b.id)?.name || b.name;

function timeline(res, o) {
  const capLvl = o.cap;
  const pct = (lvl) => `${(lvl / capLvl) * 100}%`;
  const colors = ["#d9b45a", "#5aa9d9", "#9ad95a", "#d97a5a", "#b98ad9", "#5ad9c0", "#d95a9a", "#c0c0c0", "#e0d070", "#70a0e0"];
  const wrap = h("div", { class: "timeline" });
  const cursor = () => h("div", { class: "tl-cursor", style: { left: pct(Math.min(S.lvl.level, capLvl)), display: S.lvl.level < capLvl ? "" : "none" } });
  for (const [t, wins] of Object.entries(res.windows)) {
    put(wrap, h("div", { class: "tl-row" }, h("div", { class: "tl-name", title: typeName(t) }, typeName(t)),
      h("div", { class: "tl-bar" }, wins.map((w, i) => h("div", {
        class: "tl-seg", title: `character level ${w.min}-${w.max}: ${w.bases.map((b) => `${subName(t, b)} (lvl ${b.level})`).join(", ")}`,
        style: { left: pct(w.min), width: `calc(${pct(w.max + 1 - w.min)} - 2px)`, background: colors[i % colors.length] },
      }, w.bases.map((b) => subName(t, b)).join(", "))), cursor())));
  }
  for (const r of res.rules) {
    const st = r.conditions.find((c) => c.type === "SubTypeCondition");
    const lv = r.conditions.find((c) => c.type === "CharacterLevelCondition");
    // weapon / off-hand windows are drawn above
    if (!st || !lv || res.windows[st.types[0]]?.some((w) => st.types.length === 1 && w.min === lv.min && w.max === lv.max)) continue;
    const color = r.recolor ? filterColor(r.color) : "#888";
    put(wrap, h("div", { class: "tl-row" }, h("div", { class: "tl-name", title: r.name }, r.name.replace(o.rule_prefix, "")),
      h("div", { class: "tl-bar" }, h("div", { class: "tl-seg", style: { left: pct(lv.min), width: `calc(${pct(lv.max + 1 - lv.min)} - 2px)`, background: color } },
        (() => { const a = r.conditions.find((c) => c.type === "AffixCondition"); return a ? condSummary(a) : "any affixes"; })()), cursor())));
  }
  const ticks = [];
  for (let l = 0; l <= capLvl; l += o.step) ticks.push(h("span", { style: { left: pct(l) } }, l));
  put(wrap, h("div", { class: "tl-axis" }, ticks));
  return wrap;
}

function renderLevPreview() {
  const p = $("#lev-preview");
  p.replaceChildren();
  const o = levOpts();
  if (S.lev.error) { put(p, h("div", { class: "box bad" }, S.lev.error)); return; }
  const res = S.lev.result;
  if (!res) { put(p, h("div", { class: "empty" }, "Generating…")); return; }
  const n = res.rules.length;
  const total = res.merged ? res.merged.length : null;
  const where = res.merged
    ? (res.removed ? `replaces the ${res.removed} rules of the previous section` : `goes in at position ${res.position + 1}`)
    : "open a filter to apply it";
  put(p, h("div", { class: "box" },
    h("div", {}, h("b", {}, `${n} rules`), ` · ${where}`,
      total != null ? h("span", { class: total > S.meta.max_rules ? "bad" : "" }, ` · filter would have ${total}/${S.meta.max_rules} rules`) : ""),
    h("div", { class: "row" },
      h("button", { class: "primary", disabled: !S.doc || !n || total > S.meta.max_rules, onclick: applyLeveling }, S.doc ? "Apply to the open filter" : "No filter open"),
      h("button", { title: REMOVE_AFFIX_TITLE, onclick: openRemoveAffix }, "Remove an affix…"),
      h("span", { class: "hint" }, "Applying replaces the earlier generated section; save afterwards."))),
    res.warnings.map((w) => h("div", { class: "warn" }, `⚠ ${w}`)));

  if (Object.keys(res.windows).length || n) {
    put(p, h("h3", {}, "When each rule is on (character level)"),
      h("div", { class: "row" }, "Character level", h("input", { type: "range", min: 1, max: 100, value: S.lvl.level, style: { flex: 1 }, oninput: (e) => setLevel(e.target.value, "leveling") }),
        h("b", { id: "lev-lvl" }, S.lvl.level)),
      timeline(res, o), h("p", { class: "hint", id: "lev-active" }));
    updateLevCursor();
  }

  put(p, h("h3", {}, "Generated rules (top first)"),
    h("ul", { class: "gen-rules" }, res.rules.map((r) => h("li", {}, ruleSwatch(r),
      h("span", {}, r.name), isSeparator(r) ? null : h("span", { class: "rule-chips" }, r.conditions.map((c) => h("span", { class: "chip-s" }, condSummary(c))))))));

  put(p, h("h3", {}, "Affixes each kind of gear takes, and where they roll"),
    h("p", { class: "hint" }, "Untick an affix to leave it out of that gear's rules (and of the Best in slot tab's From the Leveling tab); tick it to bring it back."));
  const slots = levSlots(o);
  S.lev.openPicks ||= new Set();
  const norm = (x) => String(x).toLowerCase().replace(/[^a-z0-9]/g, "");
  for (const [s, sectionLabel] of LEV_SECTIONS) {
    if (!slots[s].length) continue;
    const key = sectionKey(s);
    const typeIds = sectionTypeIds(s);
    const rollsHere = (id) => (M.affix.get(id)?.rolls_on || []).filter((x) => typeIds.has(x));
    const excluded = new Set(res.excluded?.[s] || []);
    const classIds = res.class_affixes.filter((id) => rollsHere(id).length);
    const used = new Set(Object.values(res.picked[s] || {}).flat());
    const toggles = Object.entries(res.candidates?.[s] || res.picked[s] || {});
    // an exclusion is kept by id; bringing an affix back also drops a config.toml entry naming it
    const flip = (id, keep) => {   // from the box's own state: quick clicks before the next result stay right
      const named = norm(M.affix.get(id)?.en_name || "");
      const ex = (o[key].exclude || []).filter((e) => e !== id && !(typeof e === "string" && norm(e) === named));
      o[key].exclude = keep ? ex : [...ex, id];
      levChanged();
    };
    put(p, h("div", { class: "group-label" }, sectionLabel), toggles.length || classIds.length ? null : h("div", { class: "affix-names" }, "no affixes picked"));
    for (const [k, ids] of toggles) {
      const n = ids.filter((id) => used.has(id)).length;
      const openKey = `${s}:${k}`;
      put(p, h("details", { open: S.lev.openPicks.has(openKey) || null, ontoggle: (e) => { S.lev.openPicks[e.target.open ? "add" : "delete"](openKey); } },
        h("summary", {}, `${M.toggle.get(k)?.label || k} (${n === ids.length ? n : `${n} of ${ids.length}`})`),
        ids.length ? h("ul", { class: "affix-names pick-list" }, ids.map((id) => {
          const out = excluded.has(id), dropped = !out && !used.has(id);   // weapons' defensive filter
          return withAffixTip(h("li", { class: out ? "excluded" : "" }, h("label", {},
            h("input", { type: "checkbox", checked: !out && !dropped, disabled: dropped, onchange: (e) => flip(id, e.target.checked) }),
            affixName(id), affixPill(id),
            h("span", { class: "where" }, dropped ? " · defensive: weapons leave it out" : ` · ${whereText(rollsHere(id))}`))),
          M.affix.get(id), new Set(rollsHere(id)));
        })) : h("div", { class: "affix-names" }, "none roll here")));
    }
    if (classIds.length) {
      const n = classIds.filter((id) => !excluded.has(id)).length;
      const openKey = `${s}:class`;
      put(p, h("details", { open: S.lev.openPicks.has(openKey) || null, ontoggle: (e) => { S.lev.openPicks[e.target.open ? "add" : "delete"](openKey); } },
        h("summary", {}, `${o.character_class} affixes (${n === classIds.length ? n : `${n} of ${classIds.length}`})`),
        h("ul", { class: "affix-names pick-list" }, classIds.map((id) => withAffixTip(h("li", { class: excluded.has(id) ? "excluded" : "" }, h("label", {},
          h("input", { type: "checkbox", checked: !excluded.has(id), onchange: (e) => flip(id, e.target.checked) }),
          affixName(id), affixPill(id), h("span", { class: "where" }, ` · ${whereText(rollsHere(id))}`))), M.affix.get(id), new Set(rollsHere(id)))))));
    }
  }
}

function updateLevCursor() {
  const res = S.lev.result, o = levOpts();
  if (!res) return;
  document.querySelectorAll(".tl-cursor").forEach((c) => {
    c.style.left = `${(Math.min(S.lvl.level, o.cap) / o.cap) * 100}%`;
    c.style.display = S.lvl.level < o.cap ? "" : "none";
  });
  const lbl = $("#lev-lvl"), act = $("#lev-active");
  if (lbl) lbl.textContent = S.lvl.level;
  if (act) {
    const on = res.rules.filter((r) => !isSeparator(r) && activeAt(r, S.lvl.level));
    act.textContent = `At level ${S.lvl.level}: ${on.length ? on.map((r) => r.name.replace(o.rule_prefix, "")).join(" · ") : "no generated rule is on"}`;
  }
}

async function applyLeveling() {
  await runLeveling();   // against the filter as it is now (an undo / redo may have changed it)
  const res = S.lev.result;
  if (!res?.merged || !S.doc) return;
  if (res.merged.length > S.meta.max_rules) { toast(`That would make ${res.merged.length} rules; the game allows ${S.meta.max_rules}. Free up rules first.`, true); return; }
  if (!res.rules.length && !res.removed) { toast("Nothing to apply."); return; }
  mutate(() => {
    S.doc.rules = res.merged;
    S.sel = res.position;
  }, { editor: true });
  toast(`Leveling section applied: ${res.rules.length} rules at position ${res.position + 1}. Save to keep it.`);
  S.lvl.on = true;
  $("#lvl-on").checked = true;
  switchTab("rules");
  renderList();
  scrollToSel();
  levelingSoon();
}

/* ---------- idols and idol altars generator ---------- */

const IDOL_STYLE_KINDS = [["both", "Idols with both wanted affixes"], ["single", "Idols with one wanted affix"],
  ["altar", "Preferred idol altars (with a beam)"], ["altar_other", "Every other idol altar"]];
const IDOL_STYLE_DEFAULTS = { both: { color: 15, emphasized: true }, single: { color: 15 },
  altar: { color: 15, emphasized: true, beam_size: "LARGE", beam_color: 19 }, altar_other: { color: 15 } };
const ALTAR_KEY = "IDOL_ALTAR";
const altarPicked = (o) => o.altar.bases.length + o.altar.affixes.length > 0;

/** Stored options merged over the defaults, keeping only keys the server still knows. */
function withDefaults(defaults, stored) {
  const out = structuredClone(defaults);
  for (const k of Object.keys(defaults)) if (stored && k in stored) out[k] = stored[k];
  return out;
}

function idolOpts() {
  if (!S.idol.opts) S.idol.opts = withDefaults(S.meta.idol_defaults, store.get("idol-opts", {}));
  return S.idol.opts;
}
function idolClasses() {
  if (!S.idol.classes) {
    const lev = levOpts().character_class;
    S.idol.classes = store.get("idol-classes", lev ? [lev] : [...S.meta.enums.classes]);
  }
  return S.idol.classes;
}
const idolKind = (key) => S.meta.idol_kinds.find((k) => k.key === key);
const idolKindFor = (type, subtype) => S.meta.idol_kinds.find((k) => k.type === type && k.subtypes.includes(subtype));

/** The idol's footprint: width x height cells, as in the idol inventory. */
function idolShape(width, height, cell = 9, big = false) {
  return h("span", { class: "idol-shape" + (big ? " big" : ""), title: `${width} wide × ${height} tall`,
    style: { gridTemplateColumns: `repeat(${width}, ${cell}px)`, gridTemplateRows: `repeat(${height}, ${cell}px)` } },
  Array.from({ length: width * height }, () => h("i", { style: { width: `${cell}px`, height: `${cell}px` } })));
}

function idolChanged({ list = true, editor = true } = {}) {
  store.set("idol-opts", S.idol.opts);
  if (list) renderIdolList();
  if (editor) renderIdolEditor();
  idolsSoon();
}

const idolsSoon = debounce(runIdols, 250);

async function runIdols() {
  if (!S.meta) return;
  try {
    const body = { options: idolOpts() };
    if (S.doc) body.rules = S.doc.rules;
    S.idol.result = await api("/api/idols", body);
    S.idol.error = null;
  } catch (e) {
    S.idol.result = null;
    S.idol.error = e.message;
  }
  renderIdolSummary();
}

/** Prefill the picks from the open filter's generated idol section, if it has one. */
async function readIdolsFromFilter() {
  if (!S.doc) return;
  try {
    const got = await api("/api/idols/read", { rules: S.doc.rules, prefix: idolOpts().rule_prefix });
    if (got.found) {
      S.idol.opts.picks = got.picks;
      S.idol.opts.hide_others = got.hide_others;
      S.idol.opts.altar = got.altar;
      S.idol.opts.show_other_altars = got.show_other_altars;
      store.set("idol-opts", S.idol.opts);
    }
  } catch { /* keep the stored picks */ }
  if ($("#tab-idols").classList.contains("active")) { renderIdolList(); renderIdolEditor(); }
  idolsSoon();
}

function idolGroups() {
  const kinds = S.meta.idol_kinds;
  const groups = [
    ["All classes", "", kinds.filter((k) => !k.character_class && !k.variant)],
    ["All classes · Weaver (enhanced: also rolls Weaver idol affixes)", "", kinds.filter((k) => !k.character_class && k.variant === "weaver")],
  ];
  for (const cls of S.meta.enums.classes) {
    if (!idolClasses().includes(cls)) continue;
    groups.push([cls, cls, kinds.filter((k) => k.character_class === cls && !k.variant)]);
    groups.push([`${cls} · Omen (also rolls the 4x1, 1x4 and 2x2 affixes)`, cls, kinds.filter((k) => k.character_class === cls && k.variant === "omen")]);
  }
  return groups.filter(([, , list]) => list.length);
}

function renderIdolList() {
  const o = idolOpts();
  const f = $("#idol-list");
  f.replaceChildren();
  const toggleClass = (c) => {
    const cl = idolClasses();
    const i = cl.indexOf(c);
    if (i >= 0) cl.splice(i, 1); else cl.push(c);
    cl.sort((a, b) => S.meta.enums.classes.indexOf(a) - S.meta.enums.classes.indexOf(b));
    store.set("idol-classes", cl);
    renderIdolList();
  };
  const picked = Object.keys(o.picks).filter((k) => o.picks[k].affixes.length).length;
  put(f, h("h3", {}, "Class idols to list"),
    h("div", { class: "chips" }, S.meta.enums.classes.map((c) => chipToggle(c, idolClasses().includes(c), () => toggleClass(c)))),
    h("p", { class: "hint" }, `Sizes are width × height, as in the idol inventory. ${picked} idol kind${picked === 1 ? "" : "s"} with picks; rules exist only for those.`));
  for (const [title, , kinds] of idolGroups()) {
    put(f, h("div", { class: "group-label" }, title));
    for (const k of kinds) {
      const pick = o.picks[k.key];
      const n = pick ? pick.affixes.length : 0;
      put(f, h("div", { class: "idol-row" + (S.idol.sel === k.key ? " selected" : ""), onclick: () => { S.idol.sel = k.key; renderIdolList(); renderIdolEditor(); } },
        h("div", { class: "shape-cell" }, idolShape(k.width, k.height)),
        h("div", {}, h("div", {}, k.label), h("div", { class: "bases" }, k.base_names.join(", ") + (k.heretical_names.length ? " + heretical" : ""))),
        h("span", { class: "count" + (n ? " has" : "") }, n ? `${n} picked · needs ${Math.min(pick.min, n)}` : `${k.pool.length} affixes`)));
    }
  }
  const altar = S.meta.idol_altar;
  if (altar) {
    const nb = o.altar.bases.length, na = o.altar.affixes.length;
    put(f, h("div", { class: "group-label" }, "Idol altars"),
      h("div", { class: "idol-row" + (S.idol.sel === ALTAR_KEY ? " selected" : ""), onclick: () => { S.idol.sel = ALTAR_KEY; renderIdolList(); renderIdolEditor(); } },
        h("div", { class: "shape-cell" }, "◈"),
        h("div", {}, h("div", {}, "Idol altar"), h("div", { class: "bases" }, "preferred altars + preferred affixes")),
        h("span", { class: "count" + (nb || na ? " has" : "") }, nb || na
          ? `${nb ? `${nb} altar${nb > 1 ? "s" : ""}` : "any altar"} · ${na ? `${na} affix${na > 1 ? "es" : ""}` : "any affixes"}`
          : `${altar.bases.length} altars · ${altar.pool.length} affixes`)));
  }
  put(f, h("h3", {}, "Other idols"),
    h("label", {}, h("input", { type: "checkbox", checked: o.hide_others, onchange: (e) => { o.hide_others = e.target.checked; idolChanged(); } }),
      " Hide every other idol (normal / magic / rare / exalted) after these rules"),
    h("p", { class: "hint" }, "Unique and set idols are never hidden by it. Idol rules of your own placed below the section stop matching."));
  put(f, h("h3", {}, "Look"));
  for (const [kind, label] of IDOL_STYLE_KINDS) {
    const st = { ...IDOL_STYLE_DEFAULTS[kind], ...(o.style?.[kind] || {}) };
    const setStyle = (patch) => {
      o.style = o.style || {};
      const next = { ...st, ...patch };   // color null = no recolour (the default swatch)
      o.style[kind] = next;
      idolChanged({ editor: false });
    };
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "row" }, palette(S.meta.palette.filter, st.color == null || st.color < 0 ? null : st.color, (i) => setStyle({ color: i })),
        h("label", {}, h("input", { type: "checkbox", checked: !!st.emphasized, onchange: (e) => setStyle({ emphasized: e.target.checked }) }), "emphasized")));
  }
  put(f, h("h3", {}, "Naming"),
    h("div", { class: "row" }, h("label", {}, "Rule prefix", h("input", { value: o.rule_prefix, size: 6, onchange: (e) => { o.rule_prefix = e.target.value; idolChanged(); } })),
      h("label", {}, "Header", h("input", { value: o.header, size: 30, onchange: (e) => { o.header = e.target.value; idolChanged(); } }))),
    h("p", { class: "hint" }, "Rules starting with the prefix are the generated section: applying again replaces them in place, and opening a filter loads its picks back."),
    h("div", { class: "row" }, h("button", { onclick: () => { if (confirm("Clear the picks of every idol kind?")) { o.picks = {}; idolChanged(); } } }, "Clear all picks"),
      h("button", { onclick: readIdolsFromFilter, disabled: !S.doc }, "Reload picks from the filter")));
}

function renderIdolSummary() {
  const box = $("#idol-summary");
  if (!box) return;
  box.replaceChildren();
  if (S.idol.error) { put(box, h("div", { class: "bad" }, S.idol.error)); return; }
  const res = S.idol.result;
  if (!res) { put(box, "…"); return; }
  const n = res.rules.length;
  const total = res.merged ? res.merged.length : null;
  const where = !n ? (res.removed ? `removes the ${res.removed} rules of the previous section` : "pick affixes to generate rules")
    : res.merged ? (res.removed ? `replaces the ${res.removed} rules of the previous section` : `goes in at position ${res.position + 1}`)
      : "open a filter to apply it";
  put(box, h("div", {}, h("b", {}, `${n} rules`), ` · ${where}`,
    total != null ? h("span", { class: total > S.meta.max_rules ? "bad" : "" }, ` · filter would have ${total}/${S.meta.max_rules} rules`) : ""),
  h("div", { class: "row" },
    h("button", { class: "primary", disabled: !S.doc || (!n && !res.removed) || total > S.meta.max_rules, onclick: applyIdols }, S.doc ? "Apply to the open filter" : "No filter open"),
      h("button", { title: REMOVE_AFFIX_TITLE, onclick: openRemoveAffix }, "Remove an affix…"),
    h("span", { class: "hint" }, "Then save. Without a section yet it goes under a separator named like IDOL, else right before the uniques, else at the top.")),
  res.warnings.map((w) => h("div", { class: "warn" }, `⚠ ${w}`)),
  n ? h("details", {}, h("summary", {}, "Generated rules"),
    h("ul", { class: "gen-rules" }, res.rules.map((r) => h("li", {}, ruleSwatch(r), h("span", {}, r.name))))) : null);
}

function renderIdolEditor() {
  const p = $("#idol-editor");
  fill(p, h("div", { class: "box sticky", id: "idol-summary" }));
  renderIdolSummary();
  const o = idolOpts();
  if (S.idol.sel === ALTAR_KEY && S.meta.idol_altar) { renderAltarEditor(p, o); return; }
  const k = idolKind(S.idol.sel);
  if (!k) { put(p, h("div", { class: "empty" }, "Pick an idol kind or the idol altar on the left to choose what you want on it.")); return; }
  const pick = o.picks[k.key] || { affixes: [], min: 2 };
  const save = (next) => {
    if (next.affixes.length) o.picks[k.key] = next; else delete o.picks[k.key];
    idolChanged();
  };
  const chosen = new Set(pick.affixes);
  const toggle = (id) => save({ ...pick, affixes: chosen.has(id) ? pick.affixes.filter((x) => x !== id) : [...pick.affixes, id] });
  const groups = new Map();
  for (const a of k.pool) {
    if (!groups.has(a.group)) groups.set(a.group, []);
    groups.get(a.group).push(a);
  }
  for (const list of groups.values()) list.sort((x, y) => compareAffixes(x.id, y.id));
  const copyTargets = S.meta.idol_kinds.filter((x) => x.key !== k.key);
  const poolBox = h("div", {});
  const search = h("input", { type: "search", placeholder: "Filter this idol's affixes…", style: { flex: 1 }, value: S.idol.search || "" });
  const drawPool = () => {
    const q = search.value.trim().toLowerCase();
    S.idol.search = search.value;
    poolBox.replaceChildren();
    for (const [group, list] of groups) {
      const shown = list.filter((a) => !q || [affixName(a.id), a.name, M.affix.get(a.id)?.en_name].some((s) => (s || "").toLowerCase().includes(q)));
      if (!shown.length) continue;
      put(poolBox, h("div", { class: "pool-group" },
        h("div", { class: "grp-head" }, h("span", {}, `${catName(group)} (${list.length})`), h("span", { class: "spacer" }),
          h("button", { onclick: () => save({ ...pick, affixes: [...new Set([...pick.affixes, ...shown.map((a) => a.id)])] }) }, "all"),
          h("button", { onclick: () => save({ ...pick, affixes: pick.affixes.filter((id) => !shown.some((a) => a.id === id)) }) }, "none")),
        h("div", { class: "pool-cols" }, shown.map((a) => h("label", {},
          h("input", { type: "checkbox", checked: chosen.has(a.id), onchange: () => toggle(a.id) }), affixName(a.id), affixPill(a.id),
          affixValueCell(M.affix.get(a.id), { typeIds: new Set([k.type_id]), omen: k.variant === "omen" }))))));
    }
  };
  search.addEventListener("input", drawPool);
  drawPool();
  put(p,
    h("div", { class: "idol-head" }, idolShape(k.width, k.height, 18, true),
      h("div", {}, h("h2", { style: { margin: 0 } }, `${k.label} idol`),
        h("div", { class: "hint" }, `${k.base_names.join(", ")} · ${k.width} wide × ${k.height} tall · ${k.pool.length} possible affixes`),
        k.heretical_names.length ? h("div", { class: "hint" }, `The rule also covers its crafted heretical version, ${k.heretical_names.join(", ")}: pick its Enchanted affixes below (only heretical idols roll them)`) : null)),
    h("div", { class: "row" }, "Show it when it has",
      h("div", { class: "seg" }, [1, 2].map((n) => h("button", {
        class: Math.min(pick.min, Math.max(1, pick.affixes.length)) === n ? "on" : "",
        disabled: n > Math.max(1, pick.affixes.length), title: n === 2 ? "both of its affixes are picked ones" : "",
        onclick: () => save({ ...pick, min: n }) }, n))),
      `of the ${pick.affixes.length} picked affixes`, h("span", { class: "hint" }, "(idols carry two affixes)")),
    h("div", { class: "row" },
      h("button", { disabled: !pick.affixes.length, onclick: () => save({ ...pick, affixes: [] }) }, "Clear picks"),
      (() => {   // the copy runs from the button, not on every change of the list
        const to = h("select", { disabled: !pick.affixes.length }, h("option", { value: "" }, "Copy picks to…"),
          copyTargets.map((x) => h("option", { value: x.key }, x.label)),
          h("option", { value: "*" }, "every other idol kind"));
        // each target takes the picks that can roll on it (class affixes only reach that class's idols)
        const copyTo = (target) => {
          const pool = new Set(target.pool.map((a) => a.id));
          const prev = o.picks[target.key] || { affixes: [], min: pick.min };
          const add = pick.affixes.filter((id) => pool.has(id));
          o.picks[target.key] = { ...prev, affixes: [...new Set([...prev.affixes, ...add])] };
          if (!o.picks[target.key].affixes.length) delete o.picks[target.key];
          return add.length;
        };
        return [to, h("button", { disabled: !pick.affixes.length, onclick: () => {
          if (to.value === "*") {
            const reached = copyTargets.filter((t) => copyTo(t) > 0);
            toast(reached.length ? `Picks copied to ${reached.length} idol kinds, each taking the ones that can roll on it`
              : "None of the picks can roll on another idol kind");
            idolChanged();
            return;
          }
          const target = idolKind(to.value);
          if (!target) { toast("Pick the idol kind to copy to first."); return; }
          const n = copyTo(target);
          toast(`${n} of ${pick.affixes.length} picks can roll on ${target.label} and were added there`);
          idolChanged();
        } }, "Copy")];
      })()),
    h("div", { class: "row" }, search),
    poolBox);
}

/** The idol altar: preferred altar bases and preferred altar affixes, one rule for both. */
function renderAltarEditor(p, o) {
  const altar = S.meta.idol_altar;
  const base = M.base.get(ALTAR_KEY);
  const altarName = (b) => base?.subtypes.find((s) => s.id === b.id)?.name || b.name;
  const flip = (list, id) => { const i = list.indexOf(id); if (i >= 0) list.splice(i, 1); else list.push(id); idolChanged(); };
  const groups = new Map();
  for (const a of altar.pool) {
    if (!groups.has(a.group)) groups.set(a.group, []);
    groups.get(a.group).push(a);
  }
  for (const list of groups.values()) list.sort((x, y) => compareAffixes(x.id, y.id));
  put(p,
    h("div", { class: "idol-head" }, h("div", {}, h("h2", { style: { margin: 0 } }, "Idol altar"),
      h("div", { class: "hint" }, "One rule, with a beam: the preferred altars with at least one of the preferred affixes. Leave a list empty to take any altar / any affix."))),
    h("label", {}, h("input", { type: "checkbox", checked: o.show_other_altars, onchange: (e) => { o.show_other_altars = e.target.checked; idolChanged(); } }),
      " Below it, show every other altar (plainer look)"),
    h("h3", {}, "Preferred altars"),
    h("div", { class: "row" },
      h("button", { disabled: !o.altar.bases.length, onclick: () => { o.altar.bases = []; idolChanged(); } }, "Clear")),
    h("div", { class: "bases" }, altar.bases.map((b) => {
      const label = h("label", {},
        h("input", { type: "checkbox", checked: o.altar.bases.includes(b.id), onchange: () => flip(o.altar.bases, b.id) }),
        altarName(b), h("span", { class: "lvl" }, `lvl ${b.level}`));
      const sub = base?.subtypes.find((x) => x.id === b.id);
      return sub ? withBaseTip(label, ALTAR_KEY, sub) : label;
    })),
    h("h3", {}, "Preferred affixes"),
    h("div", { class: "row" },
      h("button", { disabled: !o.altar.affixes.length, onclick: () => { o.altar.affixes = []; idolChanged(); } }, "Clear")),
    [...groups].map(([group, list]) => h("div", { class: "pool-group" },
      h("div", { class: "grp-head" }, h("span", {}, `${catName(group)} (${list.length})`)),
      h("div", { class: "pool-cols" }, list.map((a) => h("label", {},
        h("input", { type: "checkbox", checked: o.altar.affixes.includes(a.id), onchange: () => flip(o.altar.affixes, a.id) }), affixName(a.id), affixPill(a.id),
        affixValueCell(M.affix.get(a.id), { typeIds: new Set([altar.type_id]) })))))));
}

async function applyIdols() {
  await runIdols();   // against the filter as it is now (an undo / redo may have changed it)
  const res = S.idol.result;
  if (!res?.merged || !S.doc) return;
  if (res.merged.length > S.meta.max_rules) { toast(`That would make ${res.merged.length} rules; the game allows ${S.meta.max_rules}. Free up rules first.`, true); return; }
  if (!res.rules.length && !res.removed) { toast("Nothing to apply."); return; }
  mutate(() => {
    S.doc.rules = res.merged;
    S.sel = Math.min(res.position, S.doc.rules.length - 1);
  }, { editor: true });
  toast(`Idol section applied: ${res.rules.length} rules at position ${res.position + 1}. Save to keep it.`);
  switchTab("rules");
  scrollToSel();
  idolsSoon();
}

/* ---------- best in slot generator ---------- */

const BIS_TIERS = [["bis", "Best in slot"], ["good", "Good"]];
// the Leveling tab's kind of gear for each slot (its "From the Leveling tab" picks)
const BIS_LEV_SECTION = { weapons: "weapons", offhand: "offhands", helmet: "armour", body: "armour", boots: "armour", gloves: "armour",
  belt: "jewelry", amulet: "jewelry", ring: "jewelry", relic: "jewelry" };

function bisOpts() {
  if (!S.bis.opts) {
    S.bis.opts = withDefaults(S.meta.bis.defaults, store.get("bis-opts", {}));
    S.bis.last = JSON.stringify(S.bis.opts);
  }
  return S.bis.opts;
}
/** Ctrl+Z / Ctrl+Y on the Best in slot tab: its picks, not the open filter. */
function bisUndo(back = true) {
  const from = back ? S.bis.undo : S.bis.redo, to = back ? (S.bis.redo ||= []) : (S.bis.undo ||= []);
  if (!from?.length) return;
  to.push(JSON.stringify(S.bis.opts));
  S.bis.opts = JSON.parse(from.pop());
  S.bis.last = JSON.stringify(S.bis.opts);
  store.set("bis-opts", S.bis.opts);
  renderBisList(); renderBisEditor(); bisSoon();
}
const bisSlotMeta = (key) => S.meta.bis.slots.find((s) => s.key === key);
/** A slot's options, made on first use. */
function bisSlot(key) {
  const o = bisOpts();
  return (o.slots[key] ||= { bases: {}, affixes: [], bis: { ...S.meta.bis.tier_defaults.bis }, good: { ...S.meta.bis.tier_defaults.good } });
}
const bisHasPicks = (o = bisOpts()) => Object.values(o.slots || {}).some((s) => s.affixes?.length || Object.keys(s.bases || {}).length);

function bisChanged({ list = true, editor = true } = {}) {
  const now = JSON.stringify(S.bis.opts);
  if (S.bis.last != null && S.bis.last !== now) { (S.bis.undo ||= []).push(S.bis.last); S.bis.redo = []; }
  S.bis.last = now;
  store.set("bis-opts", S.bis.opts);
  if (list) renderBisList();
  if (editor) renderBisEditor();
  bisSoon();
}
const bisSoon = debounce(runBis, 250);

async function runBis() {
  if (!S.meta) return;
  try {
    const body = { options: bisOpts() };
    if (S.doc) body.rules = S.doc.rules;
    S.bis.result = await api("/api/bis", body);
    S.bis.error = null;
  } catch (e) {
    S.bis.result = null;
    S.bis.error = e.message;
  }
  renderBisSummary();
}

/** The open filter's generated BiS rules -> the tab's picks (kept when the filter has none). */
async function readBisFromFilter() {
  if (!S.doc) return;
  try {
    const got = await api("/api/bis/read", { rules: S.doc.rules });
    if (got.found) {
      const o = bisOpts();
      o.slots = got.slots;
      if (got.rarity) o.rarity = got.rarity;
      o.character_class = got.character_class || "";   // the class the filter's BiS rules were made for (none: none)
      bisChanged({ list: false, editor: false });      // the replaced picks stay one Ctrl+Z away
    }
  } catch { /* keep the stored picks */ }
  if ($("#tab-bis").classList.contains("active")) { renderBisList(); renderBisEditor(); }
  bisSoon();
}

/** "Two-Handed Sword, Axe · 3 bases · 6 affixes · 2+ T7 / 1+ T6" */
function bisSlotSummary(key) {
  const s = bisOpts().slots[key];
  const meta = bisSlotMeta(key);
  if (!s || (!s.affixes.length && !Object.keys(s.bases).length)) return "";
  const types = Object.keys(s.bases);
  const nBases = Object.values(s.bases).reduce((n, ids) => n + ids.length, 0);
  const tiers = BIS_TIERS.filter(([t]) => s[t]?.enabled && (s.affixes.length || t === "bis"))
    .map(([t]) => (s.affixes.length ? `${s[t].min}+ T${s[t].tier}` : "bases") + (s[t].fp ? ` FP${s[t].fp}+` : "")).join(" / ");
  return [meta.types.length > 1 ? (types.length ? types.map(typeName).join(", ") : "no item type") : null,
    nBases ? `${nBases} base${nBases > 1 ? "s" : ""}` : "every base", `${s.affixes.length} affixes`, tiers].filter(Boolean).join(" · ");
}

function renderBisList() {
  const o = bisOpts();
  const f = $("#bis-list");
  f.replaceChildren();
  const toggleIn = (arr, v) => { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); bisChanged(); };
  put(f, h("h3", {}, "Build"),
    h("div", { class: "row" }, h("label", {}, "Class",
      h("select", { onchange: (e) => { o.character_class = e.target.value; bisChanged(); } },
        h("option", { value: "" }, "any (no class bases or affixes)"),
        S.meta.enums.classes.map((c) => h("option", { value: c, selected: c === o.character_class }, c))))),
    h("p", { class: "hint" }, "A class lists its class bases (relics, class weapons) and class affixes, and leaves out other classes' bases."),
    h("div", { class: "group-label" }, "Rarity"),
    h("div", { class: "chips" }, S.meta.enums.rarities.map((r) => chipToggle(cap(r), o.rarity.includes(r), () => toggleIn(o.rarity, r)))),
    h("h3", {}, "Slots"),
    h("p", { class: "hint" }, "Per slot the bases and affixes you want, and two tiers: best in slot (with a beam) and good below it. Slots with nothing picked get no rules."));
  for (const slot of S.meta.bis.slots) {
    const summary = bisSlotSummary(slot.key);
    put(f, h("div", { class: "idol-row bis-row" + (S.bis.sel === slot.key ? " selected" : ""),
      onclick: () => { if (S.bis.sel !== slot.key) S.bis.search = ""; S.bis.sel = slot.key; renderBisList(); renderBisEditor(); } },
      h("div", {}, h("div", {}, slot.label), h("div", { class: "bases" }, summary || (slot.types.length > 1 ? `${slot.types.length} item types` : "nothing picked"))),
      h("span", { class: "count" + (summary ? " has" : "") }, summary ? "✓" : "")));
  }
  put(f, h("h3", {}, "Look"));
  for (const [kind, label] of BIS_TIERS) {
    const st = { ...S.meta.bis.style_defaults[kind], ...(o.style?.[kind] || {}) };
    const setStyle = (patch) => {
      o.style = o.style || {};
      const next = { ...st, ...patch };   // color null = no recolour (the default swatch)
      o.style[kind] = next;
      bisChanged({ editor: false });
    };
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "row" }, palette(S.meta.palette.filter, st.color == null || st.color < 0 ? null : st.color, (i) => setStyle({ color: i })),
        h("label", {}, h("input", { type: "checkbox", checked: !!st.emphasized, onchange: (e) => setStyle({ emphasized: e.target.checked }) }), "emphasized"),
        h("label", {}, h("input", { type: "checkbox", checked: (st.beam_size || "NONE") !== "NONE",
          onchange: (e) => setStyle({ beam_size: e.target.checked ? "LARGEST" : "NONE", beam_color: st.beam_color ?? 12 }) }), "beam")));
  }
  put(f, h("div", { class: "row" },
    h("button", { onclick: readBisFromFilter, disabled: !S.doc }, "Reload picks from the filter"),
    h("button", { onclick: () => { if (confirm("Clear the picks of every slot?")) { o.slots = {}; bisChanged(); } } }, "Clear all picks")),
  h("p", { class: "hint" }, "Opening a filter loads its BiS picks back (when it has generated BiS rules)."));
}

function renderBisSummary() {
  const box = $("#bis-summary");
  if (!box) return;
  box.replaceChildren();
  if (S.bis.error) { put(box, h("div", { class: "bad" }, S.bis.error)); return; }
  const res = S.bis.result;
  if (!res) { put(box, "…"); return; }
  const n = res.rules.length;
  const total = res.merged ? res.merged.length : null;
  const where = !n ? (res.removed ? `removes the ${res.removed} BiS rules there` : "pick bases or affixes to generate rules")
    : res.merged ? (res.removed ? `replaces the filter's ${res.removed} BiS rules` : `goes in at position ${res.position + 1}`)
      : "open a filter to apply it";
  put(box, h("div", {}, h("b", {}, `${n} rules`), ` · ${where}`,
    total != null ? h("span", { class: total > S.meta.max_rules ? "bad" : "" }, ` · filter would have ${total}/${S.meta.max_rules} rules`) : ""),
  h("div", { class: "row" },
    h("button", { class: "primary", disabled: !S.doc || (!n && !res.removed) || total > S.meta.max_rules, onclick: applyBis }, S.doc ? "Apply to the open filter" : "No filter open"),
      h("button", { title: REMOVE_AFFIX_TITLE, onclick: openRemoveAffix }, "Remove an affix…"),
    h("span", { class: "hint" }, "Replaces its \"BIS - \" rules (the template's generic ones the first time); then save.")),
  res.warnings.map((w) => h("div", { class: "warn" }, `⚠ ${w}`)),
  n ? h("details", {}, h("summary", {}, "Generated rules"),
    h("ul", { class: "gen-rules" }, res.rules.map((r) => h("li", {}, ruleSwatch(r), h("span", {}, r.name),
      h("span", { class: "rule-chips" }, r.conditions.map((c) => h("span", { class: "chip-s" }, condSummary(c)))))))) : null);
}

async function applyBis() {
  await runBis();   // against the filter as it is now (an undo / redo may have changed it)
  const res = S.bis.result;
  if (!res?.merged || !S.doc) return;
  if (res.merged.length > S.meta.max_rules) { toast(`That would make ${res.merged.length} rules; the game allows ${S.meta.max_rules}. Free up rules first.`, true); return; }
  if (!res.rules.length && !res.removed) { toast("Nothing to apply."); return; }
  mutate(() => {
    S.doc.rules = res.merged;
    S.sel = Math.min(res.position, S.doc.rules.length - 1);
  }, { editor: true });
  toast(`BiS rules applied: ${res.rules.length} at position ${res.position + 1}. Save to keep them.`);
  switchTab("rules");
  scrollToSel();
  bisSoon();
}

function renderBisEditor() {
  const p = $("#bis-editor");
  fill(p, h("div", { class: "box sticky", id: "bis-summary" }));
  renderBisSummary();
  const o = bisOpts();
  const meta = bisSlotMeta(S.bis.sel) || S.meta.bis.slots[0];
  S.bis.sel = meta.key;
  const s = bisSlot(meta.key);
  const multi = meta.types.length > 1;
  const cls = S.meta.enums.classes.indexOf(o.character_class);
  const fits = (sub) => cls < 0 || !sub.class || sub.class & (1 << cls);
  const flip = (list, v) => { const i = list.indexOf(v); if (i >= 0) list.splice(i, 1); else list.push(v); bisChanged(); };
  put(p, h("h2", { style: { margin: "4px 0" } }, meta.label));

  // tiers
  put(p, h("h3", {}, "What an item needs"));
  for (const [t, label] of BIS_TIERS) {
    const need = s[t];
    const num = (key, opt) => numInput(need[key], (v) => { need[key] = v; bisChanged({ list: true, editor: false }); }, opt);
    put(p, h("div", { class: "row bis-tier" },
      h("label", {}, h("input", { type: "checkbox", checked: need.enabled, onchange: (e) => { need.enabled = e.target.checked; bisChanged(); } }), h("b", {}, label)),
      h("span", {}, "at least"), num("min", { min: 1, max: 6, width: "48px" }), h("span", {}, "of the picked affixes at tier"),
      num("tier", { min: 1, max: 8, width: "48px" }), h("span", {}, "or higher; forging potential at least"),
      num("fp", { min: 0, max: 255, width: "56px", nullable: true })));
  }
  put(p, h("p", { class: "hint" }, "Good sits below best in slot, so an item meeting both shows as best in slot. Leave forging potential empty for any. "
    + "With bases but no affixes, one rule shows those bases (best in slot's look and forging potential)."));

  // bases
  put(p, h("h3", {}, multi ? "Item types and bases" : "Bases"),
    h("p", { class: "hint" }, multi ? "Tick the types the build may use - each gets its own rules - then, if you like, their bases (none ticked = every base)."
      : "None ticked = every base. Hover a base (or press and hold it) for its implicits."));
  const baseChips = (t) => {
    const ids = s.bases[t] || [];
    // a single-type slot keeps no entry while no base is ticked (no base filter, nothing picked)
    const toggleBase = (id) => {
      const next = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
      if (next.length || multi) s.bases[t] = next; else delete s.bases[t];
      bisChanged();
    };
    // picked bases another class needs stay listed (marked) so they can be unticked; the rules leave them out
    const all = M.base.get(t)?.subtypes || [];
    const subs = [...all].filter((x) => ids.includes(x.id) || (fits(x) && x.drops))
      .sort((a, b) => a.level - b.level || a.id - b.id);
    const gone = ids.filter((id) => !all.some((x) => x.id === id));   // picked under another game version
    return h("div", { class: "chips" }, gone.map((id) => {
      const chip = chipToggle(`#${id}`, true, () => toggleBase(id));
      chip.classList.add("misfit");
      chip.title = "not in this game version's data: the rules leave it out - click to remove";
      return chip;
    }), subs.map((x) => {
      const chip = withBaseTip(chipToggle(x.name, ids.includes(x.id), () => toggleBase(x.id), `${x.level}`), t, x);
      if (!fits(x)) { chip.classList.add("misfit"); chip.title = `not a ${o.character_class} base: the rules leave it out`; }
      return chip;
    }));
  };
  if (multi) {
    const noneFit = (t) => cls >= 0 && !(M.base.get(t)?.subtypes || []).some(fits);
    put(p, h("div", { class: "chips" }, meta.types.map((t) => {
      const chip = chipToggle(typeName(t), t in s.bases, () => {
        if (t in s.bases) delete s.bases[t]; else s.bases[t] = [];
        bisChanged();
      });
      if (noneFit(t)) { chip.classList.add("misfit"); chip.title = `no ${o.character_class} bases: no rule for it`; }
      return chip;
    })));
    for (const t of meta.types.filter((x) => x in s.bases)) {
      const n = s.bases[t].length;
      put(p, h("details", { class: "good-bases", open: S.bis.openTypes?.has(t) || null,
        ontoggle: (e) => { (S.bis.openTypes ||= new Set())[e.target.open ? "add" : "delete"](t); } },
      h("summary", {}, typeName(t), h("span", { class: "hint" }, ` · ${n ? `${n} base${n > 1 ? "s" : ""}` : "every base"}`)), baseChips(t)));
    }
  } else {
    put(p, baseChips(meta.types[0]));
  }

  // affixes
  const typeIds = new Set((multi ? Object.keys(s.bases) : meta.types).map((t) => M.base.get(t)?.id));
  const offered = (S.meta.bis.pools[o.character_class || ""]?.[meta.key] || []).map((id) => M.affix.get(id)).filter(Boolean)
    .filter((a) => !multi || !typeIds.size || a.rolls_on.some((x) => typeIds.has(x)));
  const picked = new Set(s.affixes);
  const groups = new Map();
  for (const a of [...offered].sort(compareAffixes)) {
    const g = affixGroup(a);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(a);
  }
  const fromLeveling = () => {
    const lev = S.lev.result;
    if (!lev) { toast("The Leveling tab's picks aren't worked out yet - open it once and try again."); return; }
    const pool = new Set(offered.map((a) => a.id));
    const section = BIS_LEV_SECTION[meta.key], out = new Set(lev.excluded?.[section] || []);
    const ids = [...Object.values(lev.picked[section] || {}).flat(), ...lev.class_affixes.filter((id) => !out.has(id))]
      .filter((id) => pool.has(id));
    const add = [...new Set(ids)].filter((id) => !picked.has(id));
    s.affixes.push(...add);
    toast(`${add.length} affixes added from the Leveling tab's ${BIS_LEV_SECTION[meta.key]} picks.`);
    bisChanged();
  };
  const box = h("div", {});
  const search = h("input", { type: "search", placeholder: "Filter affixes…", style: { flex: 1 }, value: S.bis.search || "" });
  const f = ((S.bis.filters ||= {})[meta.key] ||= newAffixFilter());
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    S.bis.search = search.value;
    box.replaceChildren();
    const lists = f.sort === "name"
      ? [["", [...offered].filter(affixShownBy(f)).sort((x, y) => x.name.localeCompare(y.name))]]
      : [...groups].filter(([g]) => !f.cats.size || f.cats.has(g));
    for (const [g, list] of lists) {
      const shown = list.filter((a) => !q || [a.name, a.en_name, a.internal_name].some((x) => (x || "").toLowerCase().includes(q)));
      if (!shown.length) continue;
      put(box, h("div", { class: "pool-group" },
        g ? h("div", { class: "grp-head" }, h("span", {}, `${g} (${list.length})`)) : null,
        h("div", { class: "pool-cols" }, shown.map((a) => h("label", {},
          h("input", { type: "checkbox", checked: picked.has(a.id), onchange: () => flip(s.affixes, a.id) }), affixName(a.id), affixPill(a),
          affixValueCell(a, { typeIds }))))));
    }
    if (!box.children.length) put(box, h("p", { class: "hint" }, multi && !typeIds.size ? "Tick an item type first." : "No affix matches."));
  };
  search.addEventListener("input", draw);
  draw();
  const unknown = s.affixes.filter((id) => !offered.some((a) => a.id === id));
  /** What a slot takes: its class pool, and for weapons / off-hand with types ticked only what rolls on those. */
  const poolOf = (slot) => {
    const pool = S.meta.bis.pools[o.character_class || ""]?.[slot] || [];
    const sm = bisSlotMeta(slot), types = Object.keys(bisOpts().slots[slot]?.bases || {});
    if (sm.types.length < 2 || !types.length) return new Set(pool);
    const ids = new Set(types.map((t) => M.base.get(t)?.id));
    return new Set(pool.filter((id) => M.affix.get(id)?.rolls_on.some((x) => ids.has(x))));
  };
  const copyTo = (targets) => {
    let added = 0, slots = 0;
    for (const t of targets) {
      const pool = poolOf(t.key), dest = bisSlot(t.key);
      const add = s.affixes.filter((id) => pool.has(id) && !dest.affixes.includes(id));
      if (add.length) { dest.affixes.push(...add); added += add.length; slots++; }
    }
    toast(added ? `${added} affixes added to ${slots} slot${slots > 1 ? "s" : ""} (only where they roll).` : "Nothing to add: those slots have them already or they don't roll there.");
    bisChanged();
  };
  const others = S.meta.bis.slots.filter((x) => x.key !== meta.key);
  put(p, h("h3", {}, `Affixes (${s.affixes.length} picked)`),
    h("div", { class: "row" }, search,
      h("button", { onclick: fromLeveling, title: "Add what the Leveling tab's toggles pick for this gear" }, "From the Leveling tab"),
      h("button", { disabled: !s.affixes.length, onclick: () => { s.affixes = []; bisChanged(); } }, "Clear")),
    h("div", { class: "row" },
      affixClipboardRow(s.affixes, `BiS ${meta.label}`, (ids) => {
        const pool = poolOf(meta.key);
        const add = ids.filter((id) => pool.has(id) && !s.affixes.includes(id));
        s.affixes.push(...add);
        toast(`${add.length} affixes pasted` + (ids.length > add.length ? `; ${ids.length - add.length} can't roll on ${meta.label.toLowerCase()} or were there already` : "") + ".");
        bisChanged();
      }, () => renderBisEditor()),
      (() => {   // the copy runs from the button: browsing the list with the keyboard copies nothing
        const target = h("select", { disabled: !s.affixes.length },
          h("option", { value: "" }, "Copy affixes to…"), others.map((x) => h("option", { value: x.key }, x.label)),
          h("option", { value: "*" }, "every other slot"));
        return [target, h("button", { disabled: !s.affixes.length, onclick: () => {
          const v = target.value;
          if (!v) { toast("Pick the slot(s) to copy to first."); return; }
          copyTo(v === "*" ? others : others.filter((x) => x.key === v));
        } }, "Copy")];
      })()),
    s.affixes.length ? h("div", { class: "selected-list" }, groupedChips(s.affixes, (id) => h("span", { class: "chip on" }, affixName(id), affixPill(id),
      h("button", { title: "remove", onclick: () => flip(s.affixes, id) }, "×")))) : null,
    unknown.length ? h("p", { class: "hint" }, `${unknown.length} picked affix${unknown.length > 1 ? "es" : ""} can't roll on the ticked item types (or the class); `
      + "they only count where they roll.") : null,
    offered.length ? affixFilterBar(f, offered, draw) : null,
    box);
}

/* ---------- item tester ---------- */

function testItem() {
  if (!S.test.item) {
    S.test.item = store.get("test-item", null) || { type: "TWO_HANDED_SWORD", subtype: 0, rarity: "RARE", unique: null, affixes: [{ id: 30, tier: 3 }], lp: null, ww: null, fp: null, corrupted: false, faction: null };
    if (!M.base.has(S.test.item.type)) S.test.item.type = "HELMET";
  }
  return S.test.item;
}

function testChanged(redraw = true) {
  store.set("test-item", S.test.item);
  if (redraw) renderTestForm();
  testSoon();
}

const testSoon = debounce(runTest, 200);

async function runTest() {
  if (!S.doc || !S.meta) { S.test.result = null; renderTestResult(); return; }
  try {
    S.test.result = await api("/api/match", { rules: S.doc.rules, item: testItem(), level: S.lvl.level });
  } catch (e) {
    S.test.result = { error: e.message };
  }
  renderTestResult();
}

function renderTestForm() {
  const it = testItem();
  const f = $("#test-form");
  f.replaceChildren();
  const base = M.base.get(it.type);
  const subs = [...(base?.subtypes || [])].sort((a, b) => a.level - b.level);
  const typeSel = h("select", { onchange: (e) => { it.type = e.target.value; it.subtype = (M.base.get(it.type)?.subtypes[0]?.id) ?? 0; it.unique = null; it.affixes = []; testChanged(); } });
  for (const [cat, list] of basesByCategory()) put(typeSel, h("optgroup", { label: cat }, list.map((b) => h("option", { value: b.type, selected: b.type === it.type }, b.name))));
  const isUnique = ["UNIQUE", "SET", "LEGENDARY"].includes(it.rarity);
  const uniques = S.meta.uniques.filter((u) => !u.hidden && base && u.base_type === base.id && (it.rarity === "SET" ? u.is_set : !u.is_set));
  const kind = idolKindFor(it.type, it.subtype);   // idols: exactly the pool the game rolls from
  const eligible = (kind ? kind.pool.map((p) => M.affix.get(p.id)).filter(Boolean)
    : S.meta.affixes.filter((a) => base && a.rolls_on.includes(base.id))).sort(compareAffixes);
  const optgroups = (sel) => {
    const out = [];
    for (const x of eligible) {
      if (affixGroup(x) !== out.at(-1)?.label) out.push(h("optgroup", { label: affixGroup(x) }));
      put(out.at(-1), h("option", { value: x.id, selected: x.id === sel }, `${x.name} (${x.kind || (x.prefix ? "prefix" : "suffix")})`));
    }
    return out;
  };
  put(f, 
    h("h3", {}, "Item"),
    h("div", { class: "row" }, h("label", {}, "Type", typeSel)),
    h("div", { class: "row" }, h("label", {}, "Base", h("select", { onchange: (e) => { it.subtype = Number(e.target.value); testChanged(); } },
      subs.map((s) => h("option", { value: s.id, selected: s.id === it.subtype }, `${s.name} (lvl ${s.level})${s.drops ? "" : " – no drop"}`))))),
    h("div", { class: "row" }, h("label", {}, "Rarity", h("select", { onchange: (e) => { it.rarity = e.target.value; it.unique = null; testChanged(); } },
      ["NORMAL", "MAGIC", "RARE", "UNIQUE", "SET", "LEGENDARY"].map((r) => h("option", { value: r, selected: r === it.rarity }, cap(r))))),
      h("span", { class: "hint" }, "magic/rare with a T6+ affix count as exalted")),
    isUnique ? h("div", { class: "row" }, h("label", {}, it.rarity === "SET" ? "Set item" : "Unique", h("select", {
      onchange: (e) => { it.unique = e.target.value ? Number(e.target.value) : null; const u = M.unique.get(it.unique); if (u) it.subtype = u.sub_type; testChanged(); } },
    h("option", { value: "" }, uniques.length ? "choose…" : "none for this type"),
    uniques.map((u) => h("option", { value: u.id, selected: u.id === it.unique }, `${u.name}${u.weavers_will ? " (WW)" : ""}`))))) : null,
    isUnique ? h("div", { class: "row" },
      h("label", {}, "LP", numInput(it.lp, (v) => { it.lp = v; testChanged(false); }, { min: 0, max: 4, nullable: true, width: "52px" })),
      h("label", {}, "WW", numInput(it.ww, (v) => { it.ww = v; testChanged(false); }, { min: 0, max: 28, nullable: true, width: "52px" }))) : null,
    h("div", { class: "row" }, h("label", {}, "Forging potential", numInput(it.fp, (v) => { it.fp = v; testChanged(false); }, { min: 0, nullable: true, width: "60px" })),
      h("label", {}, h("input", { type: "checkbox", checked: it.corrupted, onchange: (e) => { it.corrupted = e.target.checked; testChanged(false); } }), "Corrupted"),
      h("label", {}, "Faction", h("select", { onchange: (e) => { it.faction = e.target.value || null; testChanged(false); } },
        h("option", { value: "" }, "none"), S.meta.enums.factions.map((x) => h("option", { value: x, selected: x === it.faction }, factionLabel(x)))))),
    h("h3", {}, "Affixes"),
    it.affixes.map((a, i) => h("div", { class: "affix-line" },
      h("select", { onchange: (e) => { a.id = Number(e.target.value); testChanged(false); } },
        optgroups(a.id),
        eligible.some((x) => x.id === a.id) ? null : h("option", { value: a.id, selected: true }, affixName(a.id))),
      affixPill(a.id),
      h("select", { onchange: (e) => { a.tier = Number(e.target.value); testChanged(false); } },
        Array.from({ length: Math.max(a.tier || 1, affixMaxTier(a.id)) }, (_, t) => t + 1)
          .map((t) => h("option", { value: t, selected: t === a.tier }, `T${t}`))),
      h("button", { onclick: () => { it.affixes.splice(i, 1); testChanged(); } }, "✕"))),
    h("div", { class: "row" }, h("button", { disabled: !eligible.length || it.affixes.length >= 6, onclick: () => {
      const used = new Set(it.affixes.map((a) => a.id));
      const next = eligible.find((x) => !used.has(x.id));
      if (next) { it.affixes.push({ id: next.id, tier: 3 }); testChanged(); }
    } }, "+ Affix")),
    h("h3", {}, "Character level"),
    h("div", { class: "row" }, h("input", { type: "range", min: 1, max: 100, value: S.lvl.level, style: { flex: 1 }, oninput: (e) => setLevel(e.target.value, "test") }),
      Object.assign(numInput(S.lvl.level, (v) => setLevel(v), { min: 1, max: 100 }), { id: "test-lvl" })));
}

function itemLabelText(it) {
  if (it.unique != null) return uniqueName(it.unique);
  const s = M.base.get(it.type)?.subtypes.find((x) => x.id === it.subtype);
  return s ? s.name : typeName(it.type);
}

function renderTestResult() {
  const p = $("#test-result");
  p.replaceChildren();
  if (!S.doc) { put(p, h("div", { class: "empty" }, "Open a filter to test items against it.")); return; }
  const res = S.test.result;
  if (!res) { put(p, h("div", { class: "empty" }, "…")); return; }
  if (res.error) { put(p, h("div", { class: "box bad" }, res.error)); return; }
  const it = testItem();
  const rule = res.index != null ? S.doc.rules[res.index] : null;
  const look = rule ? { show: rule.type !== "HIDE", recolor: rule.recolor, color: rule.color, emphasized: rule.emphasized, beam_override: rule.beam_override, beam_size: rule.beam_size, beam_color: rule.beam_color }
    : { show: true, recolor: false, emphasized: false };
  put(p, h("h3", {}, `At character level ${S.lvl.level}`), labelPreview(look, res.rarity, itemLabelText(it)),
    h("div", { class: "box" }, rule
      ? h("span", {}, rule.type === "HIDE" ? "Hidden" : "Shown", " by rule ",
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); S.sel = res.index; switchTab("rules"); renderList(); renderEditor(); scrollToSel(); } }, `#${res.index + 1} ${rule.name || "(unnamed)"}`))
      : "No rule matches: the item is shown with its default look."));
  const rows = [];
  res.results.forEach((r, i) => {
    const rr = S.doc.rules[i];
    if (!rr) return;
    const after = res.index != null && i > res.index;
    const status = !r.enabled ? "off" : r.matched === true ? "✓" : r.matched === false ? "✗" : "?";
    const why = r.checks.filter(([ok]) => (r.matched ? true : ok !== true)).map(([ok, txt]) => txt).join("; ");
    rows.push(h("tr", { class: (i === res.index ? "hit" : "") + (after ? " after" : "") },
      h("td", {}, i + 1), h("td", { class: status === "✓" ? "good" : status === "✗" ? "bad" : "hint" }, status),
      h("td", {}, rr.name || (isRaw(rr) ? "(raw rule)" : "(unnamed)")), h("td", { class: "why" }, isSeparator(rr) ? "no conditions" : why)));
  });
  put(p, h("h3", {}, "Every rule, top first"), h("p", { class: "hint" }, "✗ shows why a rule doesn't match; rules below the one that decides are never reached."),
    h("table", { class: "checks" }, h("tbody", {}, rows)));
}

/* ---------- tabs & wiring ---------- */

function switchTab(name) {
  document.querySelectorAll(".tabs > button[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "leveling") { renderLevForm(); renderLevPreview(); levelingSoon(); }
  if (name === "test") { renderTestForm(); runTest(); }
  if (name === "idols") { renderIdolList(); renderIdolEditor(); idolsSoon(); }
  if (name === "bis") { renderBisList(); renderBisEditor(); bisSoon(); }
  if (name === "rules") { renderList(); renderEditor(); }   // e.g. the paste button after copying elsewhere
}

function wire() {
  document.querySelectorAll(".tabs > button[data-tab]").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#file-select").addEventListener("change", (e) => {
    const v = e.target.value;
    if (!v) return;
    if (!confirmDiscard()) { loadFilters(); return; }
    const [loc, ...rest] = v.split("|");
    openFile(loc, rest.join("|"));
  });
  $("#btn-new").onclick = newFilter;
  $("#btn-reload").onclick = () => { if (S.file && confirmDiscard()) openFile(S.file.location, S.file.file); };
  $("#btn-save").onclick = () => save(false);
  $("#btn-saveas").onclick = () => save(true);
  $("#btn-undo").onclick = undo;
  $("#btn-redo").onclick = redo;
  $("#btn-add").onclick = addRule;
  $("#btn-dup").onclick = dupRule;
  $("#btn-del").onclick = delRule;
  $("#btn-up").onclick = () => stepRule(-1);
  $("#btn-down").onclick = () => stepRule(1);
  $("#btn-refresh").onclick = refreshGenerated;
  $("#btn-free").onclick = freeUpRules;
  $("#btn-remove-affix").onclick = openRemoveAffix;
  $("#btn-restore-exalted").onclick = restoreExalted;
  $("#btn-complete").onclick = addMissingSections;
  $("#btn-reorder").onclick = reorderSections;
  $("#btn-delete").onclick = deleteDialog;
  $("#hdr-icon").onclick = headerIconDialog;
  $("#search").addEventListener("input", (e) => { S.search = e.target.value; renderList(); });
  $("#lvl-on").addEventListener("change", (e) => { S.lvl.on = e.target.checked; renderList(); });
  $("#lvl-range").addEventListener("input", (e) => setLevel(e.target.value));
  $("#lvl-num").addEventListener("change", (e) => setLevel(e.target.value));
  $("#hdr-name").addEventListener("input", (e) => mutate(() => { S.doc.header.name = e.target.value; }, { list: false, typing: true }));
  $("#hdr-desc").addEventListener("input", (e) => mutate(() => { S.doc.header.description = e.target.value; }, { list: false, typing: true }));
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(false); }
    else if (!typing && (e.ctrlKey || e.metaKey) && ["z", "y"].includes(e.key.toLowerCase())) {
      e.preventDefault();
      const back = e.key.toLowerCase() === "z" && !e.shiftKey;
      if ($("#tab-bis").classList.contains("active")) bisUndo(back);   // the BiS picks
      else back ? undo() : redo();
    }
    else if (!typing && $("#tab-rules").classList.contains("active") && (e.key === "ArrowDown" || e.key === "ArrowUp") && S.doc) {
      e.preventDefault();
      S.sel = Math.max(0, Math.min(S.doc.rules.length - 1, S.sel + (e.key === "ArrowDown" ? 1 : -1)));
      renderList(); renderEditor(); scrollToSel();
    }
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

async function init() {
  wire();
  // A tip whose element was re-rendered under the mouse gets no pointerleave: moving onto anything else hides it.
  document.addEventListener("pointerover", (e) => { if (e.pointerType !== "touch" && !tipOwner(e.target)) hideTip(); });
  wireTouchTips();
  try {
    S.meta = await api("/api/meta");
  } catch (e) {
    toast(`Could not load game data: ${e.message}`, true);
    return;
  }
  META_EN = S.meta;
  S.meta = applyLanguage(META_EN, null);
  indexMeta(S.meta);
  const langSel = $("#lang-select");
  fill(langSel, ...META_EN.languages.map((l) => h("option", { value: l.code }, l.label)));
  langSel.addEventListener("change", () => setLanguage(langSel.value));
  const lang = store.get("lang", "en");
  if (lang !== "en" && META_EN.languages.some((l) => l.code === lang)) await setLanguage(lang);
  const upd = S.meta.template.update;
  if (upd?.error) toast(`The new-filter template couldn't be updated: ${upd.error}`, true);
  else if (upd && !upd.created) {
    const counts = ["added", "updated", "dropped"].filter((k) => upd[k]?.length).map((k) => `${upd[k].length} ${k}`).join(", ") || "no rule changes";
    toast(`New-filter template updated from ${upd.from || "an unstamped version"} to ${upd.to}: ${counts}`
      + (upd.kept?.length ? `; your edits kept on ${upd.kept.length} rules this version also changed` : "")
      + `. Rules you removed stay removed${upd.backup ? `; the old one is in ${upd.backup}` : ""}.`);
  }
  await loadFilters();
  const last = store.get("last-file", null);
  const pick = (last && S.filters.find((f) => f.location === last.location && f.file === last.file)) || S.filters.find((f) => f.location === "game") || S.filters[0];
  if (pick) await openFile(pick.location, pick.file);
  else renderDoc();
  renderLevForm();
  levelingSoon();
}

init();
