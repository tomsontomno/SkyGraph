/* Flight DAG + backward dynamic program - the browser twin of explorer/dp.py.
 *
 * Nodes are concrete flights, an edge f -> g means g departs from the city f arrives in with
 * arr(f) + minGap <= dep(g) <= arr(f) + maxGap.  That is the successor rule of
 * simulate/route_find_fixed.py with flex_km = 0.  Departures increase strictly along a path, so the
 * graph is acyclic and sorting by departure is a topological order.
 *
 * For a prefix P (route_find stores every valid prefix):
 *     oneWay(P)    = 1 + sum over legal next flights g of oneWay(P + g)
 *     roundTrip(P) = [last city of P is a return city] + sum over g of roundTrip(P + g)
 * memoised over (flight, cap state, remaining flights) - so no flight limit is needed.
 *
 * Booking cap, same rule as simulate/booking_cap.py:
 *   calendar : at most `cap` departures per local calendar day of the departure airport.
 *   rolling24: never cap + 1 departures inside a window shorter than 24 h.
 *
 * explorer/tests/test_js.py runs this file under node and compares it against explorer/dp.py.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ExplorerDP = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SECONDS_PER_DAY = 86400;
  var CAP_MODES = ['none', 'calendar', 'rolling24'];

  function lowerBound(sorted, value) {
    var lo = 0, hi = sorted.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < value) lo = mid + 1; else hi = mid; }
    return lo;
  }

  function upperBound(sorted, value) {
    var lo = 0, hi = sorted.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] <= value) lo = mid + 1; else hi = mid; }
    return lo;
  }

  /* Build the network from a bundle written by explorer/build.py.  Flight indices match the bundle,
   * and therefore explorer/dp.py's FlightNetwork. */
  function buildNetwork(bundle) {
    var flights = bundle.flights.map(function (row, i) {
      return { index: i, origin: row[0], dest: row[1], dep: row[2], arr: row[3],
               day: row[4], depLabel: row[5], arrLabel: row[6] };
    });
    for (var i = 1; i < flights.length; i++) {
      if (flights[i].dep < flights[i - 1].dep) throw new Error('bundle flights are not sorted by departure');
    }
    var byOrigin = new Map(), depByOrigin = new Map();
    flights.forEach(function (f) {
      if (!byOrigin.has(f.origin)) { byOrigin.set(f.origin, []); depByOrigin.set(f.origin, []); }
      byOrigin.get(f.origin).push(f.index);
      depByOrigin.get(f.origin).push(f.dep);
    });
    return { flights: flights, byOrigin: byOrigin, depByOrigin: depByOrigin, cities: bundle.cities };
  }

  /* Assemble a bundle from the archive manifest and the day files of one window.
   *
   * All day files share the manifest's city table, so merging is a concatenation.  `dayPayloads` are
   * the loaded day files in any order; the window's days are taken from them, sorted.  With
   * `firstFlightOnly` the result keeps just the earliest flight per route, which is the view the
   * buggy core/route_find.py had. */
  function bundleFromDays(manifest, dayPayloads, firstFlightOnly) {
    if (!dayPayloads || !dayPayloads.length) throw new Error('no days given');
    var dates = dayPayloads.map(function (d) { return d.date; }).sort();
    var dayIndex = new Map(dates.map(function (date, i) { return [date, i]; }));
    var rows = [];
    dayPayloads.forEach(function (payload) {
      payload.flights.forEach(function (row) {
        rows.push([row[0], row[1], row[2], row[3], dayIndex.get(row[4]), row[5], row[6]]);
      });
    });
    rows.sort(function (a, b) { return a[2] - b[2] || a[0] - b[0] || a[1] - b[1]; });
    if (firstFlightOnly) {
      var seen = new Set(), kept = [];
      rows.forEach(function (row) {
        var key = row[0] + '>' + row[1];
        if (seen.has(key)) return;
        seen.add(key);
        kept.push(row);
      });
      rows = kept;
    }
    var edges = new Set();
    rows.forEach(function (row) { edges.add(row[0] + '>' + row[1]); });
    return {
      scan: 'arch-' + dates[0] + '-' + dates.length + 'd' + (firstFlightOnly ? '-original' : ''),
      label: dates[0] + ' + ' + (dates.length - 1) + ' Tage aus dem Archiv'
             + (firstFlightOnly ? ' – Originalcode (nur je erster Flug)' : ' – Fix (alle Flüge)'),
      source: manifest.source,
      day0: dates[0],
      days: dates,
      cities: manifest.cities,
      countries: manifest.countries || [],
      flights: rows,
      stats: { cities: manifest.cities.length, edges: edges.size, flights: rows.length,
               invisibleFlights: rows.length - edges.size },
      defaultStart: manifest.defaultStart
    };
  }

  /* Flights leaving `city` (a city index) with lo <= dep <= hi, in departure order. */
  function departuresFrom(net, city, lo, hi) {
    var deps = net.depByOrigin.get(city);
    if (!deps) return [];
    return net.byOrigin.get(city).slice(lowerBound(deps, lo), upperBound(deps, hi));
  }

  function successors(net, minGapHours, maxGapHours) {
    var loOff = minGapHours * 3600, hiOff = maxGapHours * 3600;
    return net.flights.map(function (f) {
      return departuresFrom(net, f.dest, f.arr + loOff, f.arr + hiOff);
    });
  }

  /* State after appending `flight`, or null when the booking rule forbids it.
   * State shape: [] for none, [dayIndex, count] for calendar, ascending departure times for
   * rolling24 (exactly those inside the trailing 24 h window, at most `cap` of them). */
  function capAdvance(state, flight, cap, capMode) {
    if (capMode === 'none') return state;
    if (capMode === 'calendar') {
      if (state.length && state[0] === flight.day) {
        var count = state[1] + 1;
        return count > cap ? null : [flight.day, count];
      }
      return cap >= 1 ? [flight.day, 1] : null;
    }
    if (capMode === 'rolling24') {
      var cutoff = flight.dep - SECONDS_PER_DAY, window = [];
      for (var i = 0; i < state.length; i++) if (state[i] > cutoff) window.push(state[i]);
      if (window.length >= cap) return null;
      window.push(flight.dep);
      return window;
    }
    throw new Error('unknown cap mode ' + capMode);
  }

  function capStateOf(net, path, cap, capMode) {
    var state = [];
    for (var i = 0; i < path.length; i++) {
      state = capAdvance(state, net.flights[path[i]], cap, capMode);
      if (state === null) throw new Error('path violates the ' + capMode + ' cap of ' + cap);
    }
    return state;
  }

  var EARTH_DIAMETER_KM = 12742;

  /* Great-circle distance in km between two {lat, lon} points (mirror of coords.haversine_km). */
  function haversineKm(a, b) {
    var rad = Math.PI / 180;
    var h = 0.5 - Math.cos((b.lat - a.lat) * rad) / 2
          + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * (1 - Math.cos((b.lon - a.lon) * rad)) / 2;
    return EARTH_DIAMETER_KM * Math.asin(Math.sqrt(Math.max(0, Math.min(1, h))));
  }

  /* City indices within `radiusKm` of `centerIndex`, nearest first (the centre is always first).
   * This is how "one city plus a radius" becomes a set of start or return cities. */
  function citiesWithin(cities, centerIndex, radiusKm) {
    var center = cities[centerIndex];
    if (!center) throw new Error('unknown city index ' + centerIndex);
    if (!(radiusKm >= 0)) throw new Error('radius must be >= 0, got ' + radiusKm);
    var hits = [];
    for (var i = 0; i < cities.length; i++) {
      var distance = haversineKm(center, cities[i]);
      if (distance <= radiusKm) hits.push({ index: i, distance: distance });
    }
    hits.sort(function (a, b) { return a.distance - b.distance || a.index - b.index; });
    return hits;
  }

  function validateSettings(s) {
    if (!s.startCities || !s.startCities.size) throw new Error('startCities must not be empty');
    if (!(s.minGapHours >= 0) || !(s.maxGapHours > s.minGapHours)) {
      throw new Error('need 0 <= minGap < maxGap, got ' + s.minGapHours + '/' + s.maxGapHours);
    }
    if (s.maxFlights !== null && s.maxFlights !== undefined && s.maxFlights < 1) {
      throw new Error('maxFlights must be >= 1 or null, got ' + s.maxFlights);
    }
    if (CAP_MODES.indexOf(s.capMode) === -1) throw new Error('unknown cap mode ' + s.capMode);
    if (s.capMode !== 'none' && !(s.dailyCap >= 1)) throw new Error('dailyCap must be >= 1');
  }

  /* Backward DP for one settings object.  `settings.start` and `settings.returnCities` are city
   * indices / a Set of city indices; `maxFlights` null means no limit. */
  function RouteCounter(net, settings) {
    validateSettings(settings);
    this.net = net;
    this.settings = settings;
    this.succ = successors(net, settings.minGapHours, settings.maxGapHours);
    this.memo = new Map();
    this.depthMemo = new Map();
    // whether depthRange asks for a way home or accepts ending anywhere
    this.depthRoundTrip = settings.mode !== 'ow';
    this.exact = true;                       // false once a count exceeds 2^53 - 1
    this.maxFlights = (settings.maxFlights === undefined) ? null : settings.maxFlights;

    // every requirement is a group of cities of which one must be visited; a required city is a
    // group of size one, a required country is a group holding all its airports.
    var groups = Array.from(settings.requiredCities || [])
      .sort(function (a, b) { return a - b; })
      .map(function (city) { return [city]; })
      .concat((settings.requiredGroups || []).map(function (group) { return Array.from(group); }));
    this.groups = groups;
    this.required = groups;                     // truthy length means "something is required"
    this.bit = new Map();
    var self0 = this;
    groups.forEach(function (group, position) {
      group.forEach(function (city) {
        self0.bit.set(city, (self0.bit.get(city) || 0) | (1 << position));
      });
    });
    this.fullMask = (1 << groups.length) - 1;
    this.reach = new Array(net.flights.length).fill(0);
    if (this.required.length) {
      // successors always depart later, so descending departure order is a topological order
      var order = net.flights.map(function (f) { return f.index; })
        .sort(function (a, b) { return net.flights[b].dep - net.flights[a].dep; });
      for (var k = 0; k < order.length; k++) {
        var i = order[k], mask = this.bit.get(net.flights[i].dest) || 0, succ = this.succ[i];
        for (var s = 0; s < succ.length; s++) mask |= this.reach[succ[s]];
        this.reach[i] = mask;
      }
    }
  }

  RouteCounter.prototype.bitOf = function (city) { return this.bit.get(city) || 0; };

  /* Required cities already visited by `path` (its start city counts as visited). */
  RouteCounter.prototype.maskOf = function (path) {
    if (!this.required.length || !path.length) return 0;
    var mask = this.bitOf(this.net.flights[path[0]].origin);
    for (var i = 0; i < path.length; i++) mask |= this.bitOf(this.net.flights[path[i]].dest);
    return mask;
  };

  RouteCounter.prototype.value = function (index, capState, remaining, mask) {
    mask = mask || 0;
    var key = index + '|' + capState.join(',') + '|' + (remaining === null ? '*' : remaining) + '|' + mask;
    var hit = this.memo.get(key);
    if (hit !== undefined) return hit;
    // nothing below this flight can complete the requirement -> the whole subtree is worthless
    if (this.required.length && (mask | this.reach[index]) !== this.fullMask) {
      var zero = { oneWay: 0, roundTrip: 0 };
      this.memo.set(key, zero);
      return zero;
    }
    var flight = this.net.flights[index];
    var complete = mask === this.fullMask;
    var oneWay = complete ? 1 : 0;
    var roundTrip = (complete && this.settings.returnCities.has(flight.dest)) ? 1 : 0;
    if (remaining === null || remaining > 0) {
      var next = remaining === null ? null : remaining - 1;
      var succ = this.succ[index];
      for (var i = 0; i < succ.length; i++) {
        var target = this.net.flights[succ[i]];
        var state = capAdvance(capState, target, this.settings.dailyCap, this.settings.capMode);
        if (state === null) continue;
        var sub = this.value(succ[i], state, next, mask | this.bitOf(target.dest));
        oneWay += sub.oneWay;
        roundTrip += sub.roundTrip;
      }
    }
    if (oneWay > Number.MAX_SAFE_INTEGER) this.exact = false;
    var result = { oneWay: oneWay, roundTrip: roundTrip };
    this.memo.set(key, result);
    return result;
  };

  /* Flights that may extend `path`.  With an empty path: every flight out of the start city with no
   * time constraint, exactly like the start loop of find_one_way_routes. */
  RouteCounter.prototype.candidateIndices = function (path) {
    if (this.maxFlights !== null && path.length >= this.maxFlights) return [];
    if (!path.length) {
      var merged = [], self = this;
      this.settings.startCities.forEach(function (city) {
        merged = merged.concat(self.net.byOrigin.get(city) || []);
      });
      var flights = this.net.flights;
      return merged.sort(function (a, b) { return flights[a].dep - flights[b].dep || a - b; });
    }
    var last = this.net.flights[path[path.length - 1]];
    return departuresFrom(this.net, last.dest,
                          last.arr + this.settings.minGapHours * 3600,
                          last.arr + this.settings.maxGapHours * 3600);
  };

  /* Legal next flights with their route counts, in departure order. */
  RouteCounter.prototype.hops = function (path) {
    var state = capStateOf(this.net, path, this.settings.dailyCap, this.settings.capMode);
    var remaining = this.maxFlights === null ? null : this.maxFlights - path.length - 1;
    var baseMask = this.maskOf(path);
    var out = [], candidates = this.candidateIndices(path);
    for (var i = 0; i < candidates.length; i++) {
      var flight = this.net.flights[candidates[i]];
      var nextState = capAdvance(state, flight, this.settings.dailyCap, this.settings.capMode);
      if (nextState === null) continue;
      var mask = baseMask | this.bitOf(flight.dest);
      if (!path.length) mask |= this.bitOf(flight.origin);   // the route's own start counts as visited
      var depth = this.depthRange(candidates[i], nextState, remaining, mask);
      out.push({
        flight: flight,
        counts: this.value(candidates[i], nextState, remaining, mask),
        // total flights of the shortest and longest completing route through this hop
        depth: depth === null ? null : { min: path.length + depth.min, max: path.length + depth.max }
      });
    }
    return out;
  };

  /* How many more flights does a completing route need from here, at least and at most?
   *
   * Counts `index` itself, so a hop that already closes the trip returns {min: 1, max: 1}.  Returns
   * null when nothing below this flight can complete - the same subtree the counter values at zero.
   * `max` is finite because the graph is acyclic and the scan window is finite. */
  RouteCounter.prototype.depthRange = function (index, capState, remaining, mask) {
    mask = mask || 0;
    var key = index + '|' + capState.join(',') + '|' + (remaining === null ? '*' : remaining) + '|' + mask;
    var hit = this.depthMemo.get(key);
    if (hit !== undefined) return hit;
    var result = null;
    if (!this.required.length || (mask | this.reach[index]) === this.fullMask) {
      var flight = this.net.flights[index];
      if (mask === this.fullMask &&
          (!this.depthRoundTrip || this.settings.returnCities.has(flight.dest))) {
        result = { min: 1, max: 1 };
      }
      if (remaining === null || remaining > 0) {
        var next = remaining === null ? null : remaining - 1;
        var succ = this.succ[index];
        for (var i = 0; i < succ.length; i++) {
          var target = this.net.flights[succ[i]];
          var state = capAdvance(capState, target, this.settings.dailyCap, this.settings.capMode);
          if (state === null) continue;
          var sub = this.depthRange(succ[i], state, next, mask | this.bitOf(target.dest));
          if (sub === null) continue;
          if (result === null) result = { min: 1 + sub.min, max: 1 + sub.max };
          else {
            result.min = Math.min(result.min, 1 + sub.min);
            result.max = Math.max(result.max, 1 + sub.max);
          }
        }
      }
    }
    this.depthMemo.set(key, result);
    return result;
  };

  /* Is there at least one route at all?  Same rules as `value`, but it stops at the first hit
   * instead of counting, which is what the day slider needs for 150 windows in a row. */
  RouteCounter.prototype.hasAny = function (roundTripOnly) {
    var self = this;
    var seen = new Map();

    function walk(index, capState, remaining, mask) {
      var key = index + '|' + capState.join(',') + '|' + (remaining === null ? '*' : remaining) + '|' + mask;
      var hit = seen.get(key);
      if (hit !== undefined) return hit;
      if (self.required.length && (mask | self.reach[index]) !== self.fullMask) {
        seen.set(key, false);
        return false;
      }
      var flight = self.net.flights[index];
      if (mask === self.fullMask &&
          (!roundTripOnly || self.settings.returnCities.has(flight.dest))) {
        seen.set(key, true);
        return true;
      }
      seen.set(key, false);            // guards against re-entering while this branch is open
      var found = false;
      if (remaining === null || remaining > 0) {
        var next = remaining === null ? null : remaining - 1;
        var succ = self.succ[index];
        for (var i = 0; i < succ.length && !found; i++) {
          var target = self.net.flights[succ[i]];
          var state = capAdvance(capState, target, self.settings.dailyCap, self.settings.capMode);
          if (state === null) continue;
          found = walk(succ[i], state, next, mask | self.bitOf(target.dest));
        }
      }
      seen.set(key, found);
      return found;
    }

    var candidates = this.candidateIndices([]);
    var remaining = this.maxFlights === null ? null : this.maxFlights - 1;
    for (var i = 0; i < candidates.length; i++) {
      var flight = this.net.flights[candidates[i]];
      var state = capAdvance([], flight, this.settings.dailyCap, this.settings.capMode);
      if (state === null) continue;
      if (walk(candidates[i], state, remaining, this.bitOf(flight.origin) | this.bitOf(flight.dest))) {
        return true;
      }
    }
    return false;
  };

  RouteCounter.prototype.totals = function (path) {
    var hops = this.hops(path || []), oneWay = 0, roundTrip = 0;
    hops.forEach(function (h) { oneWay += h.counts.oneWay; roundTrip += h.counts.roundTrip; });
    return { oneWay: oneWay, roundTrip: roundTrip };
  };

  /* Per destination city of the next hop: its flights, counts and shares of all continuations.
   * The shares over all cities sum to 1 for each mode whose total is positive. */
  RouteCounter.prototype.cityShares = function (path) {
    var hops = this.hops(path || []);
    var totalOw = 0, totalRt = 0;
    hops.forEach(function (h) { totalOw += h.counts.oneWay; totalRt += h.counts.roundTrip; });
    var grouped = new Map();
    hops.forEach(function (h) {
      var entry = grouped.get(h.flight.dest);
      if (!entry) {
        entry = { city: h.flight.dest, flights: [], oneWay: 0, roundTrip: 0 };
        grouped.set(h.flight.dest, entry);
      }
      entry.flights.push(h);
      entry.oneWay += h.counts.oneWay;
      entry.roundTrip += h.counts.roundTrip;
      if (h.depth) {
        entry.minFlights = entry.minFlights === undefined ? h.depth.min : Math.min(entry.minFlights, h.depth.min);
        entry.maxFlights = entry.maxFlights === undefined ? h.depth.max : Math.max(entry.maxFlights, h.depth.max);
      }
    });
    grouped.forEach(function (entry) {
      entry.shareOneWay = totalOw ? entry.oneWay / totalOw : 0;
      entry.shareRoundTrip = totalRt ? entry.roundTrip / totalRt : 0;
    });
    return { cities: Array.from(grouped.values()), totalOneWay: totalOw, totalRoundTrip: totalRt,
             hops: hops };
  };

  return {
    SECONDS_PER_DAY: SECONDS_PER_DAY,
    CAP_MODES: CAP_MODES,
    buildNetwork: buildNetwork,
    bundleFromDays: bundleFromDays,
    departuresFrom: departuresFrom,
    successors: successors,
    capAdvance: capAdvance,
    capStateOf: capStateOf,
    haversineKm: haversineKm,
    citiesWithin: citiesWithin,
    RouteCounter: RouteCounter
  };
}));
