/* The map: Leaflet with OpenStreetMap tiles.
 *
 *   createMap(container, handlers) -> { kind, setData(data), invalidate(), destroy() }
 *
 * data = { center: point|null, points: [point], background: [{lat,lon}], fit: bool }
 * point = { key, name, lat, lon, weight (0..1), isNew, selected }
 * handlers = { onHover(point, clientX, clientY), onLeave(), onSelect(point) }
 *
 * If Leaflet did not load, `createMap` returns a placeholder that shows a message instead of a map.
 * The list, the settings and every number keep working without it - only the picture is missing.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ExplorerMap = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MIN_RADIUS = 5, MAX_RADIUS = 26;
  var COLOR_HOP = '#5b8def', COLOR_NEW = '#2fbf71', COLOR_SELECTED = '#f5a524',
      COLOR_HOME = '#e5484d', COLOR_REQUIRED = '#e5484d';

  function radiusFor(weight) {
    var w = (typeof weight === 'number' && isFinite(weight) && weight > 0) ? Math.min(1, weight) : 0;
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(w);
  }

  function hasLeaflet() {
    return !!(typeof window !== 'undefined' && window.L && typeof window.L.map === 'function');
  }

  // ---------------------------------------------------------------- Leaflet

  function LeafletMap(container, handlers) {
    this.container = container;
    this.handlers = handlers || {};
    this.map = window.L.map(container, {
      zoomControl: true, worldCopyJump: true, preferCanvas: true, attributionControl: true
    }).setView([51.5, 7.6], 5);
    // OpenStreetMap's tile policy requires visible attribution, so it stays - but small, dim and
    // without Leaflet's own advertising, which is optional.
    this.map.attributionControl.setPrefix('');
    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 12, attribution: '&copy; OSM'
    }).addTo(this.map);
    this.layer = window.L.layerGroup().addTo(this.map);
  }

  LeafletMap.prototype.kind = 'osm';

  LeafletMap.prototype.setData = function (data) {
    var self = this, L = window.L;
    this.layer.clearLayers();

    (data.background || []).forEach(function (city) {
      L.circleMarker([city.lat, city.lon], {
        radius: 1.5, stroke: false, fillColor: '#8b98a8', fillOpacity: .35, interactive: false
      }).addTo(self.layer);
    });

    if (data.center && !data.noLines) {
      data.points.forEach(function (point) {
        L.polyline([[data.center.lat, data.center.lon], [point.lat, point.lon]], {
          color: point.selected ? COLOR_SELECTED : COLOR_HOP, interactive: false,
          weight: 1 + 3 * Math.sqrt(Math.max(0, Math.min(1, point.weight))),
          opacity: point.selected ? .95 : .45
        }).addTo(self.layer);
      });
    }

    data.points.forEach(function (point) {
      var color = point.selected ? COLOR_SELECTED
        : (point.isRequired ? COLOR_REQUIRED : (point.isNew ? COLOR_NEW : COLOR_HOP));
      var marker = L.circleMarker([point.lat, point.lon], {
        radius: radiusFor(point.weight), color: color, weight: point.selected ? 3 : 1.6,
        fillColor: color, fillOpacity: .45
      }).addTo(self.layer);
      marker.on('mousemove', function (event) {
        if (self.handlers.onHover) self.handlers.onHover(point, event.originalEvent.clientX,
                                                         event.originalEvent.clientY);
      });
      marker.on('mouseout', function () { if (self.handlers.onLeave) self.handlers.onLeave(); });
      marker.on('click', function () { if (self.handlers.onSelect) self.handlers.onSelect(point); });
      marker.bindTooltip(point.name, { direction: 'top', opacity: .9 });
    });

    if (data.center) {
      L.circleMarker([data.center.lat, data.center.lon], {
        radius: 7, color: COLOR_HOME, weight: 3, fillColor: COLOR_HOME, fillOpacity: .85
      }).addTo(this.layer).bindTooltip(data.center.name, { permanent: true, direction: 'right' });
    }

    if (data.fit) {
      var bounds = data.points.map(function (p) { return [p.lat, p.lon]; });
      if (data.center) bounds.push([data.center.lat, data.center.lon]);
      if (bounds.length === 1) this.map.setView(bounds[0], 6);
      else if (bounds.length > 1) this.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 8 });
    }
  };

  LeafletMap.prototype.invalidate = function () { this.map.invalidateSize(); };

  LeafletMap.prototype.destroy = function () {
    this.map.remove();
    this.container.textContent = '';
  };

  // ---------------------------------------------------------------- placeholder

  /* Shown when Leaflet is unavailable.  It keeps the same interface so the rest of the page does
   * not need to know, and it never throws. */
  function MissingMap(container) {
    this.container = container;
    this.kind = 'none';
    container.textContent = '';
    this.node = document.createElement('div');
    this.node.className = 'map-missing';
    this.node.textContent = 'Karte nicht verfügbar (Leaflet konnte nicht geladen werden). '
      + 'Die Liste, die Einstellungen und alle Zahlen funktionieren weiterhin.';
    container.appendChild(this.node);
  }

  MissingMap.prototype.setData = function () {};
  MissingMap.prototype.invalidate = function () {};
  MissingMap.prototype.destroy = function () { this.container.textContent = ''; };

  function createMap(container, handlers) {
    container.textContent = '';
    if (!hasLeaflet()) return new MissingMap(container);
    try {
      return new LeafletMap(container, handlers);
    } catch (err) {
      container.textContent = '';
      return new MissingMap(container);
    }
  }

  return { createMap: createMap, radiusFor: radiusFor, hasLeaflet: hasLeaflet };
}));
