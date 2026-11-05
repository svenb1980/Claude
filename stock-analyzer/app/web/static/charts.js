// Small hand-written SVG charts: no library and no external requests.
(function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const nf = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 });
  const eur = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
  const df = new Intl.DateTimeFormat("nl-NL", { day: "2-digit", month: "short", year: "numeric" });
  const dtf = new Intl.DateTimeFormat("nl-NL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const axisFull = new Intl.DateTimeFormat("nl-NL", { month: "short", year: "2-digit" });
  const axisShort = new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short" });
  const axisTime = new Intl.DateTimeFormat("nl-NL", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  const pctf = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const LEVEL_WINDOW = 0.35; // Lines further than this from the price would flatten the chart.

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

  // Keep level labels readable when lines sit close together.
  function spreadLabels(items, minGap, top, bottom) {
    const sorted = [...items].sort((a, b) => a.y - b.y);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].labelY < sorted[i - 1].labelY + minGap) sorted[i].labelY = sorted[i - 1].labelY + minGap;
    }
    const overflow = sorted.length ? sorted[sorted.length - 1].labelY - bottom : 0;
    if (overflow > 0) {
      sorted[sorted.length - 1].labelY = bottom;
      for (let i = sorted.length - 2; i >= 0; i--) {
        if (sorted[i].labelY > sorted[i + 1].labelY - minGap) sorted[i].labelY = sorted[i + 1].labelY - minGap;
      }
    }
    sorted.forEach((s) => { s.labelY = Math.max(s.labelY, top); });
  }

  // Each line as % change since its first value in the visible period.
  function restate(points, series) {
    const bases = {};
    series.forEach((s) => {
      const first = points.find((p) => p[s.key] != null);
      bases[s.key] = first ? first[s.key] : null;
    });
    return points.map((p) => {
      const out = { ...p };
      series.forEach((s) => {
        out[s.key] = p[s.key] == null || !bases[s.key] ? null : (p[s.key] / bases[s.key] - 1) * 100;
      });
      return out;
    });
  }

  function signedPct(value) {
    return `${value > 0 ? "+" : ""}${pctf.format(value)}%`;
  }

  function drawLine(box, config, rawPoints) {
    box.textContent = "";
    const dateKey = config.dateKey || "d";
    const series = config.series.filter((s) => rawPoints.some((p) => p[s.key] != null));
    if (rawPoints.length < 2 || !series.length) return;
    const points = config.restate ? restate(rawPoints, series) : rawPoints;
    const fmt = config.restate ? signedPct : (v) => nf.format(v);

    const hasLevels = (config.levels || []).length > 0;
    const W = 900, H = 340, M = { l: 52, r: hasLevels || config.restate ? 150 : 16, t: 10, b: 26 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" }, box);

    const dates = points.map((p) => new Date(p[dateKey]));
    const values = points.flatMap((p) => series.map((s) => p[s.key])).filter((v) => v != null);
    const lastPrice = points[points.length - 1][series[0].key];
    const levels = (config.levels || []).filter((l) => Math.abs(l.price / lastPrice - 1) <= LEVEL_WINDOW);
    const domain = values.concat(levels.map((l) => l.price));
    const min = Math.min(...domain), max = Math.max(...domain);
    const pad = (max - min) * 0.05 || 1;
    const y0 = min - pad, y1 = max + pad;
    const x = (i) => M.l + (i / (points.length - 1)) * (W - M.l - M.r);
    const y = (v) => M.t + (1 - (v - y0) / (y1 - y0)) * (H - M.t - M.b);

    niceTicks(y0, y1, 5).forEach((tick) => {
      el("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), stroke: "var(--grid)", "stroke-width": 1 }, svg);
      const label = el("text", { x: M.l - 8, y: y(tick) + 4, "text-anchor": "end", "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = config.restate ? `${nf.format(tick)}%` : nf.format(tick);
    });

    const spanDays = (dates[dates.length - 1] - dates[0]) / 86400000;
    const axis = config.intraday ? axisTime : spanDays < 200 ? axisShort : axisFull;
    const labelCount = 5;
    for (let k = 0; k <= labelCount; k++) {
      const i = Math.round((k / labelCount) * (points.length - 1));
      const anchor = k === 0 ? "start" : k === labelCount ? "end" : "middle";
      const label = el("text", { x: x(i), y: H - 8, "text-anchor": anchor, "font-size": 12, fill: "var(--text-secondary)" }, svg);
      label.textContent = axis.format(dates[i]);
    }

    series.forEach((s) => {
      let path = "", pen = false;
      points.forEach((p, i) => {
        if (p[s.key] == null) { pen = false; return; }
        path += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(p[s.key]).toFixed(1)}`;
        pen = true;
      });
      el("path", { d: path, fill: "none", stroke: `var(--series-${s.slot})`, "stroke-width": s.slot === 1 ? 2 : 1.5, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    });

    // Sell lines: dashed, with a direct label on the right. Text stays in ink colours.
    const labelled = levels.map((l) => ({ ...l, y: y(l.price), labelY: y(l.price) + 4 }));
    spreadLabels(labelled, 15, M.t + 10, H - M.b);
    labelled.forEach((l) => {
      el("line", { x1: M.l, x2: W - M.r, y1: l.y, y2: l.y, stroke: `var(--series-${l.slot})`, "stroke-width": 1.5, "stroke-dasharray": "6 4" }, svg);
      if (Math.abs(l.labelY - 4 - l.y) > 1) {
        el("line", { x1: W - M.r, x2: W - M.r + 6, y1: l.y, y2: l.labelY - 4, stroke: `var(--series-${l.slot})`, "stroke-width": 1 }, svg);
      }
      const text = el("text", { x: W - M.r + 8, y: l.labelY, "font-size": 12, fill: "var(--text-primary)" }, svg);
      text.textContent = `${l.label} ${nf.format(l.price)}`;
    });

    if (config.restate) {
      const ends = series.map((s) => {
        let last = null;
        for (let i = points.length - 1; i >= 0 && last == null; i--) last = points[i][s.key];
        return { series: s, value: last, y: y(last), labelY: y(last) + 4 };
      }).filter((e) => e.value != null);
      spreadLabels(ends, 15, M.t + 10, H - M.b);
      ends.forEach((e) => {
        if (Math.abs(e.labelY - 4 - e.y) > 1) {
          el("line", { x1: W - M.r, x2: W - M.r + 6, y1: e.y, y2: e.labelY - 4, stroke: `var(--series-${e.series.slot})`, "stroke-width": 1 }, svg);
        }
        const text = el("text", { x: W - M.r + 8, y: e.labelY, "font-size": 12, fill: "var(--text-primary)" }, svg);
        const name = e.series.label.length > 13 ? `${e.series.label.slice(0, 12)}…` : e.series.label;
        text.textContent = `${name} ${signedPct(e.value)}`;
      });
    }

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
      title.textContent = (config.intraday ? dtf : df).format(dates[i]);
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
        row.append(mark, `${s.label}: ${fmt(value)}`);
        tip.appendChild(row);
      });
      tip.style.display = "block";
      const scale = rect.width / W;
      const left = x(i) * scale;
      tip.style.left = left > rect.width / 2 ? `${left - tip.offsetWidth - 12}px` : `${left + 12}px`;
    });
  }

  function sliceRange(points, range, dateKey) {
    if (range.months === undefined) return points.slice(-range.days);
    if (range.months === null) return points;
    // In UTC, so summer time can't shift the date. A day that doesn't exist in the target
    // month becomes that month's last day, as on the server (31 August - 6 months = 28 February).
    const last = new Date(points[points.length - 1][dateKey]);
    const firstOfMonth = new Date(Date.UTC(last.getUTCFullYear(), last.getUTCMonth() - range.months, 1));
    const monthDays = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth() + 1, 0)).getUTCDate();
    const cutoff = new Date(Date.UTC(firstOfMonth.getUTCFullYear(), firstOfMonth.getUTCMonth(), Math.min(last.getUTCDate(), monthDays)));
    // Start at the last point on or before the cutoff, as the table on the page does.
    let from = 0;
    points.forEach((p, i) => { if (new Date(p[dateKey]) <= cutoff) from = i; });
    return points.slice(from);
  }

  function lineChart(container, config) {
    const all = config.points;
    const series = config.series.filter((s) => all.some((p) => p[s.key] != null));
    if (all.length < 2 || !series.length) return;
    legend(container, series);

    const box = document.createElement("div");
    box.className = "chart-box";

    if (config.ranges) {
      const bar = document.createElement("div");
      bar.className = "chart-ranges";
      const usable = config.ranges.filter((r, i) => r.months !== undefined || i === 0 || all.length > config.ranges[i - 1].days);
      const start = usable.find((r) => r === config.currentRange)
        || usable.find((r) => r.days === config.defaultRange || (r.months !== undefined && r.months === config.defaultMonths))
        || usable[usable.length - 1];
      const buttons = usable.map((range) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = range.label;
        button.addEventListener("click", () => select(range, button));
        bar.appendChild(button);
        return { range, button };
      });
      function select(range, active) {
        buttons.forEach((b) => b.button.setAttribute("aria-pressed", String(b.button === active)));
        config.currentRange = range;
        drawLine(box, config, sliceRange(all, range, config.dateKey || "d"));
      }
      container.append(bar, box);
      select(start, buttons.find((b) => b.range === start).button);
    } else {
      container.appendChild(box);
      drawLine(box, config, all);
    }
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

  async function marketCompare(section) {
    const say = (text) => {
      section.textContent = "";
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = text;
      section.appendChild(p);
    };
    say(section.dataset.loading);
    let data;
    try {
      data = await (await fetch("/api/market-comparison")).json();
    } catch (error) {
      say(section.dataset.failed);
      return;
    }
    if (data.error) { say(data.error); return; }
    section.textContent = "";

    const controls = document.createElement("label");
    controls.className = "compare-controls";
    const select = document.createElement("select");
    data.subjects.forEach((subject) => {
      const option = document.createElement("option");
      option.value = subject.key;
      option.textContent = subject.label;
      select.appendChild(option);
    });
    controls.append(section.dataset.subjectLabel, select);
    const chart = document.createElement("div");
    section.append(controls, chart);

    const config = {
      points: data.points, ranges: data.ranges, defaultMonths: data.defaultMonths, restate: true,
    };
    function render() {
      const subject = data.subjects.find((s) => s.key === select.value);
      config.series = [
        { key: subject.key, label: subject.label, slot: 1 },
        ...data.markets.map((m, i) => ({ key: m.key, label: m.label, slot: i + 2 })),
      ];
      chart.textContent = "";
      lineChart(chart, config);
    }
    select.addEventListener("change", render);
    render();
  }

  function intradayTable(section, rows) {
    const table = document.createElement("table");
    table.className = "level-table";
    const head = table.createTHead().insertRow();
    [["colLevel", ""], ["colPrice", "num"], ["colDistance", "num"], ["colEvidence", ""]].forEach(([key, cls]) => {
      const th = document.createElement("th");
      th.textContent = section.dataset[key];
      th.className = cls;
      head.appendChild(th);
    });
    const body = table.createTBody();
    rows.forEach((row) => {
      const tr = body.insertRow();
      const name = tr.insertCell();
      const strong = document.createElement("strong");
      strong.textContent = row.label;
      const explain = document.createElement("div");
      explain.className = "muted small";
      explain.textContent = row.explain;
      name.append(strong, explain);
      const price = tr.insertCell();
      price.className = "num";
      price.textContent = row.priceText;
      const distance = tr.insertCell();
      distance.className = "num";
      distance.textContent = row.distance;
      const evidence = tr.insertCell();
      evidence.className = "small";
      evidence.textContent = row.evidence;
    });
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    wrap.appendChild(table);
    return wrap;
  }

  function intraday(section) {
    const button = section.querySelector(".intraday-load");
    const output = section.querySelector(".intraday-output");
    function say(text) {
      output.textContent = "";
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = text;
      output.appendChild(p);
    }
    button.addEventListener("click", async () => {
      button.disabled = true;
      say(section.dataset.loading);
      try {
        const response = await fetch(`/api/intraday/${encodeURIComponent(section.dataset.intraday)}`);
        const data = await response.json();
        if (data.error) { say(data.error); return; }
        output.textContent = "";
        const chart = document.createElement("div");
        output.appendChild(chart);
        lineChart(chart, data.chart);
        output.appendChild(intradayTable(section, data.rows));
        data.notes.forEach((note) => {
          const p = document.createElement("p");
          p.className = "muted small";
          p.textContent = note;
          output.appendChild(p);
        });
      } catch (error) {
        say(section.dataset.failed);
      } finally {
        button.disabled = false;
      }
    });
  }

  document.querySelectorAll(".line-chart").forEach((c) => lineChart(c, JSON.parse(c.dataset.chart)));
  document.querySelectorAll(".bar-chart").forEach(barChart);
  document.querySelectorAll(".intraday").forEach(intraday);
  document.querySelectorAll(".market-compare").forEach(marketCompare);
})();
