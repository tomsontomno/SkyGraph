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
    departureCities: new Set(), resolved: null, required: [], requiredCountries: [],
    tab: 'hop', tabBeforePick: 'milestones', pickMode: false,
    manifest: null, dayCache: new Map(), archiveToken: 0,
    allStarts: [], feasibleStarts: null, scanToken: 0, daysPreloaded: false
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

  var WEEKDAYS = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
  var PRICE_PER_FLIGHT = 9.99;

  /* "Di 17.12.2024" from an ISO date, computed from the parts so no timezone can shift the day. */
  function fmtDate(isoDate) {
    var parts = isoDate.split('-').map(Number);
    var weekday = WEEKDAYS[new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])).getUTCDay()];
    return weekday + ' ' + String(parts[2]).padStart(2, '0') + '.' +
           String(parts[1]).padStart(2, '0') + '.' + parts[0];
  }

  /* Hours between two epoch seconds, e.g. "8,5 h".  Epochs are absolute, so this is already free of
   * any timezone question - a layover in Larnaca counts the real waiting time, not the clock jump. */
  function fmtHours(seconds) {
    var hours = seconds / 3600;
    return hours.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' h';
  }

  function fmtPrice(flights) {
    return (flights * PRICE_PER_FLIGHT).toLocaleString('de-DE',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';
  }

  function cityRecord(index) { return state.bundle.cities[index]; }
  function cityName(index) { return state.bundle.cities[index].name; }

  function isNewCountry(cityIndex) { return cityRecord(cityIndex).countryNew === true; }

  function isRequired(cityIndex) {
    if (state.required.indexOf(cityName(cityIndex)) !== -1) return true;
    var country = cityRecord(cityIndex).country;
    return !!country && state.requiredCountries.indexOf(country) !== -1;
  }

  function countries() { return state.bundle.countries || []; }

  function requirementCount() { return state.required.length + state.requiredCountries.length; }

  function countryByName(name) {
    return countries().filter(function (c) { return c.name === name; })[0] || null;
  }

  function countryLabel(name) {
    var country = countryByName(name);
    return country ? country.de : name;
  }

  /* Adding a country removes the cities it already covers - naming both would be redundant. */
  function addRequiredCountry(name) {
    if (state.requiredCountries.indexOf(name) !== -1) return;
    var country = countryByName(name);
    if (!country) return;
    var covered = new Set(country.cities.map(cityName));
    state.required = state.required.filter(function (city) { return !covered.has(city); });
    state.requiredCountries = state.requiredCountries.concat([name]);
    recompute(false);
  }

  function cityCoveredByCountry(name) {
    var record = state.bundle.cities.filter(function (c) { return c.name === name; })[0];
    return !!(record && record.country && state.requiredCountries.indexOf(record.country) !== -1);
  }

  function addRequiredCity(name) {
    if (!name || state.required.indexOf(name) !== -1 || cityCoveredByCountry(name)) return;
    state.required = state.required.concat([name]);
    recompute(false);
  }

  function removeRequirement(kind, name) {
    if (kind === 'country') {
      state.requiredCountries = state.requiredCountries.filter(function (o) { return o !== name; });
    } else {
      state.required = state.required.filter(function (o) { return o !== name; });
    }
    recompute(false);
  }

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
      // one group per required country: any airport in it satisfies the requirement
      requiredGroups: state.requiredCountries.map(function (name) {
        var country = countryByName(name);
        return new Set(country ? country.cities : []);
      }),
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
        if (state.manifest && els.scanSelect.value === ARCHIVE_SCAN) preloadDays();
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

  /* In round-trip mode a city you cannot get home from is not an option, so it is dropped rather
   * than drawn as a zero-sized dot.  In one-way mode every reachable city stays. */
  function visibleEntries() {
    if (state.settings.mode !== 'rt') return state.shares.cities;
    return state.shares.cities.filter(function (entry) { return entry.roundTrip > 0; });
  }

  /* The flights of one city, in round-trip mode only those you can still come home from. */
  function visibleHops(entry) {
    var hops = entry.flights;
    if (state.settings.mode === 'rt') {
      hops = hops.filter(function (hop) { return hop.counts.roundTrip > 0; });
    }
    return hops.slice().sort(function (a, b) { return a.flight.dep - b.flight.dep; });
  }

  /* "4 bis 9 Flüge" - the shortest and longest completing route through this hop, with its price. */
  function depthText(entry) {
    if (entry.minFlights === undefined) return 'keine vollständige Route';
    if (entry.minFlights === entry.maxFlights) {
      return entry.minFlights + (entry.minFlights === 1 ? ' Flug' : ' Flüge')
        + ' · ' + fmtPrice(entry.minFlights);
    }
    return entry.minFlights + ' bis ' + entry.maxFlights + ' Flüge · '
      + fmtPrice(entry.minFlights) + ' bis ' + fmtPrice(entry.maxFlights);
  }

  function hopDepthText(hop) {
    if (!hop.depth) return 'keine vollständige Route';
    if (hop.depth.min === hop.depth.max) {
      return hop.depth.min + (hop.depth.min === 1 ? ' Flug' : ' Flüge') + ' · ' + fmtPrice(hop.depth.min);
    }
    return hop.depth.min + ' bis ' + hop.depth.max + ' Flüge · '
      + fmtPrice(hop.depth.min) + ' bis ' + fmtPrice(hop.depth.max);
  }

  function sortedEntries() {
    return visibleEntries().slice().sort(function (a, b) {
      var d = weightOf(b) - weightOf(a);
      return d !== 0 ? d : (cityName(a.city) < cityName(b.city) ? -1 : 1);
    });
  }

  /* The required cities as removable chips.  A chip turns red once no continuation can still
   * reach it, which is the fastest way to see that a wish is impossible from here. */
  function renderRequiredChips() {
    els.requiredChips.textContent = '';
    var entries = state.requiredCountries.map(function (name) { return { kind: 'country', name: name }; })
      .concat(state.required.map(function (name) { return { kind: 'city', name: name }; }));
    if (!entries.length) {
      var hint = document.createElement('span');
      hint.className = 'empty';
      hint.textContent = 'nichts gewählt – alle Routen zählen';
      els.requiredChips.appendChild(hint);
      return;
    }
    var impossible = state.shares && state.shares.totalOneWay === 0 && state.shares.totalRoundTrip === 0;
    entries.forEach(function (entry) {
      var chip = document.createElement('span');
      chip.className = 'chip' + (entry.kind === 'country' ? ' country' : '') +
                       (impossible ? ' unreachable' : '');
      chip.appendChild(document.createTextNode(
        entry.kind === 'country' ? countryLabel(entry.name) : entry.name));
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.title = 'entfernen';
      remove.addEventListener('click', function () { removeRequirement(entry.kind, entry.name); });
      chip.appendChild(remove);
      els.requiredChips.appendChild(chip);
    });
  }

  /* Search over countries and cities at once; countries first because they are the wider wish. */
  function renderMilestoneResults() {
    var query = (els.milestoneSearch.value || '').trim().toLowerCase();
    var rows = [];
    countries().forEach(function (country) {
      if (query && country.de.toLowerCase().indexOf(query) === -1 &&
          country.name.toLowerCase().indexOf(query) === -1) return;
      rows.push({ kind: 'country', name: country.name, label: country.de,
                  note: country.cities.length + (country.cities.length === 1 ? ' Stadt' : ' Städte') +
                        (country.new ? ' · neu' : ''),
                  chosen: state.requiredCountries.indexOf(country.name) !== -1 });
    });
    state.bundle.cities.forEach(function (city) {
      if (query && city.name.toLowerCase().indexOf(query) === -1) return;
      var covered = cityCoveredByCountry(city.name);
      rows.push({ kind: 'city', name: city.name, label: city.name,
                  note: covered ? 'durch Land abgedeckt' : (city.countryNew ? 'neues Land' : ''),
                  chosen: covered || state.required.indexOf(city.name) !== -1 });
    });
    els.milestoneResults.textContent = '';
    if (!rows.length) {
      var empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = 'nichts gefunden';
      els.milestoneResults.appendChild(empty);
      return;
    }
    rows.slice(0, 60).forEach(function (row) {
      var li = document.createElement('li');
      li.className = row.chosen ? 'chosen' : '';
      li.innerHTML = '<span class="kind ' + row.kind + '">' +
          (row.kind === 'country' ? 'Land' : 'Stadt') + '</span>' +
        '<span class="label2">' + escapeHtml(row.label) + '</span>' +
        '<span class="note">' + escapeHtml(row.note) + '</span>';
      if (!row.chosen) {
        li.addEventListener('click', function () {
          if (row.kind === 'country') addRequiredCountry(row.name);
          else addRequiredCity(row.name);
        });
      }
      els.milestoneResults.appendChild(li);
    });
  }

  function render(refit) {
    renderRequiredChips();
    renderMilestoneResults();
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
    var pills = [
      'ab <b>' + escapeHtml(cityName(currentCityIndex())) + '</b>',
      '<b>' + fmtInt(totals.totalOneWay) + '</b> One-way',
      '<b>' + fmtInt(totals.totalRoundTrip) + '</b> Rundreisen'
    ];
    if (!state.counter.exact) pills.push('<b>Zahlen gerundet</b>');
    els.totals.innerHTML = pills.map(function (text) {
      return '<span class="pill">' + text + '</span>';
    }).join(' ');
  }

  function renderMap(refit) {
    var center = cityRecord(currentCityIndex());
    if (state.pickMode) {
      state.map.setData({
        center: { name: center.name, lat: center.lat, lon: center.lon },
        points: state.bundle.cities.map(function (record, index) {
          return { key: index, name: record.name, lat: record.lat, lon: record.lon,
                   weight: isRequired(index) ? 1 : 0, isNew: false, isRequired: isRequired(index),
                   selected: false, entry: null };
        }),
        background: [], fit: refit !== false, noLines: true
      });
      return;
    }
    var points = visibleEntries().map(function (entry) {
      var record = cityRecord(entry.city);
      return {
        key: entry.city, name: record.name, lat: record.lat, lon: record.lon,
        weight: weightOf(entry),
        isNew: state.settings.highlightNew && isNewCountry(entry.city),
        isRequired: isRequired(entry.city),
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
    if (requirementCount() && state.shares.totalOneWay === 0) {
      els.detailHint.textContent = 'Keine einzige Route erfüllt alle ' + requirementCount() +
        ' Meilensteine gleichzeitig. Entferne welche, oder erhöhe max. Gap und Tage.';
      return;
    }
    if (!entries.length) {
      var dead = state.settings.mode === 'rt' && state.shares.cities.length > 0;
      els.detailHint.textContent = dead
        ? 'Von hier kommst du nicht mehr nach Hause. ' + state.shares.cities.length +
          ' Städte wären noch erreichbar, aber ohne Rückweg – auf One-way umschalten, um sie zu sehen.'
        : 'Von hier führt kein Flug weiter – zurückgehen oder Einstellungen lockern.';
      return;
    }
    var hidden = state.shares.cities.length - entries.length;
    if (requirementCount() && state.shares.totalOneWay === 0) {
      els.detailHint.textContent = 'Keine einzige Route erfüllt alle ' + requirementCount() +
        ' Meilensteine gleichzeitig. Entferne welche, oder erhöhe max. Gap und Tage.';
      return;
    }
    els.detailHint.textContent = 'Größe = Anteil der Vollrouten über diesen Hop (' +
      (state.settings.mode === 'rt' ? 'Rundreise' : 'One-way') + ')' +
      (state.required.length ? ', gezählt werden nur Routen über ' + state.required.join(', ') : '') + '.' +
      (hidden > 0 ? ' ' + hidden + ' Städte ohne Rückweg sind ausgeblendet.' : '');
    entries.forEach(function (entry) {
      var li = document.createElement('li');
      li.className = (isRequired(entry.city) ? 'is-required ' : '') +
                     (state.settings.highlightNew && isNewCountry(entry.city) ? 'is-new' : '') +
                     (state.selectedCity === entry.city ? ' selected' : '');
      var weight = weightOf(entry);
      li.innerHTML =
        '<span class="row1">' +
          '<span class="name">' + escapeHtml(cityName(entry.city)) + '</span>' +
          '<span class="bar"><i style="width:' + (Math.min(1, weight) * 100).toFixed(1) + '%"></i></span>' +
          '<span class="share">' + fmtPct(weight) + '</span>' +
        '</span>' +
        '<span class="row2">' + escapeHtml(depthText(entry)) + ' · ' +
          fmtInt(state.settings.mode === 'rt' ? entry.roundTrip : entry.oneWay) + ' Routen</span>';
      li.addEventListener('click', function () { selectCity(entry.city); });
      li.addEventListener('mousemove', function (ev) { showTooltip(entry, ev.clientX, ev.clientY); });
      li.addEventListener('mouseleave', hideTooltip);
      els.cityList.appendChild(li);
    });
  }

  function renderFlightList(cityIndex) {
    var entry = state.shares.cities.filter(function (c) { return c.city === cityIndex; })[0];
    if (!entry) { showCityList(); return; }
    var roundTrip = state.settings.mode === 'rt';
    var total = roundTrip ? state.shares.totalRoundTrip : state.shares.totalOneWay;
    var cityCount = roundTrip ? entry.roundTrip : entry.oneWay;
    els.detailTitle.innerHTML = 'Flüge nach <b>' + escapeHtml(cityName(cityIndex)) + '</b>' +
      ' · <b>' + fmtPct(total ? cityCount / total : 0) + '</b> aller Optionen von hier' +
      '<span class="sub">' + escapeHtml(depthText(entry)) + '</span>';
    els.cityList.hidden = true;
    els.detailHint.hidden = true;
    els.flightWrap.hidden = false;
    els.flightList.textContent = '';
    visibleHops(entry).forEach(function (hop) {
      var li = document.createElement('li');
      var count = roundTrip ? hop.counts.roundTrip : hop.counts.oneWay;
      li.innerHTML =
        '<span class="row1">' +
          '<span class="time">' + escapeHtml(hop.flight.depLabel) + ' → ' +
            escapeHtml(hop.flight.arrLabel) + '</span>' +
          '<span class="share">' + fmtPct(cityCount ? count / cityCount : 0) + '</span>' +
        '</span>' +
        '<span class="row2">' + escapeHtml(hopDepthText(hop)) + ' · ' + fmtInt(count) + ' Routen · ' +
          fmtPct(total ? count / total : 0) + ' von allen</span>';
      li.addEventListener('click', function () { pushHop(hop.flight.index); });
      els.flightList.appendChild(li);
    });
  }

  function showCityList() {
    els.detailTitle.textContent = '';
    els.cityList.hidden = false;
    els.detailHint.hidden = false;
    els.flightWrap.hidden = true;
  }

  function renderBreadcrumb() {
    els.breadcrumb.textContent = breadcrumbText();
    els.price.textContent = state.path.length
      ? state.path.length + (state.path.length === 1 ? ' Flug · ' : ' Flüge · ') + fmtPrice(state.path.length)
      : '';
    fitBreadcrumb();
    els.backBtn.disabled = state.path.length === 0;
    els.resetBtn.disabled = state.path.length === 0;
  }

  /* Shrink the route line until it fits on one line, down to a floor where it starts scrolling. */
  function fitBreadcrumb() {
    var size = 12;
    els.breadcrumb.style.fontSize = size + 'px';
    if (!els.crumbs.getBoundingClientRect) return;
    var available = els.crumbs.getBoundingClientRect().width;
    if (!available) return;
    while (size > 8 && els.breadcrumb.scrollWidth > available) {
      size -= 0.5;
      els.breadcrumb.style.fontSize = size + 'px';
    }
  }

  /* Light format of core/route_find.py: first city with its departure, every intermediate city with
   * the next departure, the last city with its arrival. */
  function breadcrumbText() {
    if (!state.path.length) {
      var extra = state.settings.startCities.size - 1;
      return cityName(state.settings.startCenter) + (extra > 0 ? ' (+' + extra + ' im Umkreis)' : '');
    }
    var flights = state.path.map(function (i) { return state.net.flights[i]; });
    var parts = [cityName(flights[0].origin) + ' ' + flights[0].depLabel];
    flights.forEach(function (flight, i) {
      if (i < flights.length - 1) {
        // layover: arrival here until the next departure, in absolute time
        parts.push(cityName(flight.dest) + ' ' + fmtHours(flights[i + 1].dep - flight.arr));
      } else {
        parts.push(cityName(flight.dest) + ' ' + flight.arrLabel);
      }
    });
    return parts.join(' → ');
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
      '<dt>Flüge</dt><dd>' + visibleHops(entry).length + '</dd>' +
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
    state.map = MAPS.createMap(els.map, {
      onHover: function (point, x, y) { if (point.entry) showTooltip(point.entry, x, y); },
      onLeave: hideTooltip,
      onSelect: function (point) {
        if (!state.pickMode) { selectCity(point.key); return; }
        var name = cityName(point.key);
        if (state.required.indexOf(name) !== -1) removeRequirement('city', name);
        else if (!cityCoveredByCountry(name)) addRequiredCity(name);
      }
    });
    state.mapKind = state.map.kind;
    // the note is only for failures; the tile attribution lives in Leaflet's own control
    els.mapNote.textContent = '';
  }

  /* Two tabs in the sidebar: the hop list and the settings. */
  function showTab(name) {
    state.tab = name;
    els.hopPanel.hidden = name !== 'hop';
    els.milestonesPanel.hidden = name !== 'milestones';
    els.settingsPanel.hidden = name !== 'settings';
    els.tabHop.className = 'tab' + (name === 'hop' ? ' active' : '');
    els.tabMilestones.className = 'tab' + (name === 'milestones' ? ' active' : '');
    els.tabSettings.className = 'tab' + (name === 'settings' ? ' active' : '');
    els.panelToggle.className = 'icon-btn' + (name === 'settings' ? ' active' : '');
    if (state.map) state.map.invalidate();
  }

  /* Pick milestones straight off the map.  The route is never touched, so leaving the mode puts
   * you back exactly where you were. */
  function setPickMode(on) {
    if (on === state.pickMode) return;
    if (on) state.tabBeforePick = state.tab;
    state.pickMode = on;
    els.pickToggle.className = 'mini pick' + (on ? ' active' : '');
    els.pickToggle.textContent = on ? 'Fertig – zurück zur Route' : 'Auf der Karte auswählen';
    els.pickBanner.hidden = !on;
    hideTooltip();
    showTab(on ? 'milestones' : state.tabBeforePick);
    renderMap(on);
  }

  function populateCitySelects() {
    var bundle = state.bundle;
    state.departureCities = new Set(bundle.flights.map(function (f) { return f[0]; }));
    state.required = state.required.filter(function (name) {
      return bundle.cities.some(function (city) { return city.name === name; });
    });
    state.requiredCountries = state.requiredCountries.filter(function (name) {
      return (bundle.countries || []).some(function (country) { return country.name === name; });
    });
    [els.startSelect, els.returnSelect].forEach(function (select) {
      select.textContent = '';
      bundle.cities.forEach(function (city, index) {
        var option = document.createElement('option');
        option.value = city.name;
        // only the start city needs the warning; for a stopover or a destination it means nothing
        var noDepartures = select === els.startSelect && !state.departureCities.has(index);
        option.textContent = city.name + (noDepartures ? ' – keine Abflüge' : '');
        select.appendChild(option);
      });
      select.value = bundle.defaultStart;
      if (!select.value && select.options.length) select.selectedIndex = 0;
    });
  }

  function copyStartToReturn() {
    els.returnSelect.value = els.startSelect.value;
    els.returnRadius.value = els.startRadius.value;
  }

  // ---------------------------------------------------------------- archive windows

  /* The window the slider currently selects: as many consecutive days as the length asks for,
   * clamped to the end of the archive. */
  function windowLength() {
    return Math.max(1, parseInt(els.archiveLength.value, 10) || 4);
  }

  /* Start indices of every window whose days are calendar-consecutive and all in the archive. */
  function allWindowStarts() {
    var days = state.manifest.days, length = windowLength(), out = [];
    for (var i = 0; i + length <= days.length; i++) {
      var first = Date.parse(days[i].date), last = Date.parse(days[i + length - 1].date);
      if (last - first === (length - 1) * 86400000) out.push(i);
    }
    return out;
  }

  /* The starts the slider may land on: the feasible ones once the scan is done, all of them
   * while it is still running. */
  function usableStarts() {
    if (state.feasibleStarts && state.feasibleStarts.length) return state.feasibleStarts;
    return state.allStarts.length ? state.allStarts : [0];
  }

  function archiveWindow() {
    var starts = usableStarts();
    var slot = Math.min(Math.max(0, parseInt(els.archiveDay.value, 10) || 0), starts.length - 1);
    return state.manifest.days.slice(starts[slot], starts[slot] + windowLength());
  }

  function syncSlider(keepDate) {
    var starts = usableStarts();
    els.archiveDay.max = String(Math.max(0, starts.length - 1));
    if (keepDate) {
      var wanted = starts.map(function (i) { return state.manifest.days[i].date; }).indexOf(keepDate);
      if (wanted === -1) {                       // the day dropped out: take the nearest one that stayed
        var target = state.manifest.days.map(function (d) { return d.date; }).indexOf(keepDate);
        var best = 0, bestDistance = Infinity;
        starts.forEach(function (index, slot) {
          var distance = Math.abs(index - target);
          if (distance < bestDistance) { bestDistance = distance; best = slot; }
        });
        wanted = best;
      }
      els.archiveDay.value = String(wanted);
    }
  }

  /* Walk every window and ask "is there any route at all under the current settings".  Runs in
   * chunks so the page stays responsive, and a token drops the results of an outdated scan. */
  function scanDays() {
    if (!state.manifest) return;
    var token = ++state.scanToken;
    state.allStarts = allWindowStarts();
    state.feasibleStarts = null;
    var settings = state.settings;
    var roundTrip = settings.mode === 'rt';
    var starts = state.allStarts.slice();
    var found = [], at = 0;
    var length = windowLength();

    function step() {
      if (token !== state.scanToken) return;
      var deadline = Date.now() + 40;
      while (at < starts.length && Date.now() < deadline) {
        var days = state.manifest.days.slice(starts[at], starts[at] + length);
        var payloads = days.map(function (day) { return state.dayCache.get(day.date); });
        if (payloads.some(function (payload) { return !payload; })) { at++; continue; }
        var bundle = DP.bundleFromDays(state.manifest, payloads, els.archiveOriginal.checked);
        var counter = new DP.RouteCounter(DP.buildNetwork(bundle), settingsForBundle(bundle, settings));
        if (counter.hasAny(roundTrip)) found.push(starts[at]);
        at++;
      }
      els.dayNote.textContent = at < starts.length
        ? 'prüfe Tage … ' + at + '/' + starts.length
        : found.length + ' von ' + starts.length + ' Fenstern mit Route';
      if (at < starts.length) { window.setTimeout(step, 0); return; }
      if (!found.length) {
        els.dayNote.textContent = 'kein Fenster erfüllt diese Einstellungen';
        state.feasibleStarts = null;
        syncSlider(null);
        return;
      }
      var current = archiveWindow()[0].date;
      state.feasibleStarts = found;
      syncSlider(current);
      if (found.indexOf(state.manifest.days.map(function (d) { return d.date; }).indexOf(current)) === -1) {
        loadArchiveWindow();
      }
    }

    els.dayNote.textContent = 'prüfe Tage …';
    window.setTimeout(step, 0);
  }

  /* Every archive window shares the manifest's city table, so a city index means the same city in
   * all of them and the settings can be reused unchanged - including the required groups. */
  function settingsForBundle(bundle, settings) {
    return settings;
  }

  /* Fetch every archive day once, then re-scan.  The download happens on the first call only, the
   * scan on every call - otherwise a changed setting would keep showing the previous verdict. */
  function preloadDays() {
    if (!state.manifest) return Promise.resolve();
    if (state.daysPreloaded) {
      if (state.settings) scanDays();
      return Promise.resolve();
    }
    state.daysPreloaded = true;
    return Promise.all(state.manifest.days.map(fetchDay)).then(function () {
      if (state.settings) scanDays();
    }).catch(function (err) {
      state.daysPreloaded = false;
      els.dayNote.textContent = 'Tagesprüfung nicht möglich: ' + err.message;
    });
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
    els.archiveLabel.textContent = fmtDate(window_[0].date) + ' – ' +
      fmtDate(window_[window_.length - 1].date) +
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
    if (scan !== ARCHIVE_SCAN) els.dayNote.textContent = '';
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
    els.milestoneSearch.addEventListener('input', renderMilestoneResults);
    els.pickToggle.addEventListener('click', function () { setPickMode(!state.pickMode); });
    els.tabMilestones.addEventListener('click', function () { showTab('milestones'); });
    els.panelToggle.addEventListener('click', function () {
      showTab(state.tab === 'settings' ? 'hop' : 'settings');
    });
    els.tabHop.addEventListener('click', function () { showTab('hop'); });
    els.tabSettings.addEventListener('click', function () { showTab('settings'); });
    els.archiveDay.addEventListener('input', loadArchiveWindow);
    els.archiveLength.addEventListener('change', function () {
      state.feasibleStarts = null;
      state.allStarts = allWindowStarts();
      syncSlider(null);
      loadArchiveWindow();
    });
    els.archiveOriginal.addEventListener('change', loadArchiveWindow);
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
      minGap: $('min-gap'), maxGap: $('max-gap'),
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
      requiredChips: $('required-chips'), panelToggle: $('panel-toggle'),
      milestonesPanel: $('milestones-panel'), tabMilestones: $('tab-milestones'),
      milestoneSearch: $('milestone-search'), milestoneResults: $('milestone-results'),
      pickToggle: $('pick-toggle'), pickBanner: $('pick-banner'),
      settingsPanel: $('settings-panel'), sidebar: $('sidebar'), hopPanel: $('hop-panel'),
      tabHop: $('tab-hop'), tabSettings: $('tab-settings'), crumbs: $('crumbs'), price: $('price'),
      dayNote: $('day-note')
    };
    createMap();
    showTab('hop');
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
          state.allStarts = allWindowStarts();
          els.archiveDay.max = String(Math.max(0, state.allStarts.length - 1));
          // open on the densest window so the slider starts somewhere worth looking at
          var best = 0, bestCount = -1;
          state.allStarts.forEach(function (index, slot) {
            var sum = state.manifest.days.slice(index, index + 4)
              .reduce(function (acc, d) { return acc + d.flights; }, 0);
            if (sum > bestCount) { bestCount = sum; best = slot; }
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
        var chosen = known ? wanted
          : ((state.manifest && state.manifest.days.length) ? ARCHIVE_SCAN : index.scans[0].scan);
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
