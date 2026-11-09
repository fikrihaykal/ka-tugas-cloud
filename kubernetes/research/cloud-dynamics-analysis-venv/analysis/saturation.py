"""Saturasi resource per service pada tiap run terencana.

Keluaran (outputs/saturation/):
  per_run_service.csv   satu baris per (run, service) untuk window burst
  by_group.csv          median antar replikasi per (grup, service)
  onset.csv             urutan service yang menyentuh limit CPU relatif terhadap awal gagal
  heatmap.png           puncak utilisasi CPU pod tersibuk, service x grup
  timeline_<cell>.png   CPU pod tersibuk per service + request gagal per detik
"""
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "cloud-dynamics-experiments" / "results"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "cloud-dynamics-analysis-venv" / "outputs" / "saturation"
OUT.mkdir(parents=True, exist_ok=True)

# Limit dari release/kubernetes-manifests.yaml (milicore, MiB).
LIMITS = {
    "adservice": (300, 300), "cartservice": (300, 128), "checkoutservice": (200, 128),
    "currencyservice": (200, 128), "emailservice": (200, 128), "frontend": (200, 128),
    "paymentservice": (200, 128), "productcatalogservice": (200, 128),
    "recommendationservice": (200, 450), "redis-cart": (125, 256), "shippingservice": (200, 128),
}
SAT = 0.85          # pod dianggap menyentuh limit pada >= 85% limit CPU
SAT_SECONDS = 3     # dan bertahan beberapa detik berturut-turut


def service_of(pod):
    m = re.match(r"(.+?)-[a-z0-9]{8,10}-[a-z0-9]{5}$", pod)
    return m.group(1) if m else re.sub(r"-[a-z0-9]+$", "", pod)


def load_series(path, t0):
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame()
    df["pod"] = df["series"].str.replace("pod=", "", regex=False)
    df["service"] = df["pod"].map(service_of)
    df["t"] = (df["timestamp_epoch"] - t0 + 1).round().astype(int)
    return df.pivot_table(index="t", columns="pod", values="value", aggfunc="last")


def first_sustained(mask, start):
    """Detik pertama >= start dengan mask True selama SAT_SECONDS berturut-turut."""
    s = mask[mask.index >= start]
    run = s.astype(int).rolling(SAT_SECONDS).sum() >= SAT_SECONDS
    hit = run[run]
    return int(hit.index[0] - SAT_SECONDS + 1) if len(hit) else np.nan


def analyse(cell):
    run = RESULTS / cell["experiment_id"]
    wl = pd.read_csv(run / "workload.csv")
    t0 = wl["timestamp_epoch"].iloc[0] - wl["elapsed_s"].iloc[0] + 1
    wl["t"] = wl["elapsed_s"].round().astype(int)
    wl = wl.drop_duplicates("t").set_index("t")
    bs, bl = int(cell["burst_start"]), int(cell["burst_s"])
    cpu = load_series(run / "metrics" / "cpu_usage.csv", t0)
    mem = load_series(run / "metrics" / "memory_working_set.csv", t0)
    svc_of = {p: service_of(p) for p in cpu.columns}
    fail_t = wl.index[(wl["failed"] > 0) & (wl.index >= bs)]
    fail_onset = int(fail_t[0]) if len(fail_t) else np.nan
    rows = []
    for svc, (lim_m, lim_mi) in LIMITS.items():
        pods = [p for p in cpu.columns if svc_of[p] == svc]
        if not pods:
            continue
        util = cpu[pods] / (lim_m / 1000)
        win = util.loc[bs - 5: bs + bl + 60]
        pre = util.loc[max(bs - 60, 1): bs - 1]
        sat = (win >= SAT)
        busy = win.mean() > 0.10                      # pod yang benar-benar bekerja
        mean_pod = win.mean()[busy]
        mu = (mem[[p for p in mem.columns if svc_of.get(p, service_of(p)) == svc]] / (lim_mi * 1024 * 1024)).loc[bs - 5: bs + bl + 60]
        onset = first_sustained(sat.any(axis=1), bs - 5)
        rows.append({
            "cell": cell["cell"], "phase": cell["phase"], "setting": cell["setting"],
            "strategy": cell.get("strategy") or "static", "rep": cell["rep"], "service": svc,
            "cpu_limit_m": lim_m, "pods_seen": len(pods), "pods_busy": int(busy.sum()),
            "cpu_util_before": pre.mean().mean() if not pre.empty else np.nan,
            "cpu_util_peak_pod": win.max().max(),
            "cpu_util_mean_busy": mean_pod.mean() if len(mean_pod) else np.nan,
            "imbalance": (mean_pod.max() / mean_pod.mean()) if len(mean_pod) else np.nan,
            "pods_saturated_max": int(sat.sum(axis=1).max()),
            "sat_onset_s": onset - bs if not np.isnan(onset) else np.nan,
            "sat_seconds_any": int(sat.any(axis=1).sum()),
            "cpu_core_sum_peak": cpu[pods].loc[bs - 5: bs + bl + 60].sum(axis=1).max(),
            "mem_util_peak": mu.max().max() if mu.size else np.nan,
            "fail_onset_s": fail_onset - bs if not np.isnan(fail_onset) else np.nan,
            "fail_burst_pct": float(cell.get("fail_burst_pct") or np.nan),
        })
    return rows, (cpu, svc_of, wl, bs, bl)


