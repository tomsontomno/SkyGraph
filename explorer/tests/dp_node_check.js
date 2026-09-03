/* Node harness: run the browser DP on a bundle and print the numbers as JSON.
 *
 * Usage: node dp_node_check.js <request.json>
 * Request: {"bundle": <bundle>, "settings": {...city names...}, "path": [flight indices]}
 * Output:  {"oneWay":…, "roundTrip":…, "exact":true, "cities":[{"city","oneWay","roundTrip",
 *           "shareOneWay","shareRoundTrip","flights"}], "candidates":[flight indices]}
 *
 * explorer/tests/test_js.py compares this against explorer/dp.py on the same bundle.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const DP = require(path.join(__dirname, '..', 'static', 'dp.js'));

function main() {
  const requestPath = process.argv[2];
  if (!requestPath) throw new Error('usage: node dp_node_check.js <request.json>');
  const request = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
  // either a ready-made bundle, or a manifest plus day files the browser would assemble itself
  const bundle = request.bundle
    ? request.bundle
    : DP.bundleFromDays(request.manifest, request.days, request.firstFlightOnly === true);
  const net = DP.buildNetwork(bundle);
  const indexOf = new Map(bundle.cities.map((c, i) => [c.name, i]));

  const resolve = (name) => {
    if (!indexOf.has(name)) throw new Error('unknown city ' + name);
    return indexOf.get(name);
  };
  // A required city that is not in this scan keeps its own bit, which can never be set, so nothing
  // can satisfy it - exactly what explorer/dp.py does with such a name.
  let sentinel = bundle.cities.length;
  const resolveRequired = (name) => (indexOf.has(name) ? indexOf.get(name) : sentinel++);
  const s = request.settings;
  const settings = {
    startCities: new Set((s.startCities || []).map(resolve)),
    returnCities: new Set((s.returnCities || []).map(resolve)),
    requiredCities: new Set((s.requiredCities || []).map(resolveRequired)),
    requiredGroups: (s.requiredGroups || []).map((group) => new Set(group.map(resolveRequired))),
    minGapHours: s.minGapHours,
    maxGapHours: s.maxGapHours,
    maxFlights: (s.maxFlights === undefined || s.maxFlights === null) ? null : s.maxFlights,
    dailyCap: s.dailyCap,
    capMode: s.capMode,
    mode: s.mode || 'rt'
  };

  const counter = new DP.RouteCounter(net, settings);
  const requestedPath = request.path || [];
  const shares = counter.cityShares(requestedPath);
  const out = {
    within: (request.radius === undefined || request.radius === null) ? null
      : DP.citiesWithin(bundle.cities, resolve(request.radiusCenter), request.radius)
          .map((hit) => ({ city: bundle.cities[hit.index].name, km: hit.distance })),
    assembled: { scan: bundle.scan, days: bundle.days, flights: bundle.flights.length,
                 edges: bundle.stats.edges },
    countries: (bundle.countries || []).length,
    depths: shares.hops.reduce((acc, hop) => {
      acc[hop.flight.index] = hop.depth;
      return acc;
    }, {}),
    oneWay: shares.totalOneWay,
    roundTrip: shares.totalRoundTrip,
    exact: counter.exact,
    memo: counter.memo.size,
    candidates: counter.candidateIndices(requestedPath),
    cities: shares.cities
      .map((entry) => ({
        city: bundle.cities[entry.city].name,
        oneWay: entry.oneWay,
        roundTrip: entry.roundTrip,
        shareOneWay: entry.shareOneWay,
        shareRoundTrip: entry.shareRoundTrip,
        flights: entry.flights.map((h) => h.flight.index)
      }))
      .sort((a, b) => (a.city < b.city ? -1 : a.city > b.city ? 1 : 0))
  };
  process.stdout.write(JSON.stringify(out));
}

main();
