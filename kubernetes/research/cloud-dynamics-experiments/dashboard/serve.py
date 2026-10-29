#!/usr/bin/env python3
"""Dashboard lokal untuk grafik hasil workload experiment.

Jalankan dari mana saja:

    python3 dashboard/serve.py

Lalu buka http://127.0.0.1:8770/
"""

import argparse
import csv
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT.parent / "results"
STATIC = ROOT / "static"

# Urutan ini yang tampil di checkbox. `on` = garis yang nyala saat run dibuka.
# success_roll10 dihitung di sini, sama seperti gambar di laporan (rata-rata 10 detik).
SPECS = [
    ("target_rps", "target", "request/detik", "#1f4e79", True),
    ("success_roll10", "berhasil, rata-rata 10 dtk", "request/detik", "#c0392b", True),
    ("CPU_USAGE", "CPU namespace", "core", "#148f4b", True),
    ("success", "berhasil, mentah", "request/detik", "#e67e22", False),
    ("sent", "terkirim", "request/detik", "#7f8c8d", False),
    ("failed", "gagal", "request/detik", "#8e44ad", False),
    ("achieved_rps", "achieved", "request/detik", "#2980b9", False),
    ("mean_latency_ms", "latency rata-rata", "ms", "#d35400", False),
    ("p95_latency_ms", "latency p95", "ms", "#6c3483", False),
    ("MEMORY_WORKING_SET", "memori working set", "byte", "#16a085", False),
    ("NETWORK_RX", "network masuk", "byte/detik", "#1abc9c", False),
    ("NETWORK_TX", "network keluar", "byte/detik", "#0e6655", False),
    ("RESTARTS", "restart", "pod", "#922b21", False),
    ("READY_PODS", "pod Ready", "pod", "#1a5276", False),
    ("CPU_THROTTLED", "CPU throttled", "core", "#b7950b", False),
    ("LINKERD_REQUEST_RATE", "Linkerd request rate", "request/detik", "#5d6d7e", False),
    ("LINKERD_SUCCESS_RATE", "Linkerd success rate", "rasio", "#117a65", False),
    ("LINKERD_LATENCY_P95", "Linkerd latency p95", "ms", "#a04000", False),
]

ROLL_WINDOW = 10
RUN_ID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def read_json(path):
    if not path.is_file():
        return {}
    with path.open() as f:
        return json.load(f)


def read_env(path):
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def read_table(path):
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows or "elapsed_s" not in rows[0]:
        raise ValueError(f"{path.name} kosong atau tanpa elapsed_s")
    elapsed = []
    columns = {key: [] for key in rows[0] if key not in ("timestamp_epoch", "elapsed_s")}
    for row in rows:
        elapsed.append(float(row["elapsed_s"]))
        for key, values in columns.items():
            raw = (row.get(key) or "").strip()
            if raw == "":
                values.append(None)
            else:
                values.append(float(raw))
    kept = {}
    for key, values in columns.items():
        if any(v is not None for v in values):
            kept[key] = values
    return elapsed, kept


def rolling_mean(values, window):
    """Rata-rata bergerak ke belakang. Slot kosong tidak masuk pembilang."""
    out = []
    buf = []
    total = 0.0
    count = 0
    for value in values:
        buf.append(value)
        if value is not None:
            total += value
            count += 1
        if len(buf) > window:
            old = buf.pop(0)
            if old is not None:
                total -= old
                count -= 1
        out.append(total / count if count else None)
    return out


def phases_for(env, elapsed):
    if not elapsed:
        return []
    duration = float(env.get("DURATION") or elapsed[-1])
    profile = env.get("PROFILE", "")
    try:
        if profile == "burst-flash-sale":
            start = float(env["BURST_START"])
            peak_end = start + float(env["BURST_DURATION"])
            decay_end = peak_end + float(env["DECAY_DURATION"])
            spans = [
                (0, start, "#f4f4f4"),
                (start, peak_end, "#fdecec"),
                (peak_end, decay_end, "#fff4e5"),
                (decay_end, duration, "#f4f4f4"),
            ]
        elif profile == "burst":
            start = float(env["BURST_START"])
            peak_end = start + float(env["BURST_DURATION"])
            spans = [
                (0, start, "#f4f4f4"),
                (start, peak_end, "#fdecec"),
                (peak_end, duration, "#f4f4f4"),
            ]
        else:
            return []
    except (KeyError, ValueError):
        return []
    return [
        {"start": start, "end": end, "fill": fill}
        for start, end, fill in spans
        if end > start
    ]


def profile_from_name(name):
    match = re.match(r"(.+)-\d{8}T", name)
    return match.group(1) if match else name


def list_runs():
    runs = []
    if not RESULTS.is_dir():
        return runs
    for folder in RESULTS.iterdir():
        if not folder.is_dir() or not (folder / "workload.csv").is_file():
            continue
        meta = read_json(folder / "metadata.json")
        runs.append(
            {
                "id": folder.name,
                "profile": meta.get("profile") or profile_from_name(folder.name),
                "has_combined": (folder / "combined.csv").is_file(),
                "mtime": folder.stat().st_mtime,
            }
        )
    runs.sort(key=lambda run: run["mtime"], reverse=True)
    for run in runs:
        del run["mtime"]
    return runs


def load_run(run_id):
    if not run_id or any(ch not in RUN_ID_OK for ch in run_id):
        raise ValueError("id run tidak valid")
    folder = RESULTS / run_id
    source_name = "combined.csv" if (folder / "combined.csv").is_file() else "workload.csv"
    source = folder / source_name
    if not source.is_file():
        raise FileNotFoundError(run_id)
    elapsed, columns = read_table(source)
    if "success" in columns:
        columns["success_roll10"] = rolling_mean(columns["success"], ROLL_WINDOW)
    meta = read_json(folder / "metadata.json")
    env = read_env(folder / "scenario.env")
    series = []
    for key, label, unit, color, on in SPECS:
        values = columns.get(key)
        if values is None:
            continue
        series.append(
            {
                "id": key,
                "label": label,
                "unit": unit,
                "color": color,
                "on": on,
                "values": values,
            }
        )
    return {
        "id": run_id,
        "profile": meta.get("profile") or env.get("PROFILE") or "",
        "application": (meta.get("application") or {}).get("name") or "",
        "source": source_name,
        "elapsed": elapsed,
        "phases": phases_for(env, elapsed),
        "series": series,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/runs":
            return self._json(list_runs())
        prefix = "/api/runs/"
        if path.startswith(prefix):
            try:
                return self._json(load_run(path[len(prefix) :]))
            except FileNotFoundError:
                return self._json({"error": "run tidak ketemu"}, 404)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
        return super().do_GET()

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Dashboard grafik hasil workload experiment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
