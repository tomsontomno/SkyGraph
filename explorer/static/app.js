/* Explorer UI: settings -> DP -> map, city list, flight list, breadcrumb.
 *
 * All counting happens in the browser (dp.js).  Every settings change rebuilds the DAG and the DP
 * and takes effect immediately; the current route is trimmed to its longest still-legal prefix.
 */
(function () {
  'use strict';

  var DP = window.ExplorerDP;
  var MAPS = window.ExplorerMap;

  var els = {};
  var ARCHIVE_SCAN = '__archive__';

  var state = {
    index: null, bundle: null, net: null, counter: null, shares: null,
    path: [], selectedCity: null, map: null, mapKind: null, settings: null,
    departureCities: new Set(), resolved: null, required: [],
    manifest: null, dayCache: new Map(), archiveToken: 0
  };

  // ---------------------------------------------------------------- helpers

  function $(id) { return document.getElementById(id); }

  function fmtInt(value) {
    if (!isFinite(value)) return '∞';
    return Math.round(value).toLocaleString('de-DE');
  }

  function fmtPct(share) {
    if (!isFinite(share)) return '–';
    var pct = share * 100;
    if (pct > 0 && pct < 0.1) return '<0,1 %';
    return pct.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' %';
  }

  function cityRecord(index) { return state.bundle.cities[index]; }
  function cityName(index) { return state.bundle.cities[index].name; }

  function isNewCountry(cityIndex) { return cityRecord(cityIndex).countryNew === true; }

  function currentCityIndex() {
    if (!state.path.length) return state.settings.startCenter;
    return state.net.flights[state.path[state.path.length - 1]].dest;
  }

  // ---------------------------------------------------------------- settings

  /* One city plus a radius -> the set of cities inside it, nearest first.  Returns the hits with
   * their distance so the panel can name them. */
  function resolveRadius(selectEl, radiusEl, indexOf) {
    var name = selectEl.value;
    if (!indexOf.has(name)) name = state.bundle.defaultStart;
    var radius = parseFloat(radiusEl.value);
    if (!isFinite(radius) || radius < 0) radius = 0;
    return { center: name, radius: radius,
             hits: DP.citiesWithin(state.bundle.cities, indexOf.get(name), radius) };
  }

  function readSettings() {
    var bundle = state.bundle;
    var indexOf = new Map(bundle.cities.map(function (c, i) { return [c.name, i]; }));
    var start = resolveRadius(els.startSelect, els.startRadius, indexOf);
    var back = resolveRadius(els.returnSelect, els.returnRadius, indexOf);
    state.resolved = { start: start, back: back };

    var maxFlightsRaw = els.maxFlights.value.trim();
    var maxFlights = maxFlightsRaw === '' ? null : Math.max(1, parseInt(maxFlightsRaw, 10) || 1);
    var minGap = parseFloat(els.minGap.value);
    var maxGap = parseFloat(els.maxGap.value);
    if (!isFinite(minGap) || minGap < 0) minGap = 0;
    if (!isFinite(maxGap) || maxGap <= minGap) maxGap = minGap + 0.5;

    return {
      startCities: new Set(start.hits.map(function (h) { return h.index; })),
      returnCities: new Set(back.hits.map(function (h) { return h.index; })),
      requiredCities: new Set(state.required.map(function (name) { return indexOf.get(name); })
                                            .filter(function (i) { return i !== undefined; })),
      startCenter: indexOf.get(start.center),
      minGapHours: minGap,
      maxGapHours: maxGap,
      maxFlights: maxFlights,
      dailyCap: Math.max(1, parseInt(els.dailyCap.value, 10) || 1),
      capMode: els.capMode.value,
      mode: document.querySelector('input[name="mode"]:checked').value,
      highlightNew: els.highlightNew.checked
    };
  }

  /* Longest prefix of `path` that is still legal under the current counter. */
  function legalPrefix(counter, path) {
    var out = [];
    for (var i = 0; i < path.length; i++) {
      if (counter.candidateIndices(out).indexOf(path[i]) === -1) break;
      var capState = DP.capStateOf(state.net, out, state.settings.dailyCap, state.settings.capMode);
      if (DP.capAdvance(capState, state.net.flights[path[i]], state.settings.dailyCap,
                        state.settings.capMode) === null) break;
      out.push(path[i]);
    }
    return out;
  }

  // ---------------------------------------------------------------- compute + render

  function recompute(refit) {
    els.busy.hidden = false;
    window.setTimeout(function () {
      try {
        state.settings = readSettings();
        state.counter = new DP.RouteCounter(state.net, state.settings);
        state.path = legalPrefix(state.counter, state.path);
        state.shares = state.counter.cityShares(state.path);
        if (state.selectedCity !== null &&
            !state.shares.cities.some(function (c) { return c.city === state.selectedCity; })) {
          state.selectedCity = null;
        }
        render(refit);
      } catch (err) {
        els.mapNote.textContent = 'Fehler: ' + err.message;
      } finally {
        els.busy.hidden = true;
      }
    }, 0);
  }

  function weightOf(entry) {
    return state.settings.mode === 'rt' ? entry.shareRoundTrip : entry.shareOneWay;
  }

  function sortedEntries() {
    return state.shares.cities.slice().sort(function (a, b) {
      var d = weightOf(b) - weightOf(a);
      return d !== 0 ? d : (cityName(a.city) < cityName(b.city) ? -1 : 1);
    });
  }

  /* The required cities as removable chips.  A chip turns red once no continuation can still
   * reach it, which is the fastest way to see that a wish is impossible from here. */
  function renderRequiredChips() {
    els.requiredChips.textContent = '';
    if (!state.required.length) {
      var hint = document.createElement('span');
      hint.className = 'empty';
      hint.textContent = 'keine – alle Routen zählen';
      els.requiredChips.appendChild(hint);
      return;
    }
    var stillPossible = state.shares
      ? state.shares.totalRoundTrip > 0 || state.shares.totalOneWay > 0 : true;
    state.required.forEach(function (name) {
      var chip = document.createElement('span');
      chip.className = 'chip' + (stillPossible ? '' : ' unreachable');
      chip.appendChild(document.createTextNode(name));
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.title = name + ' entfernen';
      remove.addEventListener('click', function () {
        state.required = state.required.filter(function (other) { return other !== name; });
        recompute(false);
      });
      chip.appendChild(remove);
      els.requiredChips.appendChild(chip);
    });
  }

  function render(refit) {
    renderRequiredChips();
    renderResolved();
    renderTotals();
    renderMap(refit);
    renderCityList();
    renderBreadcrumb();
    if (state.selectedCity !== null) renderFlightList(state.selectedCity);
    else showCityList();
  }

  /* Name the cities a radius pulled in, with the number of them that actually have departures. */
  function renderResolved() {
    var withDepartures = state.departureCities;
    var describe = function (resolved, needsDepartures) {
      var names = resolved.hits.map(function (h) { return cityName(h.index); });
      var usable = needsDepartures
        ? resolved.hits.filter(function (h) { return withDepartures.has(h.index); }).length
        : names.length;
      if (resolved.radius <= 0) {
        return '<b>' + escapeHtml(names[0] || '–') + '</b> allein' +
               (needsDepartures && !usable ? ' – keine Abflüge in diesem Scan' : '');
      }
      var extra = names.slice(1);
      return '<b>' + names.length + ' Städte</b> im Umkreis von ' + Math.round(resolved.radius) + ' km: ' +
             escapeHtml(names.join(', ')) +
             (needsDepartures ? ' · <b>' + usable + '</b> davon mit Abflügen' : '') +
             (extra.length ? '' : ' (nur die Stadt selbst)');
    };
    els.startResolved.innerHTML = describe(state.resolved.start, true);
    els.returnResolved.innerHTML = describe(state.resolved.back, false);
    els.returnResolved.appendChild(els.returnReset);
  }

  /* Wrapping pills instead of one long line, so the numbers survive a phone screen. */
  function renderTotals() {
    var totals = state.shares;
    var remaining = state.settings.maxFlights === null
      ? '∞' : String(state.settings.maxFlights - state.path.length);
    var pills = [
      'ab <b>' + escapeHtml(cityName(currentCityIndex())) + '</b>',
      '<b>' + fmtInt(totals.totalOneWay) + '</b> One-way',
      '<b>' + fmtInt(totals.totalRoundTrip) + '</b> Rundreisen',
      '<b>' + totals.cities.length + '</b> Städte',
      'noch <b>' + remaining + '</b> Flüge'
    ];
    if (!state.counter.exact) pills.push('<b>Zahlen gerundet</b>');
    els.totals.innerHTML = pills.map(function (text) {
      return '<span class="pill">' + text + '</span>';
    }).join(' ');
  }

  function renderMap(refit) {
    var center = cityRecord(currentCityIndex());
    var points = state.shares.cities.map(function (entry) {
      var record = cityRecord(entry.city);
      return {
        key: entry.city, name: record.name, lat: record.lat, lon: record.lon,
        weight: weightOf(entry),
        isNew: state.settings.highlightNew && isNewCountry(entry.city),
        selected: state.selectedCity === entry.city,
        entry: entry
      };
    });
    state.map.setData({
      center: { name: center.name, lat: center.lat, lon: center.lon },
      points: points,
      background: state.bundle.cities,
      fit: refit !== false
    });
  }

  function renderCityList() {
    var entries = sortedEntries();
    els.cityList.textContent = '';
    if (!entries.length) {
      els.detailHint.textContent = 'Von hier führt kein Flug weiter – zurückgehen oder Einstellungen lockern.';
      return;
    }
    els.detailHint.textContent = 'Größe = Anteil der Vollrouten über diesen Hop (' +
      (state.settings.mode === 'rt' ? 'Rundreise' : 'One-way') + ')' +
      (state.required.length ? ', gezählt werden nur Routen über ' + state.required.join(', ') : '') + '.';
    entries.forEach(function (entry) {
      var li = document.createElement('li');
      li.className = (state.settings.highlightNew && isNewCountry(entry.city) ? 'is-new' : '') +
                     (state.selectedCity === entry.city ? ' selected' : '');
      var weight = weightOf(entry);
      li.innerHTML =
        '<span class="name">' + escapeHtml(cityName(entry.city)) + '</span>' +
        '<span class="bar"><i style="width:' + (Math.min(1, weight) * 100).toFixed(1) + '%"></i></span>' +
        '<span class="share">' + fmtPct(weight) + '</span>';
      li.addEventListener('click', function () { selectCity(entry.city); });
      li.addEventListener('mousemove', function (ev) { showTooltip(entry, ev.clientX, ev.clientY); });
      li.addEventListener('mouseleave', hideTooltip);
      els.cityList.appendChild(li);
    });
  }

  function renderFlightList(cityIndex) {
    var entry = state.shares.cities.filter(function (c) { return c.city === cityIndex; })[0];
    if (!entry) { showCityList(); return; }
    els.detailTitle.textContent = 'Flüge nach ' + cityName(cityIndex);
    els.cityList.hidden = true;
    els.detailHint.hidden = true;
    els.flightWrap.hidden = false;
    els.flightList.textContent = '';
    entry.flights.slice().sort(function (a, b) { return a.flight.dep - b.flight.dep; }).forEach(function (hop) {
      var li = document.createElement('li');
      var count = state.settings.mode === 'rt' ? hop.counts.roundTrip : hop.counts.oneWay;
      var total = state.settings.mode === 'rt' ? state.shares.totalRoundTrip : state.shares.totalOneWay;
      li.innerHTML =
        '<span class="time">' + escapeHtml(hop.flight.depLabel) + ' → ' + escapeHtml(hop.flight.arrLabel) + '</span>' +
        '<span class="meta">' + fmtInt(count) + ' Routen · ' + fmtPct(total ? count / total : 0) + '</span>';
      li.addEventListener('click', function () { pushHop(hop.flight.index); });
      els.flightList.appendChild(li);
    });
  }

  function showCityList() {
    els.detailTitle.textContent = 'Nächster Hop';
    els.cityList.hidden = false;
    els.detailHint.hidden = false;
    els.flightWrap.hidden = true;
  }

  function renderBreadcrumb() {
    els.breadcrumb.textContent = breadcrumbText();
    els.backBtn.disabled = state.path.length === 0;
    els.resetBtn.disabled = state.path.length === 0;
  }

  /* Light format of core/route_find.py: first city with its departure, every intermediate city with
   * the next departure, the last city with its arrival. */
  function breadcrumbText() {
    if (!state.path.length) {
      var extra = state.settings.startCities.size - 1;
      return cityName(state.settings.startCenter) + (extra > 0 ? ' (+' + extra + ' im Umkreis)' : '');
    }
    var flights = state.path.map(function (i) { return state.net.flights[i]; });
    var parts = [cityName(flights[0].origin) + ' (' + flights[0].depLabel + ')'];
    flights.forEach(function (flight, i) {
      var stamp = (i < flights.length - 1) ? flights[i + 1].depLabel : flight.arrLabel;
      parts.push(cityName(flight.dest) + ' (' + stamp + ')');
    });
    return parts.join(' -> ');
  }

  // ---------------------------------------------------------------- interaction

  function selectCity(cityIndex) {
    state.selectedCity = cityIndex;
    renderMap(false);
    renderCityList();
    renderFlightList(cityIndex);
  }

  function pushHop(flightIndex) {
    state.path.push(flightIndex);
    state.selectedCity = null;
    hideTooltip();
    recompute(true);
  }

  function popHop() {
    if (!state.path.length) return;
    state.path.pop();
    state.selectedCity = null;
    hideTooltip();
    recompute(true);
  }

  function resetPath() {
    state.path = [];
    state.selectedCity = null;
    hideTooltip();
    recompute(true);
  }

  function showTooltip(entry, x, y) {
    var record = cityRecord(entry.city);
    var newLabel = record.countryNew === null ? 'unbekannt' : (record.countryNew ? 'ja' : 'nein');
    els.tooltip.innerHTML =
      '<h3>' + escapeHtml(record.name) + '</h3><dl>' +
      '<dt>Flüge</dt><dd>' + entry.flights.length + '</dd>' +
      '<dt>Anteil Rundreise</dt><dd>' + fmtPct(entry.shareRoundTrip) + '</dd>' +
      '<dt>Anteil One-way</dt><dd>' + fmtPct(entry.shareOneWay) + '</dd>' +
      '<dt>offene Rückwege</dt><dd>' + fmtInt(entry.roundTrip) + '</dd>' +
      '<dt>neues Land</dt><dd class="' + (record.countryNew ? 'new-yes' : '') + '">' + newLabel + '</dd>' +
      '</dl>';
    els.tooltip.hidden = false;
    var rect = els.tooltip.getBoundingClientRect();
    var left = Math.min(x + 14, window.innerWidth - rect.width - 8);
    var top = Math.min(y + 14, window.innerHeight - rect.height - 8);
    els.tooltip.style.left = Math.max(8, left) + 'px';
    els.tooltip.style.top = Math.max(8, top) + 'px';
  }

  function hideTooltip() { els.tooltip.hidden = true; }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  // ---------------------------------------------------------------- setup

  function createMap() {
    if (state.map) state.map.destroy();
    var preferred = els.mapKind.value === 'svg' ? 'svg' : 'auto';
    state.map = MAPS.createMap(els.map, {
      onHover: function (point, x, y) { showTooltip(point.entry, x, y); },
      onLeave: hideTooltip,
      onSelect: function (point) { selectCity(point.key); }
    }, preferred);
    state.mapKind = state.map.kind;
    els.mapNote.textContent = state.map.kind === 'osm'
      ? 'OpenStreetMap-Kacheln'
      : 'Offline-Karte (schematisch, Web-Mercator) · ziehen zum Verschieben, Mausrad zum Zoomen';
  }

  function populateCitySelects() {
    var bundle = state.bundle;
    state.departureCities = new Set(bundle.flights.map(function (f) { return f[0]; }));
    state.required = state.required.filter(function (name) {
      return bundle.cities.some(function (city) { return city.name === name; });
    });
    [els.startSelect, els.returnSelect, els.requiredSelect].forEach(function (select) {
      select.textContent = '';
      bundle.cities.forEach(function (city, index) {
        var option = document.createElement('option');
        option.value = city.name;
        // a city without departures is still a valid centre - the radius may reach the ones that fly
        option.textContent = city.name + (state.departureCities.has(index) ? '' : ' (ohne Abflüge)');
        select.appendChild(option);
      });
      select.value = bundle.defaultStart;
      if (!select.value && select.options.length) select.selectedIndex = 0;
    });
    if (els.requiredSelect.options.length) els.requiredSelect.selectedIndex = 0;
  }

  function addRequiredCity() {
    var name = els.requiredSelect.value;
    if (!name || state.required.indexOf(name) !== -1) return;
    state.required = state.required.concat([name]);
    recompute(false);
  }

  function copyStartToReturn() {
    els.returnSelect.value = els.startSelect.value;
    els.returnRadius.value = els.startRadius.value;
  }

  // ---------------------------------------------------------------- archive windows

  /* The window the slider currently selects: as many consecutive days as the length asks for,
   * clamped to the end of the archive. */
  function archiveWindow() {
    var days = state.manifest.days;
    var length = Math.max(1, parseInt(els.archiveLength.value, 10) || 4);
    var start = Math.min(Math.max(0, parseInt(els.archiveDay.value, 10) || 0), days.length - 1);
    start = Math.min(start, Math.max(0, days.length - length));
    return days.slice(start, start + length);
  }

  function fetchDay(day) {
    var cached = state.dayCache.get(day.date);
    if (cached) return Promise.resolve(cached);
    return fetch('bundles/' + encodeURIComponent(day.file))
      .then(function (response) {
        if (!response.ok) throw new Error('Archivtag ' + day.date + ' nicht ladbar (HTTP ' + response.status + ')');
        return response.json();
      })
      .then(function (payload) {
        state.dayCache.set(day.date, payload);
        return payload;
      });
  }

  /* Load the window's day files and hand the assembled bundle to the normal render path.
   * A token guards against a slow fetch overwriting a newer selection. */
  function loadArchiveWindow() {
    var window_ = archiveWindow();
    var token = ++state.archiveToken;
    var flights = window_.reduce(function (sum, day) { return sum + day.flights; }, 0);
    var scans = window_.reduce(function (sum, day) { return sum + day.scans; }, 0);
    els.archiveLabel.textContent = window_[0].date + ' – ' + window_[window_.length - 1].date +
      ' · ' + flights.toLocaleString('de-DE') + ' Flüge · ' + scans + ' Scans';
    els.busy.hidden = false;
    return Promise.all(window_.map(fetchDay))
      .then(function (payloads) {
        if (token !== state.archiveToken) return;
        useBundle(DP.bundleFromDays(state.manifest, payloads, els.archiveOriginal.checked));
      })
      .catch(function (err) {
        els.busy.hidden = true;
        els.mapNote.textContent = 'Fehler: ' + err.message;
      });
  }

  function useBundle(bundle) {
    state.bundle = bundle;
    state.net = DP.buildNetwork(bundle);
    state.path = [];
    state.selectedCity = null;
    populateCitySelects();
    recompute(true);
  }

  function loadBundle(scan) {
    els.archiveBar.hidden = scan !== ARCHIVE_SCAN;
    if (scan === ARCHIVE_SCAN) return loadArchiveWindow();
    els.busy.hidden = false;
    return fetch('bundles/' + encodeURIComponent(scan) + '.json')
      .then(function (response) {
        if (!response.ok) throw new Error('Bundle ' + scan + ' nicht ladbar (HTTP ' + response.status + ')');
        return response.json();
      })
      .then(useBundle)
      .catch(function (err) {
        els.busy.hidden = true;
        els.mapNote.textContent = 'Fehler: ' + err.message;
      });
  }

  function bindEvents() {
    els.scanSelect.addEventListener('change', function () { loadBundle(els.scanSelect.value); });
    els.startSelect.addEventListener('change', function () {
      copyStartToReturn();
      state.path = [];
      state.selectedCity = null;
      recompute(true);
    });
    els.startRadius.addEventListener('input', function () {
      state.path = [];
      state.selectedCity = null;
      recompute(true);
    });
    ['minGap', 'maxGap', 'maxFlights', 'dailyCap'].forEach(function (key) {
      els[key].addEventListener('input', function () { recompute(false); });
    });
    els.capMode.addEventListener('change', function () { recompute(false); });
    els.highlightNew.addEventListener('change', function () { recompute(false); });
    els.returnSelect.addEventListener('change', function () { recompute(false); });
    els.returnRadius.addEventListener('input', function () { recompute(false); });
    els.returnReset.addEventListener('click', function () {
      copyStartToReturn();
      recompute(false);
    });
    Array.from(document.querySelectorAll('input[name="mode"]')).forEach(function (radio) {
      radio.addEventListener('change', function () { recompute(false); });
    });
    els.requiredAdd.addEventListener('click', addRequiredCity);
    els.panelToggle.addEventListener('click', function () {
      els.settingsPanel.classList.toggle('open');
      els.panelToggle.classList.toggle('active');
      if (state.map) state.map.invalidate();
    });
    els.archiveDay.addEventListener('input', loadArchiveWindow);
    els.archiveLength.addEventListener('change', loadArchiveWindow);
    els.archiveOriginal.addEventListener('change', loadArchiveWindow);
    els.mapKind.addEventListener('change', function () { createMap(); renderMap(true); });
    els.backBtn.addEventListener('click', popHop);
    els.resetBtn.addEventListener('click', resetPath);
    els.flightBack.addEventListener('click', function () {
      state.selectedCity = null;
      showCityList();
      renderCityList();
      renderMap(false);
    });
    els.map.addEventListener('mouseleave', hideTooltip);
  }

  var started = false;

  function start() {
    if (started) return;
    started = true;
    els = {
      scanSelect: $('scan-select'), startSelect: $('start-select'), totals: $('totals'),
      mapKind: $('map-kind'), minGap: $('min-gap'), maxGap: $('max-gap'),
      maxFlights: $('max-flights'), dailyCap: $('daily-cap'), capMode: $('cap-mode'),
      highlightNew: $('highlight-new'), startRadius: $('start-radius'), returnSelect: $('return-select'),
      returnRadius: $('return-radius'), returnReset: $('return-reset'),
      startResolved: $('start-resolved'), returnResolved: $('return-resolved'),
      cityList: $('city-list'), detailTitle: $('detail-title'), detailHint: $('detail-hint'),
      flightWrap: $('flight-list-wrap'), flightList: $('flight-list'), flightBack: $('flight-back'),
      map: $('map'), mapNote: $('map-note'), tooltip: $('tooltip'), busy: $('busy'),
      breadcrumb: $('breadcrumb'), backBtn: $('back-btn'), resetBtn: $('reset-btn'),
      archiveBar: $('archive-bar'), archiveDay: $('archive-day'), archiveLabel: $('archive-label'),
      archiveLength: $('archive-length'), archiveOriginal: $('archive-original'),
      requiredSelect: $('required-select'), requiredAdd: $('required-add'),
      requiredChips: $('required-chips'), panelToggle: $('panel-toggle'),
      settingsPanel: $('settings-panel'), sidebar: $('sidebar')
    };
    createMap();
    bindEvents();
    // The archive manifest is optional: without it the page simply offers the fixed bundles.
    var manifest = fetch('bundles/archive-days.json')
      .then(function (response) { return response.ok ? response.json() : null; })
      .catch(function () { return null; });

    Promise.all([
      fetch('bundles/index.json').then(function (response) {
        if (!response.ok) throw new Error('index.json nicht ladbar (HTTP ' + response.status + ')');
        return response.json();
      }),
      manifest
    ])
      .then(function (loaded) {
        var index = loaded[0];
        state.index = index;
        state.manifest = loaded[1];
        index.scans.forEach(function (scan) {
          var option = document.createElement('option');
          option.value = scan.scan;
          option.textContent = scan.label + ' – ' + scan.stats.flights + ' Flüge';
          els.scanSelect.appendChild(option);
        });
        if (state.manifest && state.manifest.days.length) {
          var option = document.createElement('option');
          option.value = ARCHIVE_SCAN;
          option.textContent = 'Archiv: ' + state.manifest.days.length + ' Flugtage frei wählbar';
          els.scanSelect.appendChild(option);
          els.archiveDay.max = String(state.manifest.days.length - 1);
          // start on the densest window so the slider opens somewhere worth looking at
          var best = 0, bestCount = -1;
          state.manifest.days.forEach(function (day, i) {
            var sum = state.manifest.days.slice(i, i + 4)
              .reduce(function (acc, d) { return acc + d.flights; }, 0);
            if (sum > bestCount) { bestCount = sum; best = i; }
          });
          els.archiveDay.value = String(best);
        }
        if (!index.scans.length) throw new Error('keine Bundles gebaut');
        // ?scan=<id> preselects a bundle, so two tabs can show two views side by side
        var wanted = null;
        try {
          wanted = new URLSearchParams(window.location ? window.location.search : '').get('scan');
        } catch (err) {
          wanted = null;
        }
        var known = index.scans.some(function (s) { return s.scan === wanted; }) ||
                    (wanted === ARCHIVE_SCAN && state.manifest);
        var chosen = known ? wanted : index.scans[0].scan;
        els.scanSelect.value = chosen;
        return loadBundle(chosen);
      })
      .catch(function (err) {
        els.busy.hidden = true;
        els.mapNote.textContent = 'Fehler: ' + err.message + ' – erst "python -m explorer build" laufen lassen.';
      });
  }

  // Leaflet is loaded with defer, so DOMContentLoaded waits for it; the timer keeps a hanging CDN
  // from blocking the page and starts with the offline map instead.
  document.addEventListener('DOMContentLoaded', start);
  window.setTimeout(start, 4000);
}());
