import { createChart } from "./chart.js";

const runSelect = document.querySelector("#run");
const meta = document.querySelector("#meta");
const seriesBox = document.querySelector("#series");
const note = document.querySelector("#note");
const chart = createChart(document.querySelector("#chart"), document.querySelector("#tip"));

let current = null;

runSelect.addEventListener("change", () => {
  loadRun(runSelect.value).catch(showError);
});

boot().catch(showError);

async function boot() {
  const runs = await fetch("/api/runs").then(readJson);
  if (!runs.length) {
    meta.textContent = "Belum ada folder results yang berisi workload.csv.";
    return;
  }
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = run.id;
    option.textContent = run.id;
    runSelect.append(option);
  }
  const preferred = runs.find((run) => run.has_combined) ?? runs[0];
  runSelect.value = preferred.id;
  await loadRun(preferred.id);
}

async function loadRun(id) {
  current = await fetch(`/api/runs/${encodeURIComponent(id)}`).then(readJson);
  const bits = [current.profile, current.application, current.source].filter(Boolean);
  meta.textContent = bits.join(" · ");
  renderSeries();
  chart.setData(current);
  renderNote();
}

function renderSeries() {
  seriesBox.replaceChildren();
  for (const series of current.series) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = series.on;
    input.addEventListener("change", () => {
      series.on = input.checked;
      chart.setData(current);
      renderNote();
    });
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = series.color;
    const text = document.createElement("span");
    text.textContent = `${series.label} · ${series.unit}`;
    label.append(input, swatch, text);
    seriesBox.append(label);
  }
}

function renderNote() {
  const visible = current.series.filter((series) => series.on);
  const units = [...new Set(visible.map((series) => series.unit))];
  if (!visible.length) {
    note.textContent = "Centang garis yang mau ditampilkan.";
    return;
  }
  const scale = units.length === 1
    ? `Sumbu Y memakai satuan ${units[0]}.`
    : "Tiap satuan digambar dari 0 sampai nilai tertingginya sendiri, jadi target dan berhasil tetap satu skala. Arahkan kursor untuk angka asli.";
  const bands = current.phases.length
    ? " Pita latar: abu-abu beban dasar, merah muda puncak, oranye penurunan."
    : "";
  note.textContent = scale + bands;
}

async function readJson(response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function showError(error) {
  meta.textContent = error.message || String(error);
}
