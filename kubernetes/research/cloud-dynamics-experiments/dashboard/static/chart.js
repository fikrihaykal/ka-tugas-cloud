const PAD = { left: 72, right: 16, top: 14, bottom: 36 };

export function createChart(canvas, tip) {
  const ctx = canvas.getContext("2d");
  let data = { elapsed: [], phases: [], series: [] };
  let hoverIndex = -1;
  let bitmap = { width: 0, height: 0, dpr: 0 };

  const observer = new ResizeObserver(() => draw());
  observer.observe(canvas.parentElement);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);

  function setData(next) {
    data = next;
    hoverIndex = -1;
    tip.hidden = true;
    draw();
  }

  function destroy() {
    observer.disconnect();
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerleave", onLeave);
  }

  function layout() {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 320;
    const height = canvas.clientHeight || 440;
    if (bitmap.width !== width || bitmap.height !== height || bitmap.dpr !== dpr) {
      bitmap = { width, height, dpr };
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return {
      width,
      height,
      plot: {
        x: PAD.left,
        y: PAD.top,
        w: Math.max(10, width - PAD.left - PAD.right),
        h: Math.max(10, height - PAD.top - PAD.bottom),
      },
    };
  }

  function draw() {
    const view = layout();
    const { width, height, plot } = view;
    ctx.clearRect(0, 0, width, height);
    const visible = data.series.filter((series) => series.on && hasNumber(series.values));
    const xDomain = domain(data.elapsed);

    drawPhases(plot, xDomain);
    if (!visible.length || !xDomain) {
      drawFrame(plot);
      ctx.fillStyle = "#777";
      ctx.font = "13px Liberation Sans, Segoe UI, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Centang minimal satu garis.", plot.x + plot.w / 2, plot.y + plot.h / 2);
      return;
    }

    const units = [...new Set(visible.map((series) => series.unit))];
    const shared = units.length === 1;
    const groupMax = maxByUnit(visible);
    const yMax = shared ? niceCeil(groupMax.get(units[0]) ?? 0) : 1;
    const toFraction = (series, value) => {
      const scale = shared ? yMax : groupMax.get(series.unit);
      return scale > 0 ? value / scale : 0;
    };
    drawGrid(plot, xDomain, yMax, shared ? visible[0].unit : "%");
    for (const series of visible) {
      strokeSeries(plot, xDomain, series, (value) => toFraction(series, value));
    }
    if (hoverIndex >= 0) drawHover(plot, xDomain, visible, toFraction);
    drawFrame(plot);
    ctx.fillStyle = "#333";
    ctx.font = "12px Liberation Sans, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("detik", plot.x + plot.w / 2, height - 6);
    ctx.save();
    ctx.translate(14, plot.y + plot.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(shared ? visible[0].unit : "0–100% tiap satuan", 0, 0);
    ctx.restore();
  }

  function drawPhases(plot, xDomain) {
    if (!xDomain) return;
    for (const phase of data.phases) {
      const x0 = xOf(plot, xDomain, phase.start);
      const x1 = xOf(plot, xDomain, phase.end);
      ctx.fillStyle = phase.fill;
      ctx.fillRect(x0, plot.y, x1 - x0, plot.h);
    }
  }

  function drawGrid(plot, xDomain, yMax, unit) {
    ctx.font = "11px Liberation Sans, Segoe UI, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const yTicks = unit === "%" ? [0, 0.25, 0.5, 0.75, 1] : ticks(0, yMax, 4);
    for (const tick of yTicks) {
      const y = plot.y + plot.h - (tick / yMax) * plot.h;
      ctx.strokeStyle = "#eee";
      ctx.beginPath();
      ctx.moveTo(plot.x, y);
      ctx.lineTo(plot.x + plot.w, y);
      ctx.stroke();
      ctx.fillStyle = "#444";
      ctx.fillText(unit === "%" ? `${Math.round(tick * 100)}%` : formatValue(tick, unit), plot.x - 8, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const tick of ticks(xDomain.min, xDomain.max, 6)) {
      const x = xOf(plot, xDomain, tick);
      ctx.strokeStyle = "#f3f3f3";
      ctx.beginPath();
      ctx.moveTo(x, plot.y);
      ctx.lineTo(x, plot.y + plot.h);
      ctx.stroke();
      ctx.fillStyle = "#444";
      ctx.fillText(formatNumber(tick, 0), x, plot.y + plot.h + 6);
    }
  }

  function drawFrame(plot) {
    ctx.strokeStyle = "#222";
    ctx.lineWidth = 1;
    ctx.strokeRect(plot.x + 0.5, plot.y + 0.5, plot.w, plot.h);
  }

  function strokeSeries(plot, xDomain, series, toUnit) {
    ctx.beginPath();
    ctx.strokeStyle = series.color;
    ctx.lineWidth = 1.7;
    ctx.lineJoin = "round";
    let drawing = false;
    series.values.forEach((value, index) => {
      if (value == null || !Number.isFinite(value)) {
        drawing = false;
        return;
      }
      const x = xOf(plot, xDomain, data.elapsed[index]);
      const y = plot.y + plot.h - toUnit(value) * plot.h;
      if (!drawing) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      drawing = true;
    });
    ctx.stroke();
  }

  function drawHover(plot, xDomain, visible, toFraction) {
    const elapsed = data.elapsed[hoverIndex];
    const x = xOf(plot, xDomain, elapsed);
    ctx.strokeStyle = "#999";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h);
    ctx.stroke();
    for (const series of visible) {
      const value = series.values[hoverIndex];
      if (value == null || !Number.isFinite(value)) continue;
      const t = toFraction(series, value);
      ctx.fillStyle = series.color;
      ctx.beginPath();
      ctx.arc(x, plot.y + plot.h - t * plot.h, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function onMove(event) {
    const view = {
      plot: {
        x: PAD.left,
        y: PAD.top,
        w: canvas.clientWidth - PAD.left - PAD.right,
        h: canvas.clientHeight - PAD.top - PAD.bottom,
      },
    };
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const inside = x >= view.plot.x && x <= view.plot.x + view.plot.w && y >= view.plot.y && y <= view.plot.y + view.plot.h;
    const xDomain = domain(data.elapsed);
    if (!inside || !xDomain || !data.elapsed.length) {
      onLeave();
      return;
    }
    const target = xDomain.min + ((x - view.plot.x) / view.plot.w) * (xDomain.max - xDomain.min);
    hoverIndex = nearest(data.elapsed, target);
    draw();
    showTip(event, visibleSeries());
  }

  function onLeave() {
    if (hoverIndex === -1 && tip.hidden) return;
    hoverIndex = -1;
    tip.hidden = true;
    draw();
  }

  function visibleSeries() {
    return data.series.filter((series) => series.on && hasNumber(series.values));
  }

  function showTip(event, series) {
    tip.replaceChildren();
    const head = document.createElement("strong");
    head.textContent = `detik ${formatNumber(data.elapsed[hoverIndex], 0)}`;
    tip.append(head);
    for (const item of series) {
      const row = document.createElement("div");
      row.className = "row";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = item.label;
      const value = document.createElement("span");
      value.textContent = formatValue(item.values[hoverIndex], item.unit);
      row.append(name, value);
      tip.append(row);
    }
    const parent = canvas.parentElement.getBoundingClientRect();
    tip.hidden = false;
    let left = event.clientX - parent.left + 14;
    let top = event.clientY - parent.top + 14;
    if (left + tip.offsetWidth > parent.width - 8) left = event.clientX - parent.left - tip.offsetWidth - 14;
    if (top + tip.offsetHeight > parent.height - 8) top = event.clientY - parent.top - tip.offsetHeight - 14;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }

  return { setData, destroy };
}

function hasNumber(values) {
  return values.some((value) => value != null && Number.isFinite(value));
}

function domain(elapsed) {
  if (!elapsed.length) return null;
  const min = elapsed[0] <= 2 ? 0 : elapsed[0];
  const max = elapsed[elapsed.length - 1];
  if (max <= min) return { min, max: min + 1 };
  return { min, max };
}

function xOf(plot, xDomain, value) {
  return plot.x + ((value - xDomain.min) / (xDomain.max - xDomain.min)) * plot.w;
}

function maxByUnit(seriesList) {
  const maxes = new Map();
  for (const series of seriesList) {
    let max = maxes.get(series.unit) ?? 0;
    for (const value of series.values) {
      if (value != null && value > max) max = value;
    }
    maxes.set(series.unit, max);
  }
  return maxes;
}

function niceCeil(value) {
  if (!(value > 0)) return 1;
  const padded = value * 1.08;
  const exp = 10 ** Math.floor(Math.log10(padded));
  const fraction = padded / exp;
  const steps = [1, 2, 2.5, 5, 10];
  const step = steps.find((item) => item + 1e-9 >= fraction) ?? 10;
  return step * exp;
}

function ticks(min, max, count) {
  const span = max - min || 1;
  const rough = span / count;
  const exp = 10 ** Math.floor(Math.log10(rough));
  const fraction = rough / exp;
  const step = (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * exp;
  const start = Math.ceil((min - step * 1e-9) / step) * step;
  const out = [];
  for (let value = start; value <= max + step * 1e-6; value += step) out.push(value);
  return out;
}

function nearest(elapsed, target) {
  let best = 0;
  let bestDist = Infinity;
  for (let index = 0; index < elapsed.length; index += 1) {
    const dist = Math.abs(elapsed[index] - target);
    if (dist < bestDist) {
      best = index;
      bestDist = dist;
    }
  }
  return best;
}

function formatNumber(value, digits) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (digits === 0) return String(Math.round(value));
  return value.toFixed(digits);
}

export function formatValue(value, unit) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (unit === "byte") return formatBytes(value, "");
  if (unit === "byte/detik") return formatBytes(value, "/s");
  if (unit === "core") return value.toFixed(4);
  if (unit === "pod") return String(Math.round(value));
  if (unit === "ms") return value >= 100 ? String(Math.round(value)) : value.toFixed(1);
  if (unit === "rasio") return value.toFixed(3);
  if (Math.abs(value) >= 100) return String(Math.round(value));
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(1);
}

function formatBytes(value, suffix) {
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1024 ** 2) return `${sign}${(abs / 1024 ** 2).toFixed(1)} MiB${suffix}`;
  if (abs >= 1024) return `${sign}${(abs / 1024).toFixed(1)} KiB${suffix}`;
  return `${sign}${abs.toFixed(0)} B${suffix}`;
}
