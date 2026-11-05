// Small hand-written SVG charts: no library and no external requests.
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const nf = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 });
  const eur = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
  const df = new Intl.DateTimeFormat("nl-NL", { day: "2-digit", month: "short", year: "numeric" });
  const yearFmt = new Intl.DateTimeFormat("nl-NL", { month: "short", year: "2-digit" });

  function el(name, attrs, parent) {
    const node = document.createElementNS(SVG_NS, name);
    for (const key in attrs) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceTicks(min, max, count) {
    const span = max - min || 1;
    const raw = span / count;
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw);
    const ticks = [];
    // Adding 0 turns -0 into 0, which would otherwise be displayed as "-0".
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) ticks.push(v + 0);
    return ticks;
  }

  function legend(container, series) {
    if (series.length < 2) return;
    const box = document.createElement("div");
    box.className = "chart-legend";
    series.forEach((s) => {
      const item = document.createElement("span");
      const mark = document.createElement("i");
      mark.style.background = `var(--series-${s.slot})`;
      item.append(mark, s.label);
      box.appendChild(item);
    });
    container.appendChild(box);
  }

  function lineChart(container) {
    const config = JSON.parse(container.dataset.chart);
    const dateKey = config.dateKey || "d";
    const points = config.points;
    const series = config.series.filter((s) => points.some((p) => p[s.key] != null));
    if (points.length < 2 || !series.length) return;
    legend(container, series);

    const W = 900, H = 320, M = { l: 52, r: 16, t: 10, b: 26 };
    const box = document.createElement("div");
    box.className = "chart-box";
    container.appendChild(box);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, box);

    const dates = points.map((p) => new Date(p[dateKey]));
    const values = points.flatMap((p) => series.map((s) => p[s.key])).filter((v) => v != null);
    const min = Math.min(...values), max = Math.max(...values);
    const pad = (max - min) * 0.05 || 1;
    const y0 = min - pad, y1 = max + pad;
    const x = (i) => M.l + (i / (points.length - 1)) * (W - M.l - M.r);
    const y = (v) => M.t + (1 - (v - y0) / (y1 - y0)) * (H - M.t - M.b);

    niceTicks(y0, y1, 5).forEach((tick) => {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), stroke: "var(--grid)", "stroke-width": 1 }, svg);
      const label = el("text", { x: M.l - 8, y: y(tick) + 4, "text-anchor": "end", "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = nf.format(tick);
    });
    const labels = 6;
    for (let k = 0; k <= labels; k++) {
      const i = Math.round((k / labels) * (points.length - 1));
      const anchor = k === 0 ? "start" : k === labels ? "end" : "middle";
      const label = el("text", { x: x(i), y: H - 8, "text-anchor": anchor, "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = yearFmt.format(dates[i]);
    }

    series.forEach((s) => {
      let path = "", pen = false;
      points.forEach((p, i) => {
        if (p[s.key] == null) { pen = false; return; }
        path += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(p[s.key]).toFixed(1)}`;
        pen = true;
      });
      el("path", { d: path, fill: "none", stroke: `var(--series-${s.slot})`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    });

    const cross = el("line", { y1: M.t, y2: H - M.b, stroke: "var(--text-secondary)", "stroke-width": 1, visibility: "hidden" }, svg);
    const dots = series.map((s) => el("circle", { r: 4, fill: `var(--series-${s.slot})`, stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" }, svg));
    const tip = document.createElement("div");
    tip.className = "chart-tooltip";
    box.appendChild(tip);

    function hide() {
      tip.style.display = "none";
      cross.setAttribute("visibility", "hidden");
      dots.forEach((d) => d.setAttribute("visibility", "hidden"));
    }
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("pointermove", (event) => {
      const rect = svg.getBoundingClientRect();
      const px = ((event.clientX - rect.left) / rect.width) * W;
      const i = Math.max(0, Math.min(points.length - 1, Math.round(((px - M.l) / (W - M.l - M.r)) * (points.length - 1))));
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      tip.textContent = "";
      const title = document.createElement("b");
      title.textContent = df.format(dates[i]);
      tip.appendChild(title);
      series.forEach((s, n) => {
        const value = points[i][s.key];
        if (value == null) { dots[n].setAttribute("visibility", "hidden"); return; }
        dots[n].setAttribute("cx", x(i));
        dots[n].setAttribute("cy", y(value));
        dots[n].setAttribute("visibility", "visible");
        const row = document.createElement("div");
        const mark = document.createElement("i");
        mark.style.background = `var(--series-${s.slot})`;
        row.append(mark, `${s.label}: ${nf.format(value)}`);
        tip.appendChild(row);
      });
      tip.style.display = "block";
      const scale = rect.width / W;
      const left = x(i) * scale;
      tip.style.left = left > rect.width / 2 ? `${left - tip.offsetWidth - 12}px` : `${left + 12}px`;
    });
  }

  function barChart(container) {
    const config = JSON.parse(container.dataset.bars);
    const rows = config.rows;
    const series = [
      { key: "received", label: config.received, slot: 1 },
      { key: "expected", label: config.expected, slot: 2 },
    ];
    legend(container, series);
    const W = 900, H = 240, M = { l: 52, r: 8, t: 10, b: 24 };
    const box = document.createElement("div");
    box.className = "chart-box";
    container.appendChild(box);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, box);
    const max = Math.max(1, ...rows.map((r) => r.received + r.expected));
    const y = (v) => M.t + (1 - v / max) * (H - M.t - M.b);
    const slot = (W - M.l - M.r) / 12;
    const width = Math.min(slot * 0.55, 34);

    niceTicks(0, max, 4).forEach((tick) => {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), stroke: "var(--grid)", "stroke-width": 1 }, svg);
      const label = el("text", { x: M.l - 8, y: y(tick) + 4, "text-anchor": "end", "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = nf.format(tick);
    });

    const tip = document.createElement("div");
    tip.className = "chart-tooltip";
    box.appendChild(tip);

    rows.forEach((row, i) => {
      const cx = M.l + slot * i + slot / 2;
      const label = el("text", { x: cx, y: H - 7, "text-anchor": "middle", "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = config.months[i];
      let base = 0;
      series.forEach((s) => {
        const value = row[s.key];
        if (value <= 0) return;
        const top = y(base + value), bottom = y(base);
        // A 2px surface gap separates stacked segments.
        const height = Math.max(1.5, bottom - top - (base > 0 ? 2 : 0));
        el("rect", { x: cx - width / 2, y: top, width, height, rx: 3, fill: `var(--series-${s.slot})` }, svg);
        base += value;
      });
      const hit = el("rect", { x: cx - slot / 2, y: M.t, width: slot, height: H - M.t - M.b, fill: "transparent" }, svg);
      hit.addEventListener("pointerenter", () => {
        tip.textContent = "";
        const title = document.createElement("b");
        title.textContent = config.months[i];
        tip.appendChild(title);
        series.forEach((s) => {
          const line = document.createElement("div");
          const mark = document.createElement("i");
          mark.style.background = `var(--series-${s.slot})`;
          line.append(mark, `${s.label}: ${eur.format(row[s.key])}`);
          tip.appendChild(line);
        });
        tip.style.display = "block";
        const rect = svg.getBoundingClientRect();
        const left = (cx / W) * rect.width;
        tip.style.left = left > rect.width / 2 ? `${left - tip.offsetWidth - 12}px` : `${left + 12}px`;
      });
      hit.addEventListener("pointerleave", () => { tip.style.display = "none"; });
    });
  }

  document.querySelectorAll(".line-chart").forEach(lineChart);
  document.querySelectorAll(".bar-chart").forEach(barChart);
})();