def group_name(r):
    return f"{r['setting']}-{r['strategy']}"


def main():
    summary = pd.read_csv(RESULTS / "_plan" / "summary.csv").fillna("")
    summary = summary[summary["phase"].astype(str).isin(["2", "3"])]
    all_rows, cache = [], {}
    for _, c in summary.iterrows():
        cell = c.to_dict()
        cell["cell"] = c["cell"]
        cj = RESULTS / c["experiment_id"] / "cell.json"
        if cj.exists():
            cell.update({k: v for k, v in json.loads(cj.read_text()).items() if k not in ("cell",)})
        cell["cell"] = c["cell"]
        cell["strategy"] = c["strategy"] or ("cold" if str(c.get("cold")) == "True" else "")
        rows, data = analyse(cell)
        all_rows += rows
        cache[c["cell"]] = data
        print("ok", c["cell"], file=sys.stderr)
    df = pd.DataFrame(all_rows)
    df["group"] = df.apply(group_name, axis=1)
    df.to_csv(OUT / "per_run_service.csv", index=False)

    num = ["cpu_util_peak_pod", "cpu_util_mean_busy", "imbalance", "pods_busy", "pods_seen",
           "pods_saturated_max", "sat_onset_s", "sat_seconds_any", "mem_util_peak", "fail_burst_pct"]
    grp = df.groupby(["group", "service"])[num].median().round(3).reset_index()
    grp["n_runs"] = df.groupby(["group", "service"]).size().values
    grp.to_csv(OUT / "by_group.csv", index=False)

    # urutan jenuh per run: service menyentuh limit paling awal
    ons = df[df["sat_onset_s"].notna()].sort_values(["cell", "sat_onset_s"])
    ons[["cell", "group", "service", "sat_onset_s", "fail_onset_s", "pods_saturated_max", "pods_busy", "pods_seen", "imbalance"]].to_csv(OUT / "onset.csv", index=False)

    # heatmap
    piv = grp.pivot(index="service", columns="group", values="cpu_util_peak_pod")
    order = piv.max(axis=1).sort_values(ascending=False).index
    piv = piv.loc[order]
    fig, ax = plt.subplots(figsize=(1.1 * len(piv.columns) + 3, 5))
    im = ax.imshow(piv.values, cmap="YlOrRd", vmin=0, vmax=1.2, aspect="auto")
    ax.set_xticks(range(len(piv.columns)), piv.columns, rotation=40, ha="right")
    ax.set_yticks(range(len(piv.index)), piv.index)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, label="CPU pod tersibuk / limit (median antar run)")
    ax.set_title("Puncak utilisasi CPU pod tersibuk saat burst")
    fig.tight_layout()
    fig.savefig(OUT / "heatmap.png", dpi=150)
    plt.close(fig)

    # timeline untuk satu run per grup utama
    for cell in ("p3-hpa-cpu-r1", "p2-S1-4x-r1", "p3-prescale-r1"):
        if cell not in cache:
            continue
        cpu, svc_of, wl, bs, bl = cache[cell]
        top = df[df["cell"] == cell].sort_values("cpu_util_peak_pod", ascending=False)["service"].head(5)
        fig, (a, b) = plt.subplots(2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        for svc in top:
            pods = [p for p in cpu.columns if svc_of[p] == svc]
            a.plot(cpu.index - bs, (cpu[pods] / (LIMITS[svc][0] / 1000)).max(axis=1), label=svc)
        a.axhline(1, ls="--", c="grey")
        a.axvspan(0, bl, color="grey", alpha=0.15)
        a.set_ylabel("CPU pod tersibuk / limit")
        a.legend(fontsize=8)
        a.set_title(f"{cell}: 5 service paling jenuh")
        b.plot(wl.index - bs, wl["failed"], c="crimson")
        b.axvspan(0, bl, color="grey", alpha=0.15)
        b.set_ylabel("gagal/detik")
        b.set_xlabel("detik relatif terhadap burst mulai")
        b.set_xlim(-60, bl + 150)
        fig.tight_layout()
        fig.savefig(OUT / f"timeline_{cell}.png", dpi=150)
        plt.close(fig)
    print(f"selesai -> {OUT}")


if __name__ == "__main__":
    main()
