/* Two interchangeable map renderers behind one interface.
 *
 *   createMap(container, handlers) -> { kind, setData(data), invalidate(), destroy() }
 *
 * "osm"  uses Leaflet with OpenStreetMap tiles when the library actually loaded.
 * "svg"  draws its own Web-Mercator SVG - graticule, every city of the scan as a faint dot for
 *        orientation, the hop lines and the reachable cities - and needs no network at all.
 *
 * data = { center: point|null, points: [point], background: [{lat,lon}], fit: bool }
 * point = { key, name, lat, lon, weight (0..1), isNew, selected }
 * handlers = { onHover(point, clientX, clientY), onLeave(), onSelect(point) }
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ExplorerMap = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MIN_RADIUS = 4, MAX_RADIUS = 26;

  function radiusFor(weight) {
    var w = (typeof weight === 'number' && isFinite(weight) && weight > 0) ? Math.min(1, weight) : 0;
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(w);
  }

  /* Normalised Web Mercator: x, y in [0, 1]. */
  function project(lat, lon) {
    var clamped = Math.max(-85.05, Math.min(85.05, lat));
    var s = Math.sin(clamped * Math.PI / 180);
    return { x: (lon + 180) / 360, y: 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI) };
  }

  function svgEl(name, attrs) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', name);
    if (attrs) Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  // ---------------------------------------------------------------- SVG renderer

  function SvgMap(container, handlers) {
    this.container = container;
    this.handlers = handlers || {};
    this.data = { center: null, points: [], background: [], fit: true };
    this.view = { cx: 0.5, cy: 0.35, scale: 900 };
    this.svg = svgEl('svg', { class: 'map-svg' });
    this.layers = {};
    ['grid', 'background', 'lines', 'points', 'labels'].forEach(function (name) {
      this.layers[name] = svgEl('g', { class: 'layer-' + name });
      this.svg.appendChild(this.layers[name]);
    }, this);
    container.appendChild(this.svg);
    this._bindPanZoom();
    this._onResize = this.invalidate.bind(this);
    window.addEventListener('resize', this._onResize);
  }

  SvgMap.prototype.kind = 'svg';

  SvgMap.prototype._size = function () {
    var rect = this.container.getBoundingClientRect();
    return { w: Math.max(240, rect.width), h: Math.max(200, rect.height) };
  };

  SvgMap.prototype._toScreen = function (lat, lon, size) {
    var p = project(lat, lon);
    return { x: (p.x - this.view.cx) * this.view.scale + size.w / 2,
             y: (p.y - this.view.cy) * this.view.scale + size.h / 2 };
  };

  SvgMap.prototype._bindPanZoom = function () {
    var self = this, dragging = null;
    this.svg.addEventListener('mousedown', function (ev) {
      if (ev.button !== 0) return;
      dragging = { x: ev.clientX, y: ev.clientY, cx: self.view.cx, cy: self.view.cy };
      self.svg.classList.add('dragging');
    });
    window.addEventListener('mousemove', function (ev) {
      if (!dragging) return;
      self.view.cx = dragging.cx - (ev.clientX - dragging.x) / self.view.scale;
      self.view.cy = dragging.cy - (ev.clientY - dragging.y) / self.view.scale;
      self._draw();
    });
    window.addEventListener('mouseup', function () {
      dragging = null;
      self.svg.classList.remove('dragging');
    });
    this.svg.addEventListener('wheel', function (ev) {
      ev.preventDefault();
      var size = self._size();
      var rect = self.svg.getBoundingClientRect();
      var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      var beforeX = (mx - size.w / 2) / self.view.scale + self.view.cx;
      var beforeY = (my - size.h / 2) / self.view.scale + self.view.cy;
      var factor = Math.exp(-ev.deltaY * 0.0015);
      self.view.scale = Math.max(120, Math.min(60000, self.view.scale * factor));
      self.view.cx = beforeX - (mx - size.w / 2) / self.view.scale;
      self.view.cy = beforeY - (my - size.h / 2) / self.view.scale;
      self._draw();
    }, { passive: false });
  };

  SvgMap.prototype._fit = function () {
    var pts = this.data.points.slice();
    if (this.data.center) pts.push(this.data.center);
    if (!pts.length) return;
    var size = this._size(), pad = 60;
    var xs = [], ys = [];
    pts.forEach(function (p) { var q = project(p.lat, p.lon); xs.push(q.x); ys.push(q.y); });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var dx = Math.max(maxX - minX, 1e-4), dy = Math.max(maxY - minY, 1e-4);
    this.view.scale = Math.max(120, Math.min(20000,
      Math.min((size.w - 2 * pad) / dx, (size.h - 2 * pad) / dy)));
    this.view.cx = (minX + maxX) / 2;
    this.view.cy = (minY + maxY) / 2;
  };

  SvgMap.prototype.setData = function (data) {
    this.data = data;
    if (data.fit) this._fit();
    this._draw();
  };

  SvgMap.prototype.invalidate = function () { this._draw(); };

  SvgMap.prototype._draw = function () {
    var self = this, size = this._size();
    this.svg.setAttribute('viewBox', '0 0 ' + size.w + ' ' + size.h);
    Object.keys(this.layers).forEach(function (name) { self.layers[name].textContent = ''; });

    // graticule every 10 degrees, labelled where it meets the frame
    for (var lon = -180; lon <= 180; lon += 10) {
      var a = this._toScreen(85, lon, size), b = this._toScreen(-85, lon, size);
      if (a.x < -20 || a.x > size.w + 20) continue;
      this.layers.grid.appendChild(svgEl('line', { x1: a.x, y1: Math.max(0, a.y), x2: b.x,
                                                   y2: Math.min(size.h, b.y), class: 'grid-line' }));
      this.layers.grid.appendChild(svgEl('text', { x: a.x + 3, y: 12, class: 'grid-label' }))
        .textContent = lon + '°';
    }
    for (var lat = -80; lat <= 80; lat += 10) {
      var p = this._toScreen(lat, 0, size);
      if (p.y < 0 || p.y > size.h) continue;
      this.layers.grid.appendChild(svgEl('line', { x1: 0, y1: p.y, x2: size.w, y2: p.y, class: 'grid-line' }));
      this.layers.grid.appendChild(svgEl('text', { x: 4, y: p.y - 3, class: 'grid-label' }))
        .textContent = lat + '°';
    }

    (this.data.background || []).forEach(function (bg) {
      var s = self._toScreen(bg.lat, bg.lon, size);
      if (s.x < -10 || s.y < -10 || s.x > size.w + 10 || s.y > size.h + 10) return;
      self.layers.background.appendChild(svgEl('circle', { cx: s.x, cy: s.y, r: 1.6, class: 'bg-dot' }));
    });

    var centerScreen = this.data.center ? this._toScreen(this.data.center.lat, this.data.center.lon, size) : null;
    if (centerScreen) {
      this.data.points.forEach(function (pt) {
        var s = self._toScreen(pt.lat, pt.lon, size);
        var line = svgEl('line', { x1: centerScreen.x, y1: centerScreen.y, x2: s.x, y2: s.y,
                                   class: 'hop-line' + (pt.selected ? ' selected' : '') });
        line.style.strokeWidth = (1 + 3 * Math.sqrt(Math.max(0, Math.min(1, pt.weight)))).toFixed(2);
        self.layers.lines.appendChild(line);
      });
    }

    this.data.points.forEach(function (pt) {
      var s = self._toScreen(pt.lat, pt.lon, size);
      var cls = 'city-dot' + (pt.isNew ? ' is-new' : '') + (pt.selected ? ' selected' : '');
      var circle = svgEl('circle', { cx: s.x, cy: s.y, r: radiusFor(pt.weight), class: cls });
      circle.addEventListener('mousemove', function (ev) {
        if (self.handlers.onHover) self.handlers.onHover(pt, ev.clientX, ev.clientY);
      });
      circle.addEventListener('mouseleave', function () { if (self.handlers.onLeave) self.handlers.onLeave(); });
      circle.addEventListener('click', function () { if (self.handlers.onSelect) self.handlers.onSelect(pt); });
      self.layers.points.appendChild(circle);
    });

    if (centerScreen) {
      this.layers.points.appendChild(svgEl('circle', { cx: centerScreen.x, cy: centerScreen.y, r: 7,
                                                       class: 'center-dot' }));
      this.layers.labels.appendChild(svgEl('text', { x: centerScreen.x + 11, y: centerScreen.y + 4,
                                                     class: 'city-label center' }))
        .textContent = this.data.center.name;
    }

    var labelled = this.data.points.slice().sort(function (a, b) { return b.weight - a.weight; }).slice(0, 22);
    labelled.forEach(function (pt) {
      var s = self._toScreen(pt.lat, pt.lon, size);
      var text = svgEl('text', { x: s.x + radiusFor(pt.weight) + 4, y: s.y + 4,
                                 class: 'city-label' + (pt.selected ? ' selected' : '') });
      text.textContent = pt.name;
      self.layers.labels.appendChild(text);
    });
  };

  SvgMap.prototype.destroy = function () {
    window.removeEventListener('resize', this._onResize);
    this.container.textContent = '';
  };

  // ---------------------------------------------------------------- Leaflet renderer

  function LeafletMap(container, handlers) {
    this.container = container;
    this.handlers = handlers || {};
    this.map = window.L.map(container, { zoomControl: true, worldCopyJump: true, preferCanvas: true })
      .setView([51.5, 7.6], 5);
    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 12, attribution: '&copy; OpenStreetMap'
    }).addTo(this.map);
    this.layer = window.L.layerGroup().addTo(this.map);
  }

  LeafletMap.prototype.kind = 'osm';

  LeafletMap.prototype.setData = function (data) {
    var self = this, L = window.L;
    this.layer.clearLayers();
    (data.background || []).forEach(function (bg) {
      L.circleMarker([bg.lat, bg.lon], { radius: 1.5, stroke: false, fillColor: '#7d8ba1',
                                         fillOpacity: 0.35, interactive: false }).addTo(self.layer);
    });
    if (data.center) {
      data.points.forEach(function (pt) {
        L.polyline([[data.center.lat, data.center.lon], [pt.lat, pt.lon]], {
          color: pt.selected ? '#f5a524' : '#5b8def', interactive: false,
          weight: 0.6 + 2.6 * Math.sqrt(Math.max(0, Math.min(1, pt.weight))),
          opacity: pt.selected ? 0.9 : 0.35
        }).addTo(self.layer);
      });
    }
    data.points.forEach(function (pt) {
      var marker = L.circleMarker([pt.lat, pt.lon], {
        radius: radiusFor(pt.weight),
        color: pt.selected ? '#f5a524' : (pt.isNew ? '#2fbf71' : '#5b8def'),
        weight: pt.selected ? 3 : 1.5, fillOpacity: 0.45,
        fillColor: pt.isNew ? '#2fbf71' : '#5b8def'
      }).addTo(self.layer);
      marker.on('mousemove', function (ev) {
        if (self.handlers.onHover) self.handlers.onHover(pt, ev.originalEvent.clientX, ev.originalEvent.clientY);
      });
      marker.on('mouseout', function () { if (self.handlers.onLeave) self.handlers.onLeave(); });
      marker.on('click', function () { if (self.handlers.onSelect) self.handlers.onSelect(pt); });
    });
    if (data.center) {
      L.circleMarker([data.center.lat, data.center.lon], {
        radius: 7, color: '#e5484d', weight: 3, fillColor: '#e5484d', fillOpacity: 0.8
      }).addTo(this.layer).bindTooltip(data.center.name, { permanent: true, direction: 'right' });
    }
    if (data.fit) {
      var all = data.points.map(function (p) { return [p.lat, p.lon]; });
      if (data.center) all.push([data.center.lat, data.center.lon]);
      if (all.length === 1) this.map.setView(all[0], 6);
      else if (all.length > 1) this.map.fitBounds(all, { padding: [40, 40] });
    }
  };

  LeafletMap.prototype.invalidate = function () { this.map.invalidateSize(); };

  LeafletMap.prototype.destroy = function () {
    this.map.remove();
    this.container.textContent = '';
  };

  /* Pick the renderer: "osm" only when Leaflet is really available, otherwise the SVG fallback. */
  function createMap(container, handlers, preferred) {
    container.textContent = '';
    if (preferred !== 'svg' && window.L && typeof window.L.map === 'function') {
      try {
        return new LeafletMap(container, handlers);
      } catch (err) {
        container.textContent = '';
        return new SvgMap(container, handlers);
      }
    }
    return new SvgMap(container, handlers);
  }

  return { createMap: createMap, project: project, radiusFor: radiusFor };
}));
