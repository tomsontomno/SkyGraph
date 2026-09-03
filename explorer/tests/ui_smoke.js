/* Headless smoke test of the real UI: runs static/app.js against a minimal DOM stub and drives it.
 *
 * Usage: node ui_smoke.js <bundle.json>
 * Prints JSON describing what the page rendered and what happened on two hops, so
 * explorer/tests/test_ui.py can check it against explorer/dp.py and simulate/routefmt.py.
 *
 * The stub implements only what app.js and map.js touch.  Anything they use that is missing throws,
 * which is exactly the point: a typo in an element id or a wrong API shows up as a failure here.
 */
'use strict';

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------- minimal DOM

function makeElement(tag) {
  const el = {
    tagName: String(tag).toLowerCase(),
    children: [],
    attrs: {},
    style: {},
    handlers: {},
    className: '',
    innerHTML: '',
    hidden: false,
    checked: false,
    disabled: false,
    selected: false,
    value: '',
    parentNode: null,
    _text: '',
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
    removeChild(child) { this.children = this.children.filter((c) => c !== child); return child; },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    setAttribute(name, value) { this.attrs[name] = String(value); if (name === 'class') this.className = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; },
    addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
    removeEventListener(type, fn) {
      if (this.handlers[type]) this.handlers[type] = this.handlers[type].filter((f) => f !== fn);
    },
    dispatch(type, event) { (this.handlers[type] || []).forEach((fn) => fn(event || { clientX: 12, clientY: 34 })); },
    getBoundingClientRect() { return { width: 960, height: 620, left: 0, top: 0, right: 960, bottom: 620 }; },
    classList: {
      add() {}, remove() {}, toggle() {}, contains() { return false; }
    }
  };
  Object.defineProperty(el, 'textContent', {
    get() { return this._text; },
    set(value) { this._text = String(value); this.children = []; }
  });
  Object.defineProperty(el, 'options', {
    get() { return this.children.filter((c) => c.tagName === 'option'); }
  });
  Object.defineProperty(el, 'selectedOptions', {
    get() { return this.options.filter((o) => o.selected); }
  });
  Object.defineProperty(el, 'selectedIndex', {
    get() { const i = this.options.findIndex((o) => o.selected); return i; },
    set(index) { this.options.forEach((o, i) => { o.selected = i === index; }); this.value = (this.options[index] || {}).value || ''; }
  });
  return el;
}

const ELEMENT_IDS = [
  'scan-select', 'start-select', 'start-radius', 'start-resolved', 'return-select', 'return-radius',
  'return-resolved', 'return-reset', 'totals', 'min-gap', 'max-gap', 'max-flights',
  'daily-cap', 'cap-mode', 'highlight-new', 'city-list',
  'detail-title', 'detail-hint', 'flight-list-wrap', 'flight-list', 'flight-back', 'map',
  'map-note', 'tooltip', 'busy', 'breadcrumb', 'back-btn', 'reset-btn', 'hop-panel',
  'tab-hop', 'tab-settings',
  'archive-bar', 'archive-day', 'archive-label', 'archive-length', 'archive-original',
  'required-chips', 'milestones-panel', 'tab-milestones', 'milestone-search',
  'milestone-results', 'pick-toggle', 'pick-banner',
  'panel-toggle', 'settings-panel', 'sidebar', 'crumbs', 'price', 'day-note'
];

// mirrors the defaults in index.html; explorer/tests/test_ui.py checks that they stay in sync
const INITIAL_VALUES = {
  'min-gap': '1', 'max-gap': '18', 'max-flights': '', 'daily-cap': '3',
  'cap-mode': 'rolling24', 'start-radius': '180', 'return-radius': '180',
  'archive-day': '0', 'archive-length': '4'
};

