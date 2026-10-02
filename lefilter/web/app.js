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
    }
  }
  for (const u of meta.uniques) {
    u.en_name = u.name;
    if (tr?.uniques[u.id]) u.name = tr.uniques[u.id];
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
}
function redo() {
  if (!S.redo.length) return;
  S.undo.push(JSON.stringify(S.doc));
  S.doc = JSON.parse(S.redo.pop());
  S.dirty = true;
  clampSel();
  renderDoc();
}
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
  dlg.replaceChildren(
    h("h3", {}, "Save filter as"),
    h("div", { class: "row fields" }, h("label", {}, "Folder ", locSel)),
    h("div", { class: "row fields" }, h("label", {}, "File ", fileIn)),
    h("p", { class: "hint" }, "The in-game name is the filter name field, not the file name."),
    h("div", { class: "row" },
      h("button", { onclick: () => dlg.close() }, "Cancel"),
      h("button", { class: "primary", onclick: async () => {
        let f = fileIn.value.trim();
        if (!f) return;
        if (!f.toLowerCase().endsWith(".xml")) f += ".xml";
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
    wrap.replaceChildren(
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
  dlg.replaceChildren(h("h3", {}, "Filter icon"),
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
  const last = store.get("new-filter", { character_class: "", fill_bis: true, add_leveling: false, add_idols: false });
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
    box("fill_bis", "Fill the BiS rules with the build's affixes (Leveling tab toggles and weapons)"),
    box("add_leveling", "Add the leveling section (Leveling tab settings)"),
    box("add_idols", hasPicks ? "Add the idol section (Idols and Idol Altars generator picks)" : "Add the idol section (no idol or altar picks yet)", hasPicks),
  ];
  const create = async () => {
    const flags = Object.fromEntries(boxes.map(([k, b]) => [k, b.checked]));
    store.set("new-filter", { character_class: clsSel.value, ...flags, icon: icon.icon, icon_color: icon.color });
    const options = { name: nameIn.value.trim() || "New filter", character_class: clsSel.value,
      fill_bis: flags.fill_bis, add_leveling: flags.add_leveling, leveling: levOpts(), icon: icon.icon, icon_color: icon.color };
    if (flags.add_idols) options.idols = idolOpts();
    try {
      const res = await api("/api/new", { options });
      dlg.close();
      if (options.character_class) {   // the class also becomes the generators' default
        levOpts().character_class = options.character_class;
        store.set("lev-opts", S.lev.opts);
        S.idol.classes = [options.character_class];
        store.set("idol-classes", S.idol.classes);
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
  dlg.replaceChildren(
    h("h3", {}, "New filter"),
    h("div", { class: "row fields" }, h("label", {}, "Name ", nameIn)),
    h("div", { class: "row fields" }, h("label", {}, "Class ", clsSel)),
    h("p", { class: "hint" }, "The class switches on its \"Hide non-<class> class\" and shatter rules and becomes the generators' class."),
    h("div", { class: "group-label" }, "Icon (follows the class until you pick one)"), picker,
    ...boxes.map(([, , row]) => row),
    h("p", { class: "hint" }, `Starts from the saved template (${LOCATION_LABELS.template}: ${S.meta.template.file} - open it from the list to edit it): `
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
  dlg.replaceChildren(
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

const CLEANUPS = [
  ["separators", "Section separators",
    "Switched-off rules without conditions: headings that only decorate the list."],
  ["leveling", "Campaign leveling rules",
    "The generated leveling section, and every rule a character level condition switches off before the leveling cap: once the campaign is done they never match again."],
  ["common_uniques", "Most common uniques",
    "The generated rules for common and uncommon uniques below LP level 60 (random drops: no boss or quest uniques) at 0-2 LP. Those uniques then fall through to the rules below, usually the bottom hide rule."],
];

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
  dlg.replaceChildren(h("h3", {}, "Free up rules"),
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
  st.replaceChildren(
    S.file ? `${{ game: "game", out: "out", template: "templates" }[S.file.location]}/${S.file.file}` : "unsaved",
    " · ", h("span", { class: n > S.meta.max_rules ? "bad" : "" }, `${n}/${S.meta.max_rules} rules`),
    S.dirty ? h("span", { class: "dirty" }, " · unsaved changes") : "",
    ` · game ${S.meta.game_version || "?"}`);
  $("#btn-undo").disabled = !S.undo.length;
  $("#btn-redo").disabled = !S.redo.length;
}

function renderHeader() {
  const btn = $("#hdr-icon");
  btn.replaceChildren(S.doc ? filterIcon(S.doc.header.icon || 0, S.doc.header.icon_color || 0, 20) : "");
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
      h("div", { class: "rule-name", title: r.name }, badge, r.name || (raw ? "(unrecognised rule, kept as is)" : "(unnamed)")),
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
      isSeparator(r) ? h("span", { class: "hint" }, "No conditions: matches every item (a disabled one is just a section header).") : null));

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
    case "SubTypeCondition": return subtypeEditor(c);
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
        }, re)))), h("p", { class: "hint" }, "Matches class-specific items of the selected classes; none selected = any item."));
    case "UniqueModifiersCondition": return uniquesEditor(c);
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

function subtypeEditor(c) {
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
    const subs = [...(base?.subtypes || [])].sort((a, b) => a.level - b.level || a.id - b.id);
    put(wrap, h("div", { class: "group-label" }, `Bases of ${base?.name} (none ticked = all)`),
      h("div", { class: "row" },
        h("button", { onclick: () => mutate(() => { c.subtypes = subs.filter((s) => s.drops).map((s) => s.id); }, re) }, "All droppable"),
        h("button", { onclick: () => mutate(() => { c.subtypes = []; }, re) }, "Clear")),
      h("div", { class: "bases" }, subs.map((s) => h("label", { class: s.drops ? "" : "nodrop", title: s.drops ? "" : "cannot drop" },
        h("input", { type: "checkbox", checked: c.subtypes.includes(s.id), onchange: () => mutate(() => {
          const i = c.subtypes.indexOf(s.id);
          if (i >= 0) c.subtypes.splice(i, 1); else c.subtypes.push(s.id);
        }) }),
        s.name, h("span", { class: "lvl" }, `lvl ${s.level}`)))));
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
  if (line.hide) return line.text;
  if (line.text.includes("{0}")) return line.text.replace("{0}", valueText);
  return S.meta.value_after ? `${line.text} ${valueText}` : `${valueText} ${line.text}`;
}

/** A tier's range "+4-5%", or the single value. */
function tierRangeText(line, tier, scale) {
  const [lo, hi] = line.tiers[tier];
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
function showTip(e, content) {
  if (!tipEl) { tipEl = h("div", { class: "tip" }); document.body.append(tipEl); }
  tipEl.replaceChildren(content);
  tipEl.style.display = "block";
  const pad = 14, r = tipEl.getBoundingClientRect();
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = innerHeight - r.height - 8;
  // Positions are in screen pixels; the page may be zoomed (large screens, see app.css).
  const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  tipEl.style.left = `${Math.max(8, x) / z}px`; tipEl.style.top = `${Math.max(8, y) / z}px`;
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

/** The value column: summary text, per-tier table on hover. */
function affixValueCell(affix, { tiers = null, typeIds = null, omen = false } = {}) {
  if (!affix?.lines?.length) return h("span", { class: "aval" });
  const scale = affixScale(affix, typeIds, omen);
  return h("span", { class: "aval", onmousemove: (e) => showTip(e, affixTierTable(affix, tiers, scale, typeIds, omen)),
    onmouseleave: hideTip }, affixValueSummary(affix, tiers, scale));
}

/** Searchable add-list. items: [{id, label, meta, group, alt?, cell?}], selected: Set of ids, onAdd(ids). */

function searchPicker(items, isSelected, onAdd, placeholder) {
  const results = h("div", { class: "picker" });
  const input = h("input", { type: "search", placeholder, style: { flex: 1 } });
  let shown = [];
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    shown = items.filter((it) => !isSelected(it.id) && (!q || [it.label, it.alt, it.group].some((s) => (s || "").toLowerCase().includes(q))));
    results.replaceChildren();
    let group = null;
    for (const it of shown.slice(0, 400)) {
      if (it.group !== group) { group = it.group; put(results, h("div", { class: "grp" }, group || "")); }
      put(results, h("div", { class: "opt" + (it.cell ? " with-value" : ""), onclick: () => { hideTip(); onAdd([it.id]); } },
        h("span", {}, it.label), h("span", { class: "meta" }, it.meta || ""), it.cell ? it.cell() : null));
    }
    if (shown.length > 400) put(results, h("div", { class: "opt hint" }, `…${shown.length - 400} more, refine the search`));
    if (!shown.length) put(results, h("div", { class: "opt hint" }, "nothing to add"));
  };
  input.addEventListener("input", draw);
  draw();
  return h("div", {}, h("div", { class: "row" }, input,
    h("button", { title: "Add every entry listed below", onclick: () => onAdd(shown.map((s) => s.id)) }, "Add all listed")), results);
}

function affixEditor(rule, c) {
  const re = { editor: true };
  const typeIds = ruleTypeIds(rule), omenPool = ruleOmenPool(rule);
  const omenOf = (a) => !!omenPool?.has(a.id);
  const showAll = SHOW_ALL_AFFIXES.has(c);
  const tiersOf = (a) => conditionTiers(c, Math.max(1, ...(a.lines || []).map((l) => l.tiers.length)));
  const items = S.meta.affixes
    .filter((a) => showAll || (omenPool ? omenPool.has(a.id) : !typeIds.size || a.rolls_on.some((t) => typeIds.has(t))))
    .map((a) => ({ id: a.id, label: a.name, alt: a.en_name, group: `${catName(a.header)} · ${catName(a.category)}`,
      meta: [a.prefix ? "prefix" : "suffix", a.idol ? "idol" : ""].filter(Boolean).join(" "),
      cell: () => affixValueCell(a, { tiers: tiersOf(a), typeIds, omen: omenOf(a) }) }))
    .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
  const sel = new Set(c.affixes);
  return h("div", {},
    h("div", { class: "selected-list" }, c.affixes.length ? c.affixes.map((id) => {
      const a = M.affix.get(id);
      return h("span", { class: "chip on", onmousemove: a?.lines?.length ? (e) => showTip(e, affixTierTable(a, tiersOf(a), affixScale(a, typeIds, omenOf(a)), typeIds, omenOf(a))) : null,
        onmouseleave: hideTip }, affixName(id), h("button", { title: "remove", onclick: () => { hideTip(); mutate(() => { c.affixes = c.affixes.filter((x) => x !== id); }, re); } }, "×"));
    })
      : h("span", { class: "hint" }, "No affixes listed: any affix counts.")),
    c.affixes.length ? h("div", { class: "row" }, h("button", { onclick: () => mutate(() => { c.affixes = []; }, re) }, "Remove all")) : null,
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
    searchPicker(items, (id) => sel.has(id), (ids) => mutate(() => { c.affixes = [...c.affixes, ...ids.filter((i) => !sel.has(i))]; }, re), "Search affixes to add…"));
}

function uniquesEditor(c) {
  const re = { editor: true };
  const sel = new Set(c.uniques.map((u) => u.id));
  const items = S.meta.uniques
    .map((u) => ({ id: u.id, label: u.name, alt: u.en_name, group: u.base_type_name || "", meta: `${u.is_set ? "set · " : ""}${u.weavers_will ? "WW · " : ""}LPL ${u.lpl}` }))
    .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
  const rolled = c.uniques.filter((u) => u.rolls.length).length;
  return h("div", {},
    h("div", { class: "selected-list" }, c.uniques.length ? c.uniques.map((u) =>
      h("span", { class: "chip on", title: u.rolls.length ? `${u.rolls.length} roll ranges kept` : "" }, uniqueName(u.id),
        h("button", { onclick: () => mutate(() => { c.uniques = c.uniques.filter((x) => x.id !== u.id); }, re) }, "×")))
      : h("span", { class: "hint" }, "Empty: add uniques here or in-game.")),
    rolled ? h("p", { class: "hint" }, `${rolled} of these carry roll ranges set in-game; they are kept as they are.`) : null,
    c.uniques.length ? h("div", { class: "row" }, h("button", { onclick: () => mutate(() => { c.uniques = []; }, re) }, "Remove all")) : null,
    searchPicker(items, (id) => sel.has(id), (ids) => mutate(() => {
      c.uniques = [...c.uniques, ...ids.filter((i) => !sel.has(i)).map((id) => ({ id, rolls: [] }))];
    }, re), "Search uniques / sets to add…"));
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

function levOpts() {
  if (!S.lev.opts) {
    S.lev.opts = withDefaults(S.meta.leveling_defaults, store.get("lev-opts", {}));
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
    const body = { options: levOpts() };
    if (S.doc) body.rules = S.doc.rules;
    S.lev.result = await api("/api/leveling", body);
    S.lev.error = null;
    document.querySelectorAll("[data-count]").forEach((el) => {
      const n = S.lev.result.picked[el.dataset.count];
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
  const picked = S.lev.result?.picked || {};
  const groups = [["damage", "Damage type"], ["focus", "Build focus"], ["attributes", "Attributes (any of them adds All Attributes, a two-hander affix)"],
    ["defence", "Defence & utility (armour, jewelry, off-hands)"]];
  put(f, h("h3", {}, "Affixes the build wants"),
    h("p", { class: "hint" }, "Each toggle adds every ordinary gear affix it names (e.g. Physical: \"… Physical Damage\", \"Physical Penetration\"). Weapons use damage, focus and attribute toggles only."));
  for (const [g, label] of groups) {
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "chips" }, S.meta.toggles.filter((t) => t.group === g).map((t) =>
        chipToggle(t.label, o[g].includes(t.key), () => toggleList(o[g], t.key), picked[t.key] ? `${picked[t.key].length}` : "", t.key))));
  }
  put(f, h("div", { class: "row" }, h("label", {}, "Class",
    h("select", { onchange: (e) => { o.character_class = e.target.value; levChanged(); } },
      h("option", { value: "" }, "any (no class-specific affixes)"),
      S.meta.enums.classes.map((c) => h("option", { value: c, selected: c === o.character_class }, c))))),
  h("p", { class: "hint" }, "A class adds its class-specific affixes and bases, and drops affixes it can't roll."));

  put(f, h("h3", {}, "Weapons (batched by base level)"),
    h("div", { class: "chips" }, S.meta.enums.weapons.map((t) => chipToggle(typeName(t), o.weapons.includes(t), () => toggleList(o.weapons, t)))),
    h("div", { class: "group-label" }, "Off-hands"),
    h("div", { class: "chips" }, S.meta.enums.offhands.map((t) => chipToggle(typeName(t), o.offhands.includes(t), () => toggleList(o.offhands, t)))),
    h("div", { class: "row" },
      h("label", {}, "Window", numInput(o.step, (v) => { o.step = v; levChanged(); }, { min: 1, max: 100, width: "56px" }), "levels"),
      h("label", {}, "until level", numInput(o.cap, (v) => { o.cap = v; levChanged(); }, { min: 1, max: 100, width: "56px" }))),
    h("div", { class: "row" }, h("label", {}, "Weapon rules",
      h("select", { onchange: (e) => { o.weapon_mode = e.target.value; levChanged(); } },
        [["highlight", "highlight bases with a build affix, show the rest"], ["require", "only bases with a build affix"], ["bases", "all bases, ignore affixes"]]
          .map(([v, l]) => h("option", { value: v, selected: v === o.weapon_mode }, l))))));

  put(f, h("h3", {}, "Armour, jewelry & belts"),
    h("div", { class: "chips" },
      chipToggle("Armour (helmet, body, boots, gloves)", o.armour, () => { o.armour = !o.armour; levChanged(); }),
      chipToggle("Jewelry & belts (amulet, ring, relic, belt)", o.jewelry, () => { o.jewelry = !o.jewelry; levChanged(); })),
    h("div", { class: "row" },
      h("label", {}, "Armour with", numInput(o.gear_min_affixes, (v) => { o.gear_min_affixes = v; levChanged(); }, { min: 1, max: 4, width: "52px" }), "+ build affixes"),
      h("label", {}, "and with 1 below level", numInput(o.single_affix_until, (v) => { o.single_affix_until = v; levChanged(); }, { min: 0, max: 100, width: "56px" }))));
  if (o.jewelry) put(f, h("p", { class: "hint" }, "Jewelry and belts with a build affix show until the cap."));

  const slots = [...new Set([...o.weapons, ...o.offhands]), ...(o.armour ? GEAR_ARMOUR : []), ...(o.jewelry ? GEAR_JEWELRY : [])];
  put(f, h("h3", {}, "Good bases"),
    h("p", { class: "hint" }, slots.length
      ? "Bases worth keeping all campaign: each slot's ticked bases get their own rule above the rest - still with a build affix, but on until the cap (then the BiS rules take over). Class bases count only for the chosen class."
      : "Pick weapons, armour or jewelry above to choose their good bases."));
  const cls = S.meta.enums.classes.indexOf(o.character_class);
  for (const t of slots) {
    const good = (o.good_bases[t] ||= []);
    const subs = [...(M.base.get(t)?.subtypes || [])]
      .filter((s) => good.includes(s.en_name) || (s.drops && s.level < o.cap && (cls < 0 || !s.class || s.class & (1 << cls))))
      .sort((a, b) => a.level - b.level || a.id - b.id);
    const names = subs.filter((s) => good.includes(s.en_name)).map((s) => s.name);
    put(f, h("details", { class: "good-bases", open: S.lev.openGood?.has(t) || null,
      ontoggle: (e) => { (S.lev.openGood ||= new Set())[e.target.open ? "add" : "delete"](t); } },
    h("summary", {}, typeName(t), h("span", { class: "hint" }, ` · ${names.length ? names.join(", ") : "none"}`)),
    h("div", { class: "chips" }, subs.map((s) => chipToggle(s.name, good.includes(s.en_name), () => toggleList(good, s.en_name), `${s.level}`)))));
  }

  put(f, h("h3", {}, "Rarity"),
    h("div", { class: "chips" }, S.meta.enums.rarities.map((r) => chipToggle(cap(r), o.rarity.includes(r), () => toggleList(o.rarity, r)))));

  put(f, h("h3", {}, "Look"));
  for (const [kind, label] of STYLE_KINDS) {
    const st = { ...STYLE_DEFAULTS[kind], ...(o.style?.[kind] || {}) };
    const setStyle = (patch) => {
      o.style = o.style || {};
      const next = { ...st, ...patch };
      if (next.color == null) delete next.color;
      o.style[kind] = next;
      levChanged();
    };
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "row" }, palette(S.meta.palette.filter, st.color ?? null, (i) => setStyle({ color: i })),
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

function tomlVal(v) {
  if (Array.isArray(v)) return `[${v.map(tomlVal).join(", ")}]`;
  if (typeof v === "string") return JSON.stringify(v);
  if (typeof v === "object" && v) return `{ ${Object.entries(v).map(([k, x]) => `${k} = ${tomlVal(x)}`).join(", ")} }`;
  return String(v);
}

function showToml() {
  const o = levOpts();
  const keys = ["rule_prefix", "header", "damage", "focus", "attributes", "defence", "character_class", "weapons", "offhands", "step", "cap",
    "weapon_mode", "armour", "jewelry", "gear_min_affixes", "single_affix_until", "good_bases", "rarity", "style"];
  const text = ["[leveling]", "enabled = true", ...keys.map((k) => `${k} = ${tomlVal(o[k] ?? "")}`)].join("\n");
  const dlg = $("#dlg");
  const ta = h("textarea", { value: text, style: { minHeight: "320px", minWidth: "560px" } });
  dlg.replaceChildren(h("h3", {}, "[leveling] section for config.toml"),
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
        condSummary(r.conditions.find((c) => c.type === "AffixCondition"))), cursor())));
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

  put(p, h("h3", {}, "Affixes picked by each toggle"));
  for (const [key, affixes] of Object.entries(res.picked)) {
    put(p, h("details", {}, h("summary", {}, `${M.toggle.get(key)?.label || key} (${affixes.length})`),
      h("div", { class: "affix-names" }, affixes.map((a) => affixName(a.id)).join(", ") || "none")));
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

function applyLeveling() {
  const res = S.lev.result;
  if (!res?.merged || !S.doc) return;
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
      const next = { ...st, ...patch };
      if (next.color == null) delete next.color;
      o.style[kind] = next;
      idolChanged({ editor: false });
    };
    put(f, h("div", { class: "group-label" }, label),
      h("div", { class: "row" }, palette(S.meta.palette.filter, st.color ?? null, (i) => setStyle({ color: i })),
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
    h("span", { class: "hint" }, "Then save. Without a section yet it goes under a separator named like IDOL, else at the top.")),
  res.warnings.map((w) => h("div", { class: "warn" }, `⚠ ${w}`)),
  n ? h("details", {}, h("summary", {}, "Generated rules"),
    h("ul", { class: "gen-rules" }, res.rules.map((r) => h("li", {}, ruleSwatch(r), h("span", {}, r.name))))) : null);
}

function renderIdolEditor() {
  const p = $("#idol-editor");
  p.replaceChildren(h("div", { class: "box sticky", id: "idol-summary" }));
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
          h("input", { type: "checkbox", checked: chosen.has(a.id), onchange: () => toggle(a.id) }), affixName(a.id),
          affixValueCell(M.affix.get(a.id), { typeIds: new Set([k.type_id]), omen: k.variant === "omen" }))))));
    }
  };
  search.addEventListener("input", drawPool);
  drawPool();
  put(p,
    h("div", { class: "idol-head" }, idolShape(k.width, k.height, 18, true),
      h("div", {}, h("h2", { style: { margin: 0 } }, `${k.label} idol`),
        h("div", { class: "hint" }, `${k.base_names.join(", ")} · ${k.width} wide × ${k.height} tall · ${k.pool.length} possible affixes`),
        k.heretical_names.length ? h("div", { class: "hint" }, `The rule also covers its crafted heretical version: ${k.heretical_names.join(", ")}`) : null)),
    h("div", { class: "row" }, "Show it when it has",
      h("div", { class: "seg" }, [1, 2].map((n) => h("button", {
        class: Math.min(pick.min, Math.max(1, pick.affixes.length)) === n ? "on" : "",
        disabled: n > Math.max(1, pick.affixes.length), title: n === 2 ? "both of its affixes are picked ones" : "",
        onclick: () => save({ ...pick, min: n }) }, n))),
      `of the ${pick.affixes.length} picked affixes`, h("span", { class: "hint" }, "(idols carry two affixes)")),
    h("div", { class: "row" },
      h("button", { disabled: !pick.affixes.length, onclick: () => save({ ...pick, affixes: [] }) }, "Clear picks"),
      h("select", { disabled: !pick.affixes.length, onchange: (e) => {
        const target = idolKind(e.target.value);
        if (!target) return;
        const pool = new Set(target.pool.map((a) => a.id));
        const prev = o.picks[target.key] || { affixes: [], min: pick.min };
        const add = pick.affixes.filter((id) => pool.has(id));
        o.picks[target.key] = { ...prev, affixes: [...new Set([...prev.affixes, ...add])] };
        if (!o.picks[target.key].affixes.length) delete o.picks[target.key];
        toast(`${add.length} of ${pick.affixes.length} picks can roll on ${target.label} and were added there`);
        idolChanged();
      } }, h("option", { value: "" }, "Copy picks to…"), copyTargets.map((x) => h("option", { value: x.key }, x.label)))),
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
  put(p,
    h("div", { class: "idol-head" }, h("div", {}, h("h2", { style: { margin: 0 } }, "Idol altar"),
      h("div", { class: "hint" }, "One rule, with a beam: the preferred altars with at least one of the preferred affixes. Leave a list empty to take any altar / any affix."))),
    h("label", {}, h("input", { type: "checkbox", checked: o.show_other_altars, onchange: (e) => { o.show_other_altars = e.target.checked; idolChanged(); } }),
      " Below it, show every other altar (plainer look)"),
    h("h3", {}, "Preferred altars"),
    h("div", { class: "row" },
      h("button", { disabled: !o.altar.bases.length, onclick: () => { o.altar.bases = []; idolChanged(); } }, "Clear")),
    h("div", { class: "bases" }, altar.bases.map((b) => h("label", {},
      h("input", { type: "checkbox", checked: o.altar.bases.includes(b.id), onchange: () => flip(o.altar.bases, b.id) }),
      altarName(b), h("span", { class: "lvl" }, `lvl ${b.level}`)))),
    h("h3", {}, "Preferred affixes"),
    h("div", { class: "row" },
      h("button", { disabled: !o.altar.affixes.length, onclick: () => { o.altar.affixes = []; idolChanged(); } }, "Clear")),
    [...groups].map(([group, list]) => h("div", { class: "pool-group" },
      h("div", { class: "grp-head" }, h("span", {}, `${catName(group)} (${list.length})`)),
      h("div", { class: "pool-cols" }, list.map((a) => h("label", {},
        h("input", { type: "checkbox", checked: o.altar.affixes.includes(a.id), onchange: () => flip(o.altar.affixes, a.id) }), affixName(a.id),
        affixValueCell(M.affix.get(a.id), { typeIds: new Set([altar.type_id]) })))))));
}

