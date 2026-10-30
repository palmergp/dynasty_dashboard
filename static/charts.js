// Small SVG chart helpers: line chart with crosshair tooltip, sparkline, stacked bars.
// Colors come from CSS tokens (--series-N, --grid, --axis, --context-line); text never
// wears a series color. Labels are inserted with textContent.
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
const compact = v => {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "K";
  return String(Math.round(v));
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dateLabel = iso => { const [y, m, d] = iso.split("-"); return `${MONTHS[+m - 1]} ${+d}, ${y}`; };

function niceTicks(max, count = 4) {
  if (max <= 0) return [0];
  const raw = max / count, pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * pow).find(s => s >= raw);
  const ticks = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function tipRows(tip, title, rows) {
  tip.replaceChildren();
  const t = document.createElement("div"); t.className = "tt-title"; t.textContent = title; tip.append(t);
  for (const r of rows) {
    const row = document.createElement("div"); row.className = "tt-row" + (r.hl ? " hl" : "");
    const key = document.createElement("span"); key.className = "tt-key"; key.style.background = r.color;
    const val = document.createElement("span"); val.className = "tt-val"; val.textContent = r.value;
    const lab = document.createElement("span"); lab.className = "tt-lab"; lab.textContent = r.label;
    row.append(key, val, lab); tip.append(row);
  }
}
function placeTip(tip, host, x, y) {
  tip.hidden = false;
  const w = tip.offsetWidth, hw = host.clientWidth;
  tip.style.left = Math.min(Math.max(0, x + 14), hw - w) + "px";
  tip.style.top = Math.max(0, y - tip.offsetHeight / 2) + "px";
  if (x + 14 + w > hw) tip.style.left = Math.max(0, x - w - 14) + "px";
}

/**
 * lineChart(host, {dates, series:[{id,label,values,color?,highlight}], format, markers:[{date,label}], height})
 * Non-highlighted series are drawn as muted context lines; highlighted ones get a color,
 * an end dot and (when there's room) a direct end label.
 */
function lineChart(host, opts) {
  const { dates, series, format = compact, markers = [], height = 320, yLabel = "" } = opts;
  host.classList.add("chart");
  host.replaceChildren();
  const W = Math.max(320, host.clientWidth), H = height;
  const m = { l: 48, r: 128, t: 14, b: 30 };
  if (W < 560) m.r = 16;
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const ts = dates.map(d => Date.parse(d));
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const x = t => m.l + (t - t0) / (t1 - t0 || 1) * iw;
  const vmax = Math.max(1, ...series.flatMap(s => s.values.filter(v => v != null)));
  const ticks = niceTicks(vmax);
  const ymax = ticks[ticks.length - 1];
  const y = v => m.t + ih - v / ymax * ih;

  const svg = svgEl("svg", { width: W, height: H, role: "img", "aria-label": opts.title || "Line chart" });
  for (const tv of ticks) {
    svg.append(svgEl("line", { x1: m.l, x2: m.l + iw, y1: y(tv), y2: y(tv), stroke: tv === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    const tx = svgEl("text", { x: m.l - 8, y: y(tv) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--chart-muted)" });
    tx.textContent = format(tv); svg.append(tx);
  }
  if (yLabel) { const yl = svgEl("text", { x: m.l, y: m.t - 3, "font-size": 11, fill: "var(--chart-muted)" }); yl.textContent = yLabel; svg.append(yl); }
  // Month ticks: ~6 evenly spaced first-of-month labels (off when markers label the points).
  const months = [];
  for (let d = new Date(t0); d <= new Date(t1); d.setMonth(d.getMonth() + 1)) months.push(new Date(d.getFullYear(), d.getMonth(), 1));
  const every = Math.max(1, Math.ceil(months.length / Math.max(2, Math.floor(iw / 90))));
  // opts.xLabels: one label per point (e.g. "Yr 1") instead of month ticks.
  if (opts.xLabels) {
    const step = Math.max(1, Math.ceil(ts.length / Math.max(2, Math.floor(iw / 44))));
    ts.forEach((t, i) => {
      if (i % step) return;
      const lab = svgEl("text", { x: x(t), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--chart-muted)" });
      lab.textContent = opts.xLabels[i]; svg.append(lab);
    });
  }
  months.filter((_, i) => !opts.hideMonths && !opts.xLabels && i % every === 0).forEach(d => {
    const t = d.getTime(); if (t < t0) return;
    const lab = svgEl("text", { x: x(t), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--chart-muted)" });
    lab.textContent = `${MONTHS[d.getMonth()]} '${String(d.getFullYear()).slice(2)}`; svg.append(lab);
  });
  for (const mk of markers) {
    const mx = x(Date.parse(mk.date));
    svg.append(svgEl("line", { x1: mx, x2: mx, y1: m.t, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }));
    const lab = svgEl("text", { x: mx + 4, y: m.t + 10, "font-size": 11, fill: "var(--chart-muted)" });
    lab.textContent = mk.label; svg.append(lab);
  }

  const pathFor = vals => {
    let d = "", pen = false;
    vals.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(v).toFixed(1)}`; pen = true;
    });
    return d;
  };
  const ordered = [...series.filter(s => !s.highlight), ...series.filter(s => s.highlight)];
  for (const s of ordered) {
    svg.append(svgEl("path", {
      d: pathFor(s.values), fill: "none", stroke: s.highlight ? s.color : "var(--context-line)",
      "stroke-width": s.highlight ? 2 : 1.25, "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
  }
  // End dots + direct labels for highlighted series (skip labels that would collide).
  const ends = series.filter(s => s.highlight).map(s => {
    const i = s.values.map(v => v != null).lastIndexOf(true);
    return i < 0 ? null : { s, i, px: x(ts[i]), py: y(s.values[i]) };
  }).filter(Boolean).sort((a, b) => a.py - b.py);
  let lastY = -Infinity;
  for (const e of ends) {
    svg.append(svgEl("circle", { cx: e.px, cy: e.py, r: 4, fill: e.s.color, stroke: "var(--panel)", "stroke-width": 2 }));
    if (m.r > 40 && e.py - lastY >= 14) {
      const lab = svgEl("text", { x: e.px + 8, y: e.py + 4, "font-size": 12, fill: "var(--text)" });
      lab.textContent = `${e.s.label} ${format(e.s.values[e.i])}`; svg.append(lab);
      lastY = e.py;
    }
  }

  // Hover layer: crosshair snaps to the nearest snapshot; one tooltip lists every series.
  const cross = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--chart-muted)", "stroke-width": 1, visibility: "hidden" });
  const dots = svgEl("g", { visibility: "hidden" });
  svg.append(cross, dots);
  const hit = svgEl("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0, class: "hit",
    "aria-label": "Chart data; use left and right arrow keys to move between dates" });
  svg.append(hit);
  host.append(svg);
  const tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true; host.append(tip);
  let cur = -1;
  const show = i => {
    cur = i;
    const px = x(ts[i]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    dots.replaceChildren(); dots.setAttribute("visibility", "visible");
    for (const s of series.filter(s => s.highlight && s.values[i] != null))
      dots.append(svgEl("circle", { cx: px, cy: y(s.values[i]), r: 4, fill: s.color, stroke: "var(--panel)", "stroke-width": 2 }));
    const rows = series.filter(s => s.values[i] != null)
      .sort((a, b) => (b.highlight - a.highlight) || (b.values[i] - a.values[i]))
      .map(s => ({ color: s.highlight ? s.color : "var(--context-line)", value: format(s.values[i]), label: s.label, hl: s.highlight }));
    if (!rows.length) { tip.hidden = true; return; }
    tipRows(tip, opts.xLabels ? opts.xLabels[i] : dateLabel(dates[i]), rows);
    const hy = Math.min(...series.filter(s => s.highlight && s.values[i] != null).map(s => y(s.values[i])), m.t + ih / 2);
    placeTip(tip, host, px, hy);
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); dots.setAttribute("visibility", "hidden"); tip.hidden = true; };
  hit.addEventListener("pointermove", ev => {
    const r = svg.getBoundingClientRect(), t = t0 + (ev.clientX - r.left - m.l) / iw * (t1 - t0);
    let best = 0; ts.forEach((tt, i) => { if (Math.abs(tt - t) < Math.abs(ts[best] - t)) best = i; });
    show(best);
  });
  hit.addEventListener("pointerleave", hide);
  hit.addEventListener("blur", hide);
  hit.addEventListener("focus", () => show(cur < 0 ? ts.length - 1 : cur));
  hit.addEventListener("keydown", ev => {
    if (ev.key === "ArrowLeft") { show(Math.max(0, cur - 1)); ev.preventDefault(); }
    if (ev.key === "ArrowRight") { show(Math.min(ts.length - 1, cur + 1)); ev.preventDefault(); }
  });
}

/** Inline sparkline: one series, slot-1 stroke, end dot. Zero-based with a minimum top
 *  so near-worthless players read as flat near zero rather than as wild swings. */
function sparkline(values, w = 96, h = 26, floorMax = 1500) {
  const pts = values.map((v, i) => [i, v]).filter(p => p[1] != null);
  if (pts.length < 2) return "";
  const max = Math.max(...pts.map(p => p[1]), floorMax), min = 0;
  const i0 = pts[0][0], i1 = pts[pts.length - 1][0];
  const px = i => 3 + (i - i0) / (i1 - i0 || 1) * (w - 6), py = v => 3 + (h - 6) * (1 - (v - min) / (max - min || 1));
  const d = pts.map((p, k) => `${k ? "L" : "M"}${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join("");
  const [li, lv] = pts[pts.length - 1];
  return `<svg class="spark" width="${w}" height="${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="var(--series-1)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${px(li)}" cy="${py(lv)}" r="2.5" fill="var(--series-1)"/></svg>`;
}

/**
 * stackedBars(host, {rows:[{label, parts:{key:value}, tip:{key:text}}], keys, labels, max?, format, text?})
 * Horizontal bars; 2px surface gaps between segments; 4px rounded data end.
 * Segment label defaults to its share of `max` (format); pass text(value) to show raw values.
 */
function stackedBars(host, opts) {
  const { rows, keys, labels, format = v => v.toFixed(0) + "%" } = opts;
  const text = opts.text || ((v, total) => format(v / total * 100));
  // Default: categorical slots in fixed order. Ordered categories pass an ordinal ramp.
  const colors = opts.colors || keys.map((_, i) => `var(--series-${i + 1})`);
  const onColors = opts.onColors || keys.map((_, i) => `var(--on-series-${i + 1})`);
  host.classList.add("chart");
  host.replaceChildren();
  const W = Math.max(320, host.clientWidth), rowH = 30, barH = 20, labW = Math.min(150, W * 0.3);
  const H = rows.length * rowH + 4, iw = W - labW - 8;
  const svg = svgEl("svg", { width: W, height: H, role: "img", "aria-label": opts.title || "Stacked bar chart" });
  const tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true;
  rows.forEach((r, ri) => {
    const total = (opts.max ?? keys.reduce((s, k) => s + (r.parts[k] || 0), 0)) || 1;
    const y0 = ri * rowH + (rowH - barH) / 2;
    const name = svgEl("text", { x: labW - 8, y: y0 + barH / 2 + 4, "text-anchor": "end", "font-size": 12, fill: "var(--text)" });
    name.textContent = r.label; svg.append(name);
    let xc = labW;
    const segs = keys.map((k, ki) => ({ k, ki, w: (r.parts[k] || 0) / total * iw })).filter(s => s.w > 0);
    segs.forEach((s, si) => {
      const last = si === segs.length - 1;
      const w = Math.max(0, s.w - (last ? 0 : 2));
      const g = svgEl("g", { tabindex: 0, class: "hit" });
      // Square at the baseline, 4px rounded only at the data end.
      const rr = last ? Math.min(4, w / 2) : 0;
      const d = `M${xc},${y0}h${w - rr}${rr ? `a${rr},${rr} 0 0 1 ${rr},${rr}v${barH - 2 * rr}a${rr},${rr} 0 0 1 -${rr},${rr}` : `v${barH}`}h-${w - rr}z`;
      const p = svgEl("path", { d, fill: colors[s.ki] });
      g.append(p);
      const txt = text(r.parts[s.k], total);
      if (w > txt.length * 7 + 12) {
        const t = svgEl("text", { x: xc + w / 2, y: y0 + barH / 2 + 4, "text-anchor": "middle", "font-size": 11, "font-weight": 600, fill: onColors[s.ki], "pointer-events": "none" });
        t.textContent = txt; g.append(t);
      }
      const showTip = ev => {
        p.setAttribute("opacity", 0.8);
        tipRows(tip, r.label, [{ color: colors[s.ki], value: txt, label: labels[s.k] + (r.tip?.[s.k] ? ` · ${r.tip[s.k]}` : "") }]);
        const hr = host.getBoundingClientRect();
        placeTip(tip, host, ev.clientX ? ev.clientX - hr.left : xc + w / 2, y0 + barH / 2);
      };
      g.addEventListener("pointermove", showTip);
      g.addEventListener("focus", showTip);
      const hideTip = () => { p.removeAttribute("opacity"); tip.hidden = true; };
      g.addEventListener("pointerleave", hideTip);
      g.addEventListener("blur", hideTip);
      svg.append(g);
      xc += s.w;
    });
  });
  host.append(svg, tip);
}

/** Nice ticks covering [lo, hi] (not zero-based). Steps of 1/2/5 so compact labels stay exact. */
function rangeTicks(lo, hi, count = 5) {
  const raw = (hi - lo) / count || 1, pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map(m => m * pow).find(s => s >= raw);
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.999; v += step) ticks.push(v);
  return ticks;
}

/**
 * scatter(host, {points:[{id,label,x,y,color,highlight,tip:[[label,value],...]}], xLabel, yLabel,
 *   xFormat, yFormat, refX, refY, quadrants:{tl,tr,bl,br}, height})
 * Every point is direct-labeled where it fits (collision-checked); hit targets are 28px.
 */
// Vertical bars around a zero line, e.g. % change by age. items: [{label, value, highlight, tip}].
// Above zero uses the diverging palette's positive pole, below zero the negative pole.
function divergingColumns(host, opts) {
  const { items, format = v => `${v > 0 ? "+" : ""}${Math.round(v)}%`, height = 220 } = opts;
  host.classList.add("chart");
  host.replaceChildren();
  const W = Math.max(320, host.clientWidth), H = height;
  const m = { l: 44, r: 10, t: 12, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const lim = Math.max(10, ...items.map(d => Math.abs(d.value)));
  const ticks = niceTicks(lim);
  const top = ticks[ticks.length - 1];
  const y = v => m.t + ih / 2 - v / top * (ih / 2);
  const bw = iw / items.length, barW = Math.max(4, Math.min(28, bw - 2));
  const svg = svgEl("svg", { width: W, height: H, role: "img", "aria-label": opts.title || "Column chart" });
  for (const tv of [-top, -top / 2, 0, top / 2, top]) {
    svg.append(svgEl("line", { x1: m.l, x2: m.l + iw, y1: y(tv), y2: y(tv), stroke: tv === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    const t = svgEl("text", { x: m.l - 6, y: y(tv) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--chart-muted)" }); t.textContent = format(tv); svg.append(t);
  }
  const tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true;
  items.forEach((d, i) => {
    const cx = m.l + bw * i + bw / 2, y0 = y(0), y1 = y(d.value);
    const h = Math.abs(y1 - y0), r = Math.min(4, h / 2, barW / 2);
    const up = d.value >= 0, x0 = cx - barW / 2;
    // Rounded at the data end only, square at the zero line.
    const path = up
      ? `M${x0},${y0} V${y1 + r} Q${x0},${y1} ${x0 + r},${y1} H${x0 + barW - r} Q${x0 + barW},${y1} ${x0 + barW},${y1 + r} V${y0} Z`
      : `M${x0},${y0} V${y1 - r} Q${x0},${y1} ${x0 + r},${y1} H${x0 + barW - r} Q${x0 + barW},${y1} ${x0 + barW},${y1 - r} V${y0} Z`;
    svg.append(svgEl("path", { d: path, fill: up ? "var(--div-s2)" : "var(--div-n2)", stroke: d.highlight ? "var(--text)" : "none", "stroke-width": d.highlight ? 2 : 0 }));
    if (d.highlight || items.length <= 16 || i % 2 === 0) {
      const t = svgEl("text", { x: cx, y: H - 16, "text-anchor": "middle", "font-size": 11, fill: d.highlight ? "var(--text)" : "var(--chart-muted)", "font-weight": d.highlight ? 700 : 400 });
      t.textContent = d.label; svg.append(t);
    }
    const hit = svgEl("rect", { x: cx - bw / 2, y: m.t, width: bw, height: ih, fill: "transparent", tabindex: 0, class: "hit", "aria-label": `${d.label}: ${format(d.value)}` });
    const show = () => { tipRows(tip, d.label, d.tip || [{ color: up ? "var(--div-s2)" : "var(--div-n2)", value: format(d.value), label: "" }]); placeTip(tip, host, cx, y1); };
    hit.addEventListener("pointermove", show); hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", () => (tip.hidden = true)); hit.addEventListener("blur", () => (tip.hidden = true));
    svg.append(hit);
  });
  if (opts.xLabel) { const t = svgEl("text", { x: m.l + iw / 2, y: H - 2, "text-anchor": "middle", "font-size": 11, fill: "var(--chart-muted)" }); t.textContent = opts.xLabel; svg.append(t); }
  host.append(svg, tip);
}

function scatter(host, opts) {
  const { points, xFormat = compact, yFormat = compact, height = 380 } = opts;
  host.classList.add("chart");
  host.replaceChildren();
  const W = Math.max(320, host.clientWidth), H = height;
  const m = { l: 56, r: 24, t: 16, b: 44 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const xpad = (Math.max(...xs) - Math.min(...xs)) * 0.08 || 1, ypad = (Math.max(...ys) - Math.min(...ys)) * 0.08 || 1;
  const xt = opts.xDomain ? rangeTicks(...opts.xDomain) : rangeTicks(Math.min(...xs) - xpad, Math.max(...xs) + xpad);
  const ylo = Math.min(...ys) - ypad;
  const yt = rangeTicks(Math.min(...ys) >= 0 ? Math.max(0, ylo) : ylo, Math.max(...ys) + ypad);  // don't pad below a zero floor
  const [x0, x1, y0, y1] = [xt[0], xt[xt.length - 1], yt[0], yt[yt.length - 1]];
  const x = v => m.l + (v - x0) / (x1 - x0) * iw, y = v => m.t + ih - (v - y0) / (y1 - y0) * ih;
  const svg = svgEl("svg", { width: W, height: H, role: "img", "aria-label": opts.title || "Scatter plot" });
  for (const v of yt) {
    svg.append(svgEl("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), stroke: v === y0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    const t = svgEl("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--chart-muted)" }); t.textContent = yFormat(v); svg.append(t);
  }
  for (const v of xt) {
    const t = svgEl("text", { x: x(v), y: m.t + ih + 16, "text-anchor": "middle", "font-size": 11, fill: "var(--chart-muted)" }); t.textContent = xFormat(v); svg.append(t);
  }
  const xl = svgEl("text", { x: m.l + iw / 2, y: H - 6, "text-anchor": "middle", "font-size": 12, fill: "var(--chart-muted)" }); xl.textContent = opts.xLabel || ""; svg.append(xl);
  const yl = svgEl("text", { x: 14, y: m.t + ih / 2, "text-anchor": "middle", "font-size": 12, fill: "var(--chart-muted)", transform: `rotate(-90 14 ${m.t + ih / 2})` }); yl.textContent = opts.yLabel || ""; svg.append(yl);
  // League-average reference lines split the plot into quadrants.
  if (opts.refX != null) svg.append(svgEl("line", { x1: x(opts.refX), x2: x(opts.refX), y1: m.t, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1 }));
  if (opts.refY != null) svg.append(svgEl("line", { x1: m.l, x2: m.l + iw, y1: y(opts.refY), y2: y(opts.refY), stroke: "var(--axis)", "stroke-width": 1 }));
  const q = iw >= 360 ? opts.quadrants || {} : {};  // no room for corner labels on narrow screens
  [["tl", m.l + 6, m.t + 14, "start"], ["tr", m.l + iw - 6, m.t + 14, "end"], ["bl", m.l + 6, m.t + ih - 8, "start"], ["br", m.l + iw - 6, m.t + ih - 8, "end"]]
    .forEach(([k, qx, qy, anchor]) => { if (!q[k]) return; const t = svgEl("text", { x: qx, y: qy, "text-anchor": anchor, "font-size": 11, fill: "var(--chart-muted)", "font-style": "italic" }); t.textContent = q[k]; svg.append(t); });

  const placed = [];
  const fits = b => b.x >= m.l && b.x + b.w <= m.l + iw + m.r && b.y >= 0 && b.y + b.h <= m.t + ih &&
    !placed.some(o => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
  const tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true;
  // Points first (so labels never cover a dot), highlighted last so they sit on top.
  const ordered = [...points].sort((a, b) => a.highlight - b.highlight);
  for (const p of ordered) placed.push({ x: x(p.x) - 8, y: y(p.y) - 8, w: 16, h: 16 });
  for (const p of ordered) {
    const px = x(p.x), py = y(p.y);
    if (p.highlight) svg.append(svgEl("circle", { cx: px, cy: py, r: 10, fill: "none", stroke: "var(--text)", "stroke-width": 1.5 }));
    svg.append(svgEl("circle", { cx: px, cy: py, r: 6, fill: p.color, stroke: "var(--panel)", "stroke-width": 2 }));
    const w = p.label.length * 6.6 + 4, h = 14;
    if (p.labeled === false) { addHit(p, px, py); continue; }
    const cand = [{ x: px + 10, y: py - h / 2 }, { x: px - 10 - w, y: py - h / 2 }, { x: px - w / 2, y: py - 10 - h }, { x: px - w / 2, y: py + 10 }]
      .map(c => ({ ...c, w, h }));
    const spot = cand.find(fits);
    if (spot) {
      placed.push({ ...spot, w, h });
      const t = svgEl("text", { x: spot.x + 2, y: spot.y + 11, "font-size": 12, fill: "var(--text)", "font-weight": p.highlight ? 700 : 400 });
      t.textContent = p.label; svg.append(t);
    }
    addHit(p, px, py);
  }
  function addHit(p, px, py) {
    const hit = svgEl("circle", { cx: px, cy: py, r: opts.hitRadius || 14, fill: "transparent", tabindex: 0, class: "hit", "aria-label": p.label });
    const show = () => {
      tipRows(tip, p.label, p.tip.map(([lab, val]) => ({ color: p.color, value: val, label: lab })));
      placeTip(tip, host, px, py);
    };
    hit.addEventListener("pointermove", show); hit.addEventListener("focus", show);
    hit.addEventListener("pointerleave", () => (tip.hidden = true)); hit.addEventListener("blur", () => (tip.hidden = true));
    svg.append(hit);
  }
  host.append(svg, tip);
}

const legendHTML = items => `<div class="legend">${items.map(i =>
  `<span><i class="${i.rect ? "rk" : "lk"}" style="background:${i.color}"></i>${esc(i.label)}</span>`).join("")}</div>`;