const registry = new Map();
ELEMENT_IDS.forEach((id) => {
  const el = makeElement(id.endsWith('select') || id === 'cap-mode' || id === 'archive-length'
    ? 'select'
    : (['panel-toggle', 'tab-hop', 'tab-settings', 'tab-milestones', 'pick-toggle'].indexOf(id) !== -1
        ? 'button' : (id === 'milestone-search' ? 'input' : 'div')));
  el.id = id;
  if (Object.prototype.hasOwnProperty.call(INITIAL_VALUES, id)) el.value = INITIAL_VALUES[id];
  if (id === 'highlight-new') el.checked = true;
  registry.set(id, el);
});

const modeRadios = [
  Object.assign(makeElement('input'), { value: 'rt', checked: true }),
  Object.assign(makeElement('input'), { value: 'ow', checked: false })
];

const documentHandlers = {};
const documentStub = {
  getElementById(id) {
    if (!registry.has(id)) throw new Error('app.js asked for an unknown element id: ' + id);
    return registry.get(id);
  },
  createElement: makeElement,
  createElementNS(ns, name) { return makeElement(name); },
  createTextNode(text) {
    const node = makeElement('#text');
    node.textContent = text;
    return node;
  },
  querySelector(selector) {
    if (selector === 'input[name="mode"]:checked') return modeRadios.find((r) => r.checked);
    throw new Error('unsupported querySelector: ' + selector);
  },
  querySelectorAll(selector) {
    if (selector === 'input[name="mode"]') return modeRadios;
    throw new Error('unsupported querySelectorAll: ' + selector);
  },
  addEventListener(type, fn) { (documentHandlers[type] = documentHandlers[type] || []).push(fn); }
};

const windowStub = {
  innerWidth: 1280, innerHeight: 800,
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  addEventListener() {}, removeEventListener() {}
};

// ---------------------------------------------------------------- bundle + fetch

const bundlePath = process.argv[2];
if (!bundlePath) throw new Error('usage: node ui_smoke.js <bundle.json> [archive-dir]');
const bundle = JSON.parse(fs.readFileSync(bundlePath, 'utf8'));
const index = { scans: [{ scan: bundle.scan, label: bundle.label, source: bundle.source,
                          stats: bundle.stats, day0: bundle.day0 }] };
const archiveDir = process.argv[3] || null;   // optional: exercises the archive day slider

global.window = windowStub;
global.document = documentStub;
global.fetch = function (url) {
  if (url.indexOf('index.json') !== -1) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(index) });
  }
  if (url.indexOf('archive-days.json') !== -1) {
    if (!archiveDir) return Promise.resolve({ ok: false, status: 404 });
    const manifest = JSON.parse(fs.readFileSync(path.join(archiveDir, 'archive-days.json'), 'utf8'));
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(manifest) });
  }
  const day = /arch-day-[\d-]+\.json/.exec(url);
  if (day && archiveDir) {
    const payload = JSON.parse(fs.readFileSync(path.join(archiveDir, day[0]), 'utf8'));
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(bundle) });
};

windowStub.ExplorerDP = require(path.join(__dirname, '..', 'static', 'dp.js'));
windowStub.ExplorerMap = require(path.join(__dirname, '..', 'static', 'map.js'));
global.ExplorerDP = windowStub.ExplorerDP;
global.ExplorerMap = windowStub.ExplorerMap;
require(path.join(__dirname, '..', 'static', 'app.js'));

// ---------------------------------------------------------------- drive the page

const settle = () => new Promise((resolve) => setTimeout(resolve, 25));

function cityListNames() {
  return registry.get('city-list').children.map((li) => {
    const match = /<span class="name">([^<]*)<\/span>/.exec(li.innerHTML);
    return match ? match[1] : null;
  });
}

function cityListShares() {
  return registry.get('city-list').children.map((li) => {
    const match = /<span class="share">([^<]*)<\/span>/.exec(li.innerHTML);
    return match ? match[1] : null;
  });
}

