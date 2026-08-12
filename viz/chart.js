/* Shared SVG chart helper for the CL-Bench visualisation instrument.
 *
 * No dependencies, no build step. Every mark carries its color as an inline
 * `style` using a CSS custom property, so light/dark swap without touching JS.
 *
 * Conventions enforced here rather than per-chart:
 *   - 2px lines, round cap/join; markers r>=4 with a 2px surface ring
 *   - hairline SOLID gridlines, one step off surface, recessive
 *   - min/max envelope for n=3 spread; never a bar with an error bar
 *   - a legend whenever there are >=2 series, plus a table-view twin on
 *     every chart (also the relief channel for the two sub-3:1 light hues)
 *   - selective direct labels: endpoint only, never a value on every point
 */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const BASE = { t: 18, r: 88, b: 42, l: 72 };
  const M = BASE; // default margins; `bars` shadows this when it rotates labels

  // ---------------------------------------------------------------- dom ----
  function s(tag, attrs, style) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (style) n.setAttribute("style", style);
    return n;
  }
  function h(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // ------------------------------------------------------------- format ----
  function fmt(v, digits) {
    if (v == null || Number.isNaN(v)) return "—";
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (Math.abs(v) >= 1e4) return (v / 1e3).toFixed(0) + "k";
    if (Number.isInteger(v) && digits == null) return String(v);
    return v.toFixed(digits == null ? 2 : digits);
  }
  const pct = (v, d) => (v == null ? "—" : (v * 100).toFixed(d == null ? 1 : d) + "%");

  function niceTicks(lo, hi, count) {
    if (lo === hi) { lo -= 0.5; hi += 0.5; }
    const raw = (hi - lo) / (count || 5);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + step * 1e-9; t += step) {
      out.push(Math.abs(t) < step * 1e-9 ? 0 : +t.toFixed(10));
    }
    return out;
  }

  function extent(vals) {
    let lo = Infinity, hi = -Infinity;
    for (const v of vals) {
      if (v == null || Number.isNaN(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    return lo === Infinity ? [0, 1] : [lo, hi];
  }

  // ------------------------------------------------------------ scaffold ---
  function frame(container, cfg) {
    const card = h("div", "card");
    if (cfg.title) card.appendChild(h("h3", null, cfg.title));
    if (cfg.subtitle) card.appendChild(h("p", "sub", cfg.subtitle));
    container.appendChild(card);
    return card;
  }

  function legend(card, series) {
    // A single series needs no legend box — the title names it.
    if (series.filter((d) => !d.hideFromLegend).length < 2) return;
    const l = h("div", "legend");
    for (const d of series) {
      if (d.hideFromLegend) continue;
      const item = h("span", "lg-item");
      const sw = h("span", "lg-swatch" + (d.dash ? " lg-dash" : ""));
      sw.style.setProperty("--sw", "var(" + d.color + ")");
      item.appendChild(sw);
      item.appendChild(h("span", null, d.name));
      l.appendChild(item);
    }
    card.appendChild(l);
  }

  function note(card, text) {
    if (text) card.appendChild(h("p", "note", text));
  }

  /* Table-view twin. Mandatory: tooltips enhance, they never gate a value,
   * and it is the relief channel for the sub-3:1 light hues. */
  function tableView(card, columns, rows) {
    if (!columns || !rows) return;
    const det = h("details", "tv");
    det.appendChild(h("summary", null, "Table view (" + rows.length + " rows)"));
    const wrap = h("div", "tv-scroll");
    const t = h("table");
    const thead = h("thead"), tr = h("tr");
    columns.forEach((c) => tr.appendChild(h("th", null, c)));
    thead.appendChild(tr);
    t.appendChild(thead);
    const tb = h("tbody");
    rows.forEach((r) => {
      const row = h("tr");
      r.forEach((c) => row.appendChild(h("td", null, c == null ? "—" : String(c))));
      tb.appendChild(row);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    det.appendChild(wrap);
    card.appendChild(det);
  }

  function plot(card, w, hh) {
    const scroll = h("div", "plot");
    const svg = s("svg", {
      viewBox: "0 0 " + w + " " + hh,
      preserveAspectRatio: "xMidYMid meet",
      role: "img",
    });
    scroll.appendChild(svg);
    card.appendChild(scroll);
    return svg;
  }

  function tip(card) {
    const t = h("div", "tip");
    t.style.display = "none";
    card.appendChild(t);
    return {
      show(html, ev) {
        t.innerHTML = html;
        t.style.display = "block";
        const b = card.getBoundingClientRect();
        let x = ev.clientX - b.left + 14;
        const y = ev.clientY - b.top + 14;
        if (x + t.offsetWidth > b.width) x = ev.clientX - b.left - t.offsetWidth - 14;
        t.style.left = Math.max(4, x) + "px";
        t.style.top = y + "px";
      },
      hide() { t.style.display = "none"; },
    };
  }

  function axes(g, sc, cfg, w, hh) {
    const { xs, ys, xt, yt } = sc;
    // horizontal gridlines — hairline, solid, recessive
    for (const v of yt) {
      g.appendChild(s("line", { x1: M.l, x2: w - M.r, y1: ys(v), y2: ys(v) }, "stroke:var(--grid);stroke-width:1"));
      g.appendChild(s("text", { x: M.l - 8, y: ys(v) + 4, "text-anchor": "end" }, "fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums")
      ).textContent = (cfg.y.format || fmt)(v);
    }
    // baseline
    g.appendChild(s("line", { x1: M.l, x2: w - M.r, y1: ys(sc.yd[0] <= 0 && sc.yd[1] >= 0 ? 0 : sc.yd[0]), y2: ys(sc.yd[0] <= 0 && sc.yd[1] >= 0 ? 0 : sc.yd[0]) }, "stroke:var(--axis);stroke-width:1"));
    for (const v of xt) {
      g.appendChild(s("text", { x: xs(v), y: hh - M.b + 18, "text-anchor": "middle" }, "fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums")
      ).textContent = (cfg.x.format || fmt)(v);
    }
    if (cfg.x.label) {
      g.appendChild(s("text", { x: (M.l + w - M.r) / 2, y: hh - 4, "text-anchor": "middle" }, "fill:var(--muted);font-size:11px")
      ).textContent = cfg.x.label;
    }
    if (cfg.y.label) {
      g.appendChild(s("text", { x: 0, y: 0, transform: "translate(14," + (M.t + (hh - M.t - M.b) / 2) + ") rotate(-90)", "text-anchor": "middle" }, "fill:var(--muted);font-size:11px")
      ).textContent = cfg.y.label;
    }
  }

  // ================================================================ lines ==
  /* cfg.series[]: {id,name,color,values:[[x,y]], band:[[x,lo,hi]], dash, step,
   *                endLabel, hideFromLegend}
   * cfg.xBands[]: {from,to,label,color} — categorical background regions */
  function lines(container, cfg) {
    const w = cfg.width || 880, hh = cfg.height || 320;
    const card = frame(container, cfg);
    const svg = plot(card, w, hh);
    const tp = tip(card);

    const allX = [], allY = [];
    for (const d of cfg.series) {
      for (const p of d.values) { if (p[1] != null) { allX.push(p[0]); allY.push(p[1]); } }
      for (const p of d.band || []) { allY.push(p[1], p[2]); }
    }
    const xd = cfg.x.domain || extent(allX);
    let yd = cfg.y.domain || extent(allY);
    if (!cfg.y.domain) {
      const pad = (yd[1] - yd[0]) * 0.08 || 0.1;
      yd = [yd[0] < 0 ? yd[0] - pad : Math.min(0, yd[0]), yd[1] + pad];
    }
    const xs = (v) => M.l + ((v - xd[0]) / (xd[1] - xd[0] || 1)) * (w - M.l - M.r);
    const ys = (v) => hh - M.b - ((v - yd[0]) / (yd[1] - yd[0] || 1)) * (hh - M.t - M.b);
    const sc = { xs, ys, xd, yd, xt: cfg.x.ticks || niceTicks(xd[0], xd[1], 8), yt: cfg.y.ticks || niceTicks(yd[0], yd[1], 5) };

    const g = s("g");
    svg.appendChild(g);

    // background regime bands sit under everything
    for (const b of cfg.xBands || []) {
      g.appendChild(s("rect", { x: xs(b.from), y: M.t, width: Math.max(0, xs(b.to) - xs(b.from)), height: hh - M.t - M.b },
        "fill:var(" + (b.color || "--band") + ");opacity:.5"));
      if (b.label) {
        g.appendChild(s("text", { x: (xs(b.from) + xs(b.to)) / 2, y: M.t + 13, "text-anchor": "middle" },
          "fill:var(--muted);font-size:10px")).textContent = b.label;
      }
    }
    axes(g, sc, cfg, w, hh);

    // vertical rules (drift boundaries etc.)
    for (const r of cfg.xRules || []) {
      g.appendChild(s("line", { x1: xs(r.at), x2: xs(r.at), y1: M.t, y2: hh - M.b }, "stroke:var(--axis);stroke-width:1"));
      if (r.label) {
        g.appendChild(s("text", { x: xs(r.at) + 5, y: M.t + 12 }, "fill:var(--muted);font-size:10px")).textContent = r.label;
      }
    }

    const path = (pts, step) => {
      let d = "", pen = false, prev = null;
      for (const p of pts) {
        if (p[1] == null || Number.isNaN(p[1])) { pen = false; continue; }
        const X = xs(p[0]), Y = ys(p[1]);
        if (!pen) { d += "M" + X + "," + Y; pen = true; }
        else if (step) { d += "L" + X + "," + ys(prev[1]) + "L" + X + "," + Y; }
        else { d += "L" + X + "," + Y; }
        prev = p;
      }
      return d;
    };

    for (const dser of cfg.series) {
      // min/max envelope — the honest n=3 spread
      if (dser.band && dser.band.length) {
        let up = "", dn = "";
        const B = dser.band.filter((p) => p[1] != null && p[2] != null);
        B.forEach((p, i) => { up += (i ? "L" : "M") + xs(p[0]) + "," + ys(p[2]); });
        for (let i = B.length - 1; i >= 0; i--) dn += "L" + xs(B[i][0]) + "," + ys(B[i][1]);
        if (B.length) g.appendChild(s("path", { d: up + dn + "Z" }, "fill:var(" + dser.color + ");opacity:.10"));
      }
      g.appendChild(s("path", {
        d: path(dser.values, dser.step),
        "stroke-dasharray": dser.dash ? "6 4" : null,
      }, "fill:none;stroke:var(" + dser.color + ");stroke-width:2;stroke-linejoin:round;stroke-linecap:round"));

      // selective direct label: endpoint only
      const last = [...dser.values].reverse().find((p) => p[1] != null);
      if (last && dser.endLabel !== false) {
        g.appendChild(s("circle", { cx: xs(last[0]), cy: ys(last[1]), r: 4 },
          "fill:var(" + dser.color + ");stroke:var(--surface);stroke-width:2"));
        g.appendChild(s("text", { x: xs(last[0]) + 9, y: ys(last[1]) + 4 },
          "fill:var(--text-2);font-size:11px;font-variant-numeric:tabular-nums")
        ).textContent = dser.endText != null ? dser.endText : (cfg.y.format || fmt)(last[1]);
      }
    }

    // crosshair + shared tooltip
    const cross = s("line", { y1: M.t, y2: hh - M.b }, "stroke:var(--axis);stroke-width:1;visibility:hidden");
    g.appendChild(cross);
    const hit = s("rect", { x: M.l, y: M.t, width: w - M.l - M.r, height: hh - M.t - M.b }, "fill:transparent");
    g.appendChild(hit);
    hit.addEventListener("mousemove", (ev) => {
      const box = svg.getBoundingClientRect();
      const px = ((ev.clientX - box.left) / box.width) * w;
      const xv = xd[0] + ((px - M.l) / (w - M.l - M.r)) * (xd[1] - xd[0]);
      cross.setAttribute("x1", xs(xv)); cross.setAttribute("x2", xs(xv));
      cross.style.visibility = "visible";
      let rows = "";
      for (const dser of cfg.series) {
        let best = null, bd = Infinity;
        for (const p of dser.values) {
          if (p[1] == null) continue;
          const dd = Math.abs(p[0] - xv);
          if (dd < bd) { bd = dd; best = p; }
        }
        if (best) {
          rows += '<div class="tr"><span class="sw" style="--sw:var(' + dser.color + ')"></span>' +
            dser.name + "<b>" + (cfg.y.format || fmt)(best[1]) + "</b></div>";
        }
      }
      tp.show('<div class="th">' + (cfg.x.label || "x") + " " + (cfg.x.format || fmt)(Math.round(xv)) + "</div>" + rows, ev);
    });
    hit.addEventListener("mouseleave", () => { cross.style.visibility = "hidden"; tp.hide(); });

    /* Default: name the series. `cfg.legend` overrides — same escape hatch
     * `bars` and `grid` already have — for charts whose visual vocabulary is
     * wider than their series list (a band that means something distinct from
     * the line drawn through it, say). */
    legend(card, cfg.legend || cfg.series);
    note(card, cfg.note);
    if (cfg.table !== false) {
      const xsAll = [...new Set(cfg.series.flatMap((d) => d.values.map((p) => p[0])))].sort((a, b) => a - b);
      tableView(card,
        [cfg.x.label || "x", ...cfg.series.map((d) => d.name)],
        xsAll.map((xv) => [(cfg.x.format || fmt)(xv), ...cfg.series.map((d) => {
          const p = d.values.find((q) => q[0] === xv);
          return p ? (cfg.y.format || fmt)(p[1]) : "—";
        })]));
    }
    return card;
  }

  // ================================================================= bars ==
  /* Grouped bars. cfg.groups[]: {label, sublabel, bars:[{name,color,value,label}]}
   * cfg.dividers[]: index after which to draw a comparability-band rule. */
  function bars(container, cfg) {
    const card = frame(container, cfg);
    const groups = cfg.groups;
    const nBars = groups.reduce((a, g2) => a + g2.bars.length, 0);
    const w = cfg.width || 880;
    // Many groups means long labels collide horizontally — rotate them and
    // buy the room back from the bottom margin rather than clipping text.
    const rot = cfg.rotate != null ? cfg.rotate : (groups.length > 6 ? -35 : 0);
    const M = { t: BASE.t, r: BASE.r, l: BASE.l, b: rot ? (cfg.bottom || 118) : BASE.b };
    const hh = (cfg.height || 300) + (rot ? M.b - BASE.b : 0);
    const svg = plot(card, w, hh);
    const tp = tip(card);

    const vals = groups.flatMap((g2) => g2.bars.map((b) => b.value)).filter((v) => v != null);
    let yd = cfg.y.domain || extent(vals);
    if (!cfg.y.domain) {
      // Leave room BELOW zero so a short negative bar's value label doesn't
      // land on the x-axis labels.
      const lo = Math.min(0, yd[0]), hi = Math.max(0, yd[1]), span = (hi - lo) || 1;
      yd = [lo < 0 ? lo - span * 0.07 : 0, hi + span * 0.12];
    }
    const ys = (v) => hh - M.b - ((v - yd[0]) / (yd[1] - yd[0] || 1)) * (hh - M.t - M.b);
    const inner = w - M.l - M.r;
    const gap = 2; // the surface gap does the separating — never a stroke
    const slot = inner / Math.max(1, nBars + groups.length);
    const bw = Math.min(24, slot - gap);

    const g = s("g");
    svg.appendChild(g);
    const yt = cfg.y.ticks || niceTicks(yd[0], yd[1], 5);
    for (const v of yt) {
      g.appendChild(s("line", { x1: M.l, x2: w - M.r, y1: ys(v), y2: ys(v) }, "stroke:var(--grid);stroke-width:1"));
      g.appendChild(s("text", { x: M.l - 8, y: ys(v) + 4, "text-anchor": "end" }, "fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums")
      ).textContent = (cfg.y.format || fmt)(v);
    }
    g.appendChild(s("line", { x1: M.l, x2: w - M.r, y1: ys(Math.max(yd[0], 0)), y2: ys(Math.max(yd[0], 0)) }, "stroke:var(--axis);stroke-width:1"));

    let cursor = M.l + slot / 2;
    const seen = new Map();
    groups.forEach((grp, gi) => {
      const start = cursor;
      grp.bars.forEach((b) => {
        if (!seen.has(b.name)) seen.set(b.name, b.color);
        const x = cursor;
        if (b.value == null) {
          // Missing counterpart: an explicit empty slot, never an absent bar.
          g.appendChild(s("rect", { x: x - bw / 2, y: ys(Math.max(0, yd[0])) - 34, width: bw, height: 34, rx: 3 },
            "fill:none;stroke:var(--axis);stroke-width:1;stroke-dasharray:3 3"));
          g.appendChild(s("text", { x: x, y: ys(Math.max(0, yd[0])) - 40, "text-anchor": "middle" },
            "fill:var(--muted);font-size:9px")).textContent = "not measured";
        } else {
          const zero = ys(Math.max(yd[0], 0));
          const y0 = Math.min(zero, ys(b.value)), y1 = Math.max(zero, ys(b.value));
          const r = Math.min(4, Math.abs(y1 - y0) / 2);
          const rect = s("rect", { x: x - bw / 2, y: y0, width: bw, height: Math.max(1, y1 - y0), rx: r },
            "fill:var(" + b.color + ")");
          g.appendChild(rect);
          g.appendChild(s("text", { x: x, y: (b.value >= 0 ? y0 - 6 : y1 + 13), "text-anchor": "middle" },
            "fill:var(--text-2);font-size:10px;font-variant-numeric:tabular-nums")
          ).textContent = b.label != null ? b.label : (cfg.y.format || fmt)(b.value);
          rect.addEventListener("mousemove", (ev) => tp.show(
            '<div class="th">' + grp.label + "</div>" + '<div class="tr"><span class="sw" style="--sw:var(' +
            b.color + ')"></span>' + b.name + "<b>" + (cfg.y.format || fmt)(b.value) + "</b></div>", ev));
          rect.addEventListener("mouseleave", tp.hide);
        }
        cursor += slot;
      });
      const mid = (start + cursor - slot) / 2;
      if (rot) {
        g.appendChild(s("text", {
          transform: "translate(" + mid + "," + (hh - M.b + 14) + ") rotate(" + rot + ")",
          "text-anchor": "end",
        }, "fill:var(--text-2);font-size:11px")).textContent = grp.label;
        if (grp.sublabel) {
          g.appendChild(s("text", {
            transform: "translate(" + (mid + 22) + "," + (hh - M.b + 14) + ") rotate(" + rot + ")",
            "text-anchor": "end",
          }, "fill:var(--muted);font-size:9px")).textContent = grp.sublabel;
        }
      } else {
        g.appendChild(s("text", { x: mid, y: hh - M.b + 16, "text-anchor": "middle" },
          "fill:var(--text-2);font-size:11px")).textContent = grp.label;
        if (grp.sublabel) {
          g.appendChild(s("text", { x: mid, y: hh - M.b + 29, "text-anchor": "middle" },
            "fill:var(--muted);font-size:10px")).textContent = grp.sublabel;
        }
      }
      cursor += slot;
      if ((cfg.dividers || []).includes(gi)) {
        const dx = cursor - slot / 2;
        g.appendChild(s("line", { x1: dx, x2: dx, y1: M.t, y2: hh - M.b + 8 }, "stroke:var(--axis);stroke-width:1"));
      }
    });

    if (cfg.y.label) {
      g.appendChild(s("text", { transform: "translate(14," + (M.t + (hh - M.t - M.b) / 2) + ") rotate(-90)", "text-anchor": "middle" },
        "fill:var(--muted);font-size:11px")).textContent = cfg.y.label;
    }
    /* Deriving the legend from bar.name is only correct while a name maps to a
     * single colour. When the same measure is drawn in a different hue per
     * group (stateful reward coloured by system), the derived legend would
     * name one hue and silently misattribute the rest — so those charts pass
     * an explicit legend instead. */
    legend(card, cfg.legend || [...seen].map(([name, color]) => ({ name, color })));
    note(card, cfg.note);
    tableView(card, ["Group", ...[...seen.keys()]],
      groups.map((grp) => [grp.label + (grp.sublabel ? " (" + grp.sublabel + ")" : ""),
      ...[...seen.keys()].map((n) => {
        const b = grp.bars.find((x) => x.name === n);
        return b && b.value != null ? (cfg.y.format || fmt)(b.value) : "not measured";
      })]));
    return card;
  }

  // ================================================================= dots ==
  /* Per-run dot plot — with n=3 the honest form is all three points plus the
   * mean, never a bar with an implied confidence interval. */
  function dots(container, cfg) {
    const card = frame(container, cfg);
    const rows = cfg.rows;
    const w = cfg.width || 880;
    const rowH = 30;
    const hh = M.t + rows.length * rowH + M.b;
    const svg = plot(card, w, hh);
    const tp = tip(card);
    const vals = rows.flatMap((r) => r.values).filter((v) => v != null);
    let xd = cfg.x.domain || extent(vals);
    const pad = (xd[1] - xd[0]) * 0.12 || 0.1;
    if (!cfg.x.domain) xd = [xd[0] - pad, xd[1] + pad];
    const L = 210;
    const xs = (v) => L + ((v - xd[0]) / (xd[1] - xd[0] || 1)) * (w - L - M.r);
    const g = s("g");
    svg.appendChild(g);

    for (const t of cfg.x.ticks || niceTicks(xd[0], xd[1], 6)) {
      g.appendChild(s("line", { x1: xs(t), x2: xs(t), y1: M.t - 6, y2: hh - M.b }, "stroke:var(--grid);stroke-width:1"));
      g.appendChild(s("text", { x: xs(t), y: hh - M.b + 16, "text-anchor": "middle" },
        "fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums")).textContent = (cfg.x.format || fmt)(t);
    }
    rows.forEach((r, i) => {
      const y = M.t + i * rowH + rowH / 2;
      g.appendChild(s("text", { x: L - 10, y: y + 4, "text-anchor": "end" },
        "fill:var(--text-2);font-size:11px")).textContent = r.label;
      if (r.sublabel) {
        g.appendChild(s("text", { x: L - 10, y: y + 15, "text-anchor": "end" },
          "fill:var(--muted);font-size:9px")).textContent = r.sublabel;
      }
      const vv = r.values.filter((v) => v != null);
      if (vv.length > 1) {
        g.appendChild(s("line", { x1: xs(Math.min(...vv)), x2: xs(Math.max(...vv)), y1: y, y2: y },
          "stroke:var(" + r.color + ");stroke-width:2;opacity:.35;stroke-linecap:round"));
      }
      r.values.forEach((v, k) => {
        if (v == null) return;
        const c = s("circle", { cx: xs(v), cy: y, r: 4.5 },
          "fill:var(" + r.color + ");stroke:var(--surface);stroke-width:2");
        g.appendChild(c);
        c.addEventListener("mousemove", (ev) => tp.show(
          '<div class="th">' + r.label + "</div>" + '<div class="tr"><span class="sw" style="--sw:var(' +
          r.color + ')"></span>run ' + k + "<b>" + (cfg.x.format || fmt)(v) + "</b></div>", ev));
        c.addEventListener("mouseleave", tp.hide);
      });
      if (vv.length) {
        const mean = vv.reduce((a, b) => a + b, 0) / vv.length;
        g.appendChild(s("line", { x1: xs(mean), x2: xs(mean), y1: y - 9, y2: y + 9 },
          "stroke:var(--text-1);stroke-width:2;stroke-linecap:round"));
        g.appendChild(s("text", { x: xs(Math.max(...vv)) + 10, y: y + 4 },
          "fill:var(--text-2);font-size:10px;font-variant-numeric:tabular-nums"))
          .textContent = (cfg.x.format || fmt)(mean);
      }
    });
    if (cfg.x.label) {
      g.appendChild(s("text", { x: (L + w - M.r) / 2, y: hh - 4, "text-anchor": "middle" },
        "fill:var(--muted);font-size:11px")).textContent = cfg.x.label;
    }
    note(card, (cfg.note ? cfg.note + " " : "") + "Vertical rule = mean of the 3 runs; dots = individual runs.");
    tableView(card, ["Artifact", "run 0", "run 1", "run 2", "mean"],
      rows.map((r) => {
        const vv = r.values.filter((v) => v != null);
        return [r.label, ...r.values.map((v) => (cfg.x.format || fmt)(v)),
          vv.length ? (cfg.x.format || fmt)(vv.reduce((a, b) => a + b, 0) / vv.length) : "—"];
      }));
    return card;
  }

  // ============================================================== heatmap ==
  /* Spectrum occupancy: x = frequency, y = scan. Four states, valence-coded.
   * Segments come from the interval endpoints themselves — exact, not binned. */
  const STATE = {
    correct_free: { color: "--st-good", label: "Correctly called free" },
    unsafe: { color: "--st-critical", label: "Unsafe — called free, actually occupied" },
    missed: { color: "--st-warning", label: "Missed — free but not claimed" },
    correct_busy: { color: "--st-neutral", label: "Correctly left occupied" },
  };

  function segmentsFor(gt, rep, band) {
    const pts = new Set([band[0], band[1]]);
    for (const iv of gt) { pts.add(iv[0]); pts.add(iv[1]); }
    for (const iv of rep) { pts.add(iv[0]); pts.add(iv[1]); }
    const xs = [...pts].filter((v) => v >= band[0] && v <= band[1]).sort((a, b) => a - b);
    const inside = (ivs, m) => ivs.some((iv) => m >= iv[0] && m <= iv[1]);
    const out = [];
    for (let i = 0; i < xs.length - 1; i++) {
      const a = xs[i], b = xs[i + 1];
      if (b - a <= 1e-9) continue;
      const m = (a + b) / 2;
      const G = inside(gt, m), R = inside(rep, m);
      out.push([a, b, G && R ? "correct_free" : R ? "unsafe" : G ? "missed" : "correct_busy"]);
    }
    return out;
  }

  function heat(container, cfg) {
    const card = frame(container, cfg);
    const scans = cfg.scans, band = cfg.band;
    const w = cfg.width || 880;
    const rowH = cfg.rowH || 5;
    const hh = M.t + scans.length * rowH + M.b;
    const svg = plot(card, w, hh);
    const tp = tip(card);
    const xs = (v) => M.l + ((v - band[0]) / (band[1] - band[0])) * (w - M.l - M.r);
    const g = s("g");
    svg.appendChild(g);

    scans.forEach((sr, i) => {
      const y = M.t + i * rowH;
      for (const [a, b, st] of segmentsFor(sr.gt || [], sr.rep || [], band)) {
        const r = s("rect", { x: xs(a), y: y, width: Math.max(0.4, xs(b) - xs(a)), height: rowH - 0.6 },
          "fill:var(" + STATE[st].color + ")");
        g.appendChild(r);
        r.addEventListener("mousemove", (ev) => tp.show(
          '<div class="th">Scan ' + (sr.scan_idx + 1) + " · " + a.toFixed(1) + "–" + b.toFixed(1) + " MHz</div>" +
          '<div class="tr"><span class="sw" style="--sw:var(' + STATE[st].color + ')"></span>' + STATE[st].label + "</div>" +
          '<div class="tr">IoU this scan<b>' + fmt(sr.score, 3) + "</b></div>" +
          '<div class="tr">reported / true<b>' + sr.n_reported + " / " + sr.n_gt + "</b></div>", ev));
        r.addEventListener("mouseleave", tp.hide);
      }
    });
    for (const t of niceTicks(band[0], band[1], 8)) {
      g.appendChild(s("text", { x: xs(t), y: hh - M.b + 16, "text-anchor": "middle" },
        "fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums")).textContent = t;
    }
    g.appendChild(s("text", { x: (M.l + w - M.r) / 2, y: hh - 4, "text-anchor": "middle" },
      "fill:var(--muted);font-size:11px")).textContent = "Frequency (MHz)";
    for (const lbl of [0, 29, 59, 89]) {
      if (lbl >= scans.length) continue;
      g.appendChild(s("text", { x: M.l - 8, y: M.t + lbl * rowH + 4, "text-anchor": "end" },
        "fill:var(--muted);font-size:10px;font-variant-numeric:tabular-nums")).textContent = lbl + 1;
    }
    g.appendChild(s("text", { transform: "translate(14," + (M.t + scans.length * rowH / 2) + ") rotate(-90)", "text-anchor": "middle" },
      "fill:var(--muted);font-size:11px")).textContent = "Scan →";

    legend(card, Object.keys(STATE).map((k) => ({ name: STATE[k].label, color: STATE[k].color })));
    note(card, cfg.note);
    tableView(card, ["Scan", "IoU", "true free regions", "reported free regions", "unsafe MHz claimed", "free MHz missed"],
      scans.map((sr) => [sr.scan_idx + 1, fmt(sr.score, 3), sr.n_gt, sr.n_reported, fmt(sr.unsafe_bw, 1), fmt(sr.missed_bw, 1)]));
    return card;
  }

  // ================================================================= grid ==
  /* Per-instance outcome grid. cells[]: {label, state, tip} */
  function grid(container, cfg) {
    const card = frame(container, cfg);
    const rows = cfg.rows;
    const w = cfg.width || 880;
    const gap = 2;
    const x0 = cfg.labelWidth || 150;
    // Size cells to the available width so a 40-column grid never overflows.
    const nCols = Math.max(1, ...rows.map((r) => r.cells.length));
    const cell = Math.max(7, Math.min(26, Math.floor((w - x0 - 24) / nCols) - gap));
    const hh = rows.length * (cell + 14) + 30;
    const svg = plot(card, w, hh);
    const tp = tip(card);
    const g = s("g");
    svg.appendChild(g);
    rows.forEach((row, ri) => {
      const y = ri * (cell + 14) + 14;
      g.appendChild(s("text", { x: x0 - 10, y: y + cell / 2 + 4, "text-anchor": "end" },
        "fill:var(--text-2);font-size:11px")).textContent = row.label;
      row.cells.forEach((c, ci) => {
        const x = x0 + ci * (cell + gap);
        const r = s("rect", { x: x, y: y, width: cell, height: cell, rx: 3 },
          "fill:var(" + c.color + ")" + (c.faint ? ";opacity:.35" : ""));
        g.appendChild(r);
        r.addEventListener("mousemove", (ev) => tp.show(c.tip, ev));
        r.addEventListener("mouseleave", tp.hide);
      });
    });
    if (cfg.rule != null) {
      const rx = x0 + cfg.rule * (cell + gap) - gap / 2;
      g.appendChild(s("line", { x1: rx, x2: rx, y1: 4, y2: hh - 18 }, "stroke:var(--text-1);stroke-width:1"));
      g.appendChild(s("text", { x: rx + 5, y: hh - 6 }, "fill:var(--text-2);font-size:10px")).textContent = cfg.ruleLabel || "";
    }
    legend(card, cfg.legend || []);
    note(card, cfg.note);
    tableView(card, cfg.tableColumns, cfg.tableRows);
    return card;
  }

  window.V = { lines, bars, dots, heat, grid, fmt, pct, niceTicks, extent, segmentsFor, tableView, STATE };
})();