function applyIdols() {
  const res = S.idol.result;
  if (!res?.merged || !S.doc) return;
  mutate(() => {
    S.doc.rules = res.merged;
    S.sel = Math.min(res.position, S.doc.rules.length - 1);
  }, { editor: true });
  toast(`Idol section applied: ${res.rules.length} rules at position ${res.position + 1}. Save to keep it.`);
  switchTab("rules");
  scrollToSel();
  idolsSoon();
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
  const uniques = S.meta.uniques.filter((u) => base && u.base_type === base.id && (it.rarity === "SET" ? u.is_set : !u.is_set));
  const kind = idolKindFor(it.type, it.subtype);   // idols: exactly the pool the game rolls from
  const eligible = (kind ? kind.pool.map((p) => M.affix.get(p.id)).filter(Boolean)
    : S.meta.affixes.filter((a) => base && a.rolls_on.includes(base.id))).sort((a, b) => a.name.localeCompare(b.name));
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
        eligible.map((x) => h("option", { value: x.id, selected: x.id === a.id }, `${x.name} (${x.prefix ? "prefix" : "suffix"})`)),
        eligible.some((x) => x.id === a.id) ? null : h("option", { value: a.id, selected: true }, affixName(a.id))),
      h("select", { onchange: (e) => { a.tier = Number(e.target.value); testChanged(false); } },
        [1, 2, 3, 4, 5, 6, 7, 8].map((t) => h("option", { value: t, selected: t === a.tier }, `T${t}`))),
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
  document.querySelectorAll(".tabs > button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "leveling") { renderLevForm(); renderLevPreview(); levelingSoon(); }
  if (name === "test") { renderTestForm(); runTest(); }
  if (name === "idols") { renderIdolList(); renderIdolEditor(); idolsSoon(); }
  if (name === "rules") renderList();
}

function wire() {
  document.querySelectorAll(".tabs > button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
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
    else if (!typing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (!typing && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
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
  document.addEventListener("mouseover", (e) => { if (!e.target.closest?.(".aval, .chip")) hideTip(); });
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
  langSel.replaceChildren(...META_EN.languages.map((l) => h("option", { value: l.code }, l.label)));
  langSel.addEventListener("change", () => setLanguage(langSel.value));
  const lang = store.get("lang", "en");
  if (lang !== "en" && META_EN.languages.some((l) => l.code === lang)) await setLanguage(lang);
  await loadFilters();
  const last = store.get("last-file", null);
  const pick = (last && S.filters.find((f) => f.location === last.location && f.file === last.file)) || S.filters.find((f) => f.location === "game") || S.filters[0];
  if (pick) await openFile(pick.location, pick.file);
  else renderDoc();
  renderLevForm();
  levelingSoon();
}

init();