async function main() {
  (documentHandlers.DOMContentLoaded || []).forEach((fn) => fn());
  await settle();
  await settle();

  const out = { steps: [], mapKind: null, tooltip: null, errors: [] };
  const note = registry.get('map-note')._text;
  if (note.indexOf('Fehler') === 0) out.errors.push(note);
  out.mapKind = registry.get('map').children.length ? 'placeholder' : 'osm';

  const record = (label) => {
    // the page reports failures into the map note; catch them here or they stay invisible
    const note = registry.get('map-note')._text;
    if (note.indexOf('Fehler') === 0 && out.errors.indexOf(note) === -1) out.errors.push(label + ': ' + note);
    return {
    label,
    breadcrumb: registry.get('breadcrumb')._text,
    startResolved: registry.get('start-resolved').innerHTML.replace(/<[^>]+>/g, ''),
    returnResolved: registry.get('return-resolved').innerHTML.replace(/<[^>]+>/g, ''),
    totals: registry.get('totals').innerHTML.replace(/<[^>]+>/g, ''),
    cities: cityListNames(),
    shares: cityListShares(),
    backDisabled: registry.get('back-btn').disabled,
    svgNodes: registry.get('map').children.length,
    hint: registry.get('detail-hint')._text,
    price: registry.get('price')._text,
    dayNote: registry.get('day-note')._text
    };
  };

  out.steps.push(record('start'));
  out.chosen = [];

  // hover the first city -> tooltip, then open it and take its first flight
  for (let hop = 0; hop < 2; hop++) {
    const list = registry.get('city-list');
    if (!list.children.length) break;
    const first = list.children[0];
    first.dispatch('mousemove', { clientX: 100, clientY: 100 });
    if (hop === 0) out.tooltip = registry.get('tooltip').innerHTML;
    first.dispatch('click');
    await settle();
    const flights = registry.get('flight-list').children;
    if (!flights.length) { out.errors.push('no flights listed for the first city'); break; }
    const row = flights[0].innerHTML;
    const times = /<span class="time">([^<]*) → ([^<]*)<\/span>/.exec(row);
    const title = /Flüge nach <b>([^<]*)<\/b>/.exec(registry.get('detail-title').innerHTML);
    if (!times || !title) { out.errors.push('flight row or title not readable: ' + row); break; }
    out.chosen.push({ city: title[1], depLabel: times[1], arrLabel: times[2] });
    out.steps.push({ label: 'flights-hop' + hop, count: flights.length,
                     first: row.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim(),
                     title: registry.get('detail-title').innerHTML.replace(/<[^>]+>/g, ' ')
                       .replace(/\s+/g, ' ').trim() });
    flights[0].dispatch('click');
    await settle();
    await settle();
    out.steps.push(record('after-hop' + (hop + 1)));
  }

  // back and reset must work
  registry.get('back-btn').dispatch('click');
  await settle();
  await settle();
  out.steps.push(record('after-back'));
  registry.get('reset-btn').dispatch('click');
  await settle();
  await settle();
  out.steps.push(record('after-reset'));

  // switching tabs must not throw and must not disturb the state
  registry.get('tab-settings').dispatch('click');
  await settle();
  out.tabsAfterSettings = { settings: registry.get('settings-panel').hidden,
                            hop: registry.get('hop-panel').hidden };
  // the country search must find the country and adding it must swallow its cities
  registry.get('tab-milestones').dispatch('click');
  registry.get('milestone-search').value = 'Türk';
  registry.get('milestone-search').dispatch('input');
  await settle();
  out.countryRows = registry.get('milestone-results').children
    .map((li) => li.innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim());
  // pick mode must toggle without disturbing the route
  registry.get('pick-toggle').dispatch('click');
  await settle();
  out.pickOn = { banner: !registry.get('pick-banner').hidden, tab: registry.get('milestones-panel').hidden };
  registry.get('pick-toggle').dispatch('click');
  await settle();
  out.pickOff = { banner: !registry.get('pick-banner').hidden };
  registry.get('milestone-search').value = '';
  registry.get('milestone-search').dispatch('input');
  await settle();
  registry.get('tab-hop').dispatch('click');
  await settle();
  out.steps.push(record('after-tab-switch'));
  out.tabsAfterHop = { settings: registry.get('settings-panel').hidden,
                       hop: registry.get('hop-panel').hidden };

  // a radius around the start must widen the set of start cities
  registry.get('start-radius').value = '400';
  registry.get('start-radius').dispatch('input');
  await settle();
  await settle();
  out.steps.push(record('after-radius'));

  // one way must reveal the cities that round trip hides because there is no way home
  registry.get('start-radius').value = String(INITIAL_VALUES['start-radius']);
  registry.get('start-radius').dispatch('input');
  await settle();
  modeRadios[0].checked = false;
  modeRadios[1].checked = true;
  modeRadios[1].dispatch('change');
  for (let i = 0; i < 4; i++) await settle();
  out.steps.push(record('one-way'));
  modeRadios[1].checked = false;
  modeRadios[0].checked = true;
  modeRadios[0].dispatch('change');
  for (let i = 0; i < 4; i++) await settle();
  out.steps.push(record('round-trip'));

  out.archiveOffered = registry.get('scan-select').options
    .some((o) => o.value === '__archive__');
  out.archiveBarHidden = registry.get('archive-bar').hidden;

  // Pflichtstädte: add one via the + button, then remove it again via its chip
  registry.get('start-radius').value = String(INITIAL_VALUES['start-radius']);
  registry.get('start-radius').dispatch('input');
  await settle();
  const before = record('before-required');
  const wish = 'Abu Dhabi';
  registry.get('tab-milestones').dispatch('click');
  registry.get('milestone-search').value = wish;
  registry.get('milestone-search').dispatch('input');
  await settle();
  const rows = registry.get('milestone-results').children;
  const option = rows.find((li) => li.innerHTML.indexOf('>' + wish + '<') !== -1);
  if (option) {
    option.dispatch('click');
    for (let i = 0; i < 4; i++) await settle();
    const after = record('with-required');
    after.chips = registry.get('required-chips').children
      .map((c) => (c._text || '') + c.children.map((x) => x._text).join(''));
    out.steps.push(after);
    // the chip's × button removes it again
    const chip = registry.get('required-chips').children[0];
    const closer = chip && chip.children.find((c) => c.tagName === 'button');
    if (closer) {
      closer.dispatch('click');
      for (let i = 0; i < 4; i++) await settle();
      out.steps.push(record('after-required-removed'));
    }
  }
  out.steps.push(before);

  // the mobile settings toggle must not throw and must not disturb the state
  registry.get('panel-toggle').dispatch('click');
  await settle();
  out.steps.push(record('after-panel-toggle'));

  if (archiveDir) {
    registry.get('start-radius').value = '0';
    registry.get('start-radius').dispatch('input');
    await settle();
    registry.get('scan-select').value = '__archive__';
    registry.get('scan-select').dispatch('change');
    for (let i = 0; i < 6; i++) await settle();
    out.steps.push(Object.assign(record('archive-window'),
      { archiveLabel: registry.get('archive-label')._text, barHidden: registry.get('archive-bar').hidden }));
    registry.get('archive-original').checked = true;
    registry.get('archive-original').dispatch('change');
    for (let i = 0; i < 6; i++) await settle();
    out.steps.push(Object.assign(record('archive-original'),
      { archiveLabel: registry.get('archive-label')._text }));
    registry.get('archive-original').checked = false;
    registry.get('archive-day').value = '0';
    registry.get('archive-day').dispatch('input');
    for (let i = 0; i < 6; i++) await settle();
    out.steps.push(Object.assign(record('archive-first-day'),
      { archiveLabel: registry.get('archive-label')._text }));
  }

  process.stdout.write(JSON.stringify(out));
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
