"""Fase 1 (step load): per tahap RPS, p95 dan gagal dari generator, serta utilisasi CPU pod tersibuk per service.

Keluaran (outputs/saturation/): step_levels.csv, step_service.png
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from saturation import LIMITS, OUT, RESULTS, load_series, service_of  # noqa: E402

rows = []
for cj in sorted(RESULTS.glob("step-*/cell.json")):
    cell = json.loads(cj.read_text())
    run = cj.parent
    wl = pd.read_csv(run / "workload.csv")
    t0 = wl["timestamp_epoch"].iloc[0] - wl["elapsed_s"].iloc[0] + 1
    wl["t"] = wl["elapsed_s"].round().astype(int)
    cpu = load_series(run / "metrics" / "cpu_usage.csv", t0)
    svc_of = {p: service_of(p) for p in cpu.columns}
    tier = int(cell["tier_s"])
    for i, rps in enumerate(cell["levels"]):
        a, b = i * tier + 1, (i + 1) * tier
        w = wl[(wl.t >= a) & (wl.t <= b)]
        tail = slice(a + tier // 3, b)  # abaikan sepertiga awal tahap (transisi)
        row = {"cell": cell["cell"], "setting": cell["setting"], "rep": cell["cell"][-1], "step": i,
               "rps": rps, "dir": "naik" if i <= len(cell["levels"]) // 2 else "turun",
               "p95_median": w["p95_latency_ms"].median(),
               "fail_pct": 100 * w["failed"].sum() / max(w["sent"].sum(), 1)}
        for svc, (lim, _) in LIMITS.items():
            pods = [p for p in cpu.columns if svc_of[p] == svc]
            u = (cpu.loc[tail][pods] / (lim / 1000)) if pods else pd.DataFrame()
            row[svc] = u.mean().max() if not u.empty else np.nan
        rows.append(row)
df = pd.DataFrame(rows)
df.to_csv(OUT / "step_levels.csv", index=False)

fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
up = df[df["dir"] == "naik"]
for ax, s in zip(axes, ["S1", "S2", "S3"]):
    d = up[up.setting == s].groupby("rps").median(numeric_only=True)
    for svc in ["currencyservice", "frontend", "cartservice", "adservice", "productcatalogservice"]:
        ax.plot(d.index, d[svc], marker="o", ms=3, label=svc)
    ax.axhline(1, ls="--", c="grey")
    ax.set_title(f"{s} ({ {'S1':15,'S2':36,'S3':67}[s] } pod)")
    ax.set_xlabel("RPS (tahap naik)")
axes[0].set_ylabel("CPU rata-rata pod tersibuk / limit")
axes[0].legend(fontsize=7)
fig.tight_layout()
fig.savefig(OUT / "step_service.png", dpi=150)
pd.set_option("display.width", 250)
print(up.groupby(["setting", "rps"])[["p95_median", "fail_pct", "currencyservice", "frontend", "cartservice"]].median().round(2).to_string())

fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8))
for s, col in zip(["S1", "S2", "S3"], ["#eb6834", "#2a78d6", "#3a9a5b"]):
    d = up[up.setting == s].groupby("rps").median(numeric_only=True)
    a.plot(d.index, d["p95_median"], marker="o", c=col, label=s)
    b.plot(d.index, d["currencyservice"], marker="o", c=col, label=s)
a.axhline(300, ls="--", c="grey"); a.set_yscale("log")
a.set_xlabel("RPS (tahap naik)"); a.set_ylabel("p95 median per tahap (ms, skala log)"); a.set_title("p95 dari sisi generator")
b.axhline(1, ls="--", c="grey")
b.set_xlabel("RPS (tahap naik)"); b.set_ylabel("CPU rata-rata pod currency tersibuk / limit"); b.set_title("currencyservice")
a.legend(); fig.tight_layout(); fig.savefig(OUT / "step_p95_vs_currency.png", dpi=150)
