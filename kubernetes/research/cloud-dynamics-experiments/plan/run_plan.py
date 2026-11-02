#!/usr/bin/env python3
"""Runs the experiment plan in docs/tugas-1/rencana-riset.md (phases 1-3), unattended.

Resumable: finished cells are kept in results/_plan/state.json and skipped on restart.
  python3 plan/run_plan.py            # everything
  python3 plan/run_plan.py --smoke    # one short cell per phase, to test the machinery
  python3 plan/run_plan.py --phases 1,2
"""
import argparse, csv, json, math, os, random, statistics, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
RES = EXP / "results"
MET = EXP.parent / "cloud-dynamics-metrics"
REPO = EXP.parents[2]
NS = "cloud-dynamics"
import shutil
if not shutil.which("kubectl"):
    os.environ["PATH"] = str(Path(__file__).resolve().parent / "bin") + os.pathsep + os.environ["PATH"]
HOST_IP = os.environ.get("HOST_IP", "127.0.0.1")
TARGET_HOST = f"online-boutique.{HOST_IP}.sslip.io"
URL = f"http://{TARGET_HOST}/"
SEED = 20261102

DEPLOYS = ["adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice", "frontend",
           "paymentservice", "productcatalogservice", "recommendationservice", "redis-cart", "shippingservice"]
BASE = {d: 1 for d in DEPLOYS}
SETTINGS = {
    "S1": {**BASE, "frontend": 5},
    "S2": {**BASE, "frontend": 8, "currencyservice": 10, "productcatalogservice": 5, "cartservice": 4, "adservice": 3},
    "S3": {**BASE, "frontend": 16, "currencyservice": 20, "productcatalogservice": 10, "cartservice": 8,
           "adservice": 6, "redis-cart": 2},
}
SLO_P95, SLO_FAIL = 300.0, 0.01
STEP_LEVELS = [10, 25, 50, 100, 150, 200, 150, 100, 50, 25, 10]

A = None            # parsed args
PLAN = None         # results/_plan (or _plan_smoke)
STATE = {}


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(PLAN / "plan.log", "a") as f:
        f.write(line + "\n")


def sh(cmd, check=True, capture=False, env=None, timeout=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), check=False, text=True, env=env, timeout=timeout,
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {cmd}\n{r.stdout or ''}")
    return r.stdout if capture else r.returncode


def save_state():
    (PLAN / ("state-smoke.json" if A.smoke else "state.json")).write_text(json.dumps(STATE, indent=2))


# ---------------------------------------------------------------- cluster helpers
def kubectl(*args, **kw):
    return sh(["kubectl", *args], **kw)


def sysctl_fix():
    for node in ("mylab99-control-plane", "mylab99-worker", "mylab99-worker2", "mylab99-worker3"):
        sh(["docker", "exec", "--privileged", node, "sysctl", "-w", "fs.inotify.max_user_instances=8192",
            "fs.inotify.max_user_watches=1048576"], check=False, capture=True)


def healthy():
    env = {**os.environ, "TARGET_HOST": TARGET_HOST}
    return subprocess.run([str(EXP / "scripts/check-environment.sh")], env=env, capture_output=True).returncode == 0


def ensure_healthy():
    for attempt in range(3):
        if healthy():
            return
        log(f"environment unhealthy, recovery attempt {attempt + 1}")
        sysctl_fix()
        kubectl("-n", "kube-system", "delete", "pod", "-l", "k8s-app=kube-proxy", check=False)
        kubectl("-n", "ingress-nginx", "delete", "pod", "-l", "app.kubernetes.io/component=controller", check=False)
        kubectl("-n", "ingress-nginx", "rollout", "status", "deploy/ingress-nginx-controller", "--timeout=180s", check=False)
        time.sleep(20)
    raise RuntimeError("environment still unhealthy after 3 recovery attempts")


def scale(setting, wait=True):
    for d, n in SETTINGS[setting].items():
        kubectl("-n", NS, "scale", f"deploy/{d}", f"--replicas={n}")
    if wait:
        for d in SETTINGS[setting]:
            kubectl("-n", NS, "rollout", "status", f"deploy/{d}", "--timeout=900s")


def replicas_str(setting):
    return setting + ":" + ",".join(f"{d}={n}" for d, n in SETTINGS[setting].items())


def warmup(rps, seconds):
    log(f"warm-up {seconds}s at {rps} RPS")
    sh([sys.executable, str(EXP / "loadgen/loadgen.py"), "--url", URL, "--profile", "constant", "--duration", str(seconds),
        "--rps", str(rps), "--discard-output", "--workers", "256"])


# ---------------------------------------------------------------- scenarios
def write_scn(name, lines):
    d = PLAN / "scenarios"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.env"
    p.write_text("\n".join(lines) + "\n")
    return p


def step_scenario(tier_s):
    steps = ",".join(f"{r}:{tier_s}" for r in STEP_LEVELS)
    return write_scn(f"step-{tier_s}s", ["PROFILE=step", f"DURATION={tier_s * len(STEP_LEVELS)}", f'STEPS="{steps}"',
                                          "WORKERS=1000"])


def burst_scenario(name, base, burst, start, burst_s, decay, tail):
    return write_scn(name, ["PROFILE=burst-flash-sale", f"DURATION={start + burst_s + decay + tail}", f"BASE_RPS={base}",
                            f"BURST_RPS={burst}", f"BURST_START={start}", f"BURST_DURATION={burst_s}",
                            f"DECAY_DURATION={decay}", f"WORKERS={min(2000, max(256, int(burst * 5)))}"])


# ---------------------------------------------------------------- one run
def run_experiment(scenario, setting_label, rep, on_start=None, warmup_seconds=None):
    env = {**os.environ, "TARGET_HOST": TARGET_HOST, "APPLICATION_NAME": "online-boutique",
           "APPLICATION_ARCHITECTURE": "online-boutique", "HOST_IP": HOST_IP, "REPLICATE": str(rep),
           "REPLICAS": setting_label}
    if warmup_seconds is not None:
        env["WARMUP_SECONDS"] = str(warmup_seconds)
    p = subprocess.Popen([str(EXP / "scripts/run-experiment.sh"), str(scenario)], env=env, text=True, bufsize=1,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    exp_id = None
    for line in p.stdout:
        line = line.rstrip()
        log("  | " + line)
        if line.startswith("Experiment ID"):
            exp_id = line.split(":", 1)[1].strip()
        if line.startswith("Measurement starts:") and on_start:
            threading.Thread(target=on_start, args=(int(line.split(":")[1]),), daemon=True).start()
    if p.wait() != 0 or not exp_id:
        raise RuntimeError(f"run-experiment failed rc={p.returncode}")
    return exp_id


def collect(exp_id):
    time.sleep(20)  # let Prometheus finish the last scrapes
    sh([str(MET / "scripts/collect-experiment.sh"), str(RES / exp_id), "online-boutique"])


def sleep_until(epoch):
    d = epoch - time.time()
    if d > 0:
        time.sleep(d)


def run_cell(cell_id, meta, scenario, setting, rep, *, warm=True, warm_rps=10, setup=None, on_start=None, cleanup=None):
    if cell_id in STATE["done"]:
        log(f"skip {cell_id} (done)")
        return STATE["done"][cell_id]
    log(f"=== CELL {cell_id} {json.dumps(meta)}")
    try:
        ensure_healthy()
        if meta.get("cold"):
            scale("S1")           # make sure the target pods are brand new
            scale(setting)
            time.sleep(15)
        else:
            scale(setting)
            if setup:
                setup()
            warmup(warm_rps, 15 if A.smoke else 120)
        exp_id = run_experiment(scenario, replicas_str(setting), rep, on_start=on_start,
                                warmup_seconds=1 if meta.get("cold") else None)
        collect(exp_id)
        (RES / exp_id / "cell.json").write_text(json.dumps({"cell": cell_id, **meta}, indent=2))
        STATE["done"][cell_id] = exp_id
        save_state()
        log(f"cell {cell_id} -> {exp_id}")
        return exp_id
    except Exception as e:
        log(f"CELL FAILED {cell_id}: {e}")
        STATE.setdefault("failed", {})[cell_id] = str(e)[:500]
        save_state()
        return None
    finally:
        if cleanup:
            try:
                cleanup()
            except Exception as e:
                log(f"cleanup error: {e}")
        time.sleep(10 if A.smoke else 20)


# ---------------------------------------------------------------- analysis
def load_rows(exp_id):
    rows = []
    with open(RES / exp_id / "workload.csv") as f:
        for r in csv.DictReader(f):
            ok, bad = int(r["success"]), int(r["failed"])
            rows.append({"t": float(r["elapsed_s"]), "rps": float(r["target_rps"]), "ok": ok, "bad": bad,
                         "p95": float(r["p95_latency_ms"])})
    return rows


def fail_frac(rs):
    n = sum(r["ok"] + r["bad"] for r in rs)
    return sum(r["bad"] for r in rs) / n if n else 0.0


def step_capacity(exp_id, tier_s):
    rows = load_rows(exp_id)
    res = []
    for i, level in enumerate(STEP_LEVELS):
        lo, hi = i * tier_s, (i + 1) * tier_s
        w = [r for r in rows if lo + 0.6 * tier_s <= r["t"] < hi]
        if not w:
            res.append(None)
            continue
        p95 = statistics.median(r["p95"] for r in w)
        ff = fail_frac(w)
        res.append({"level": level, "p95": p95, "fail": ff, "pass": p95 < SLO_P95 and ff < SLO_FAIL})
    n_up = STEP_LEVELS.index(max(STEP_LEVELS)) + 1
    up, down = res[:n_up], res[n_up:]
    cap = 0
    for r in up:
        if r and r["pass"]:
            cap = r["level"]
        else:
            break
    rec = 0                    # down-sweep: highest level L such that all levels <= L pass
    for r in reversed(down):
        if r and r["pass"]:
            rec = r["level"]
        else:
            break
    return {"capacity_up": cap, "recovered_level_down": rec, "steps": res}


def burst_metrics(exp_id, burst_start, burst_s):
    rows = load_rows(exp_id)
    b = [r for r in rows if burst_start <= r["t"] < burst_start + burst_s]
    lead = None
    for r in rows:
        if r["t"] < burst_start:
            continue
        w = [x for x in rows if r["t"] <= x["t"] <= r["t"] + 30]
        if all((x["p95"] < SLO_P95 or x["ok"] + x["bad"] == 0) and (x["bad"] / max(x["ok"] + x["bad"], 1)) < SLO_FAIL
               for x in w) and w and w[-1]["t"] >= r["t"] + 29:
            lead = r["t"] - burst_start
            break
    ok = sum(r["ok"] for r in rows)
    bad = sum(r["bad"] for r in rows)
    return {"fail_burst_pct": 100 * fail_frac(b), "p95_median_burst": statistics.median(r["p95"] for r in b) if b else None,
            "p95_max": max(r["p95"] for r in rows), "total_failed": bad, "total_ok": ok, "lead_time_s": lead}


def write_summary():
    out = []
    for cell_id, exp_id in STATE["done"].items():
        meta = json.loads((RES / exp_id / "cell.json").read_text())
        row = {"cell": cell_id, "experiment_id": exp_id, **{k: v for k, v in meta.items() if k != "cell"}}
        try:
            if meta.get("phase") == 0:
                rows = load_rows(exp_id)
                row.update(total_ok=sum(r["ok"] for r in rows), total_failed=sum(r["bad"] for r in rows),
                           fail_pct=100 * fail_frac(rows), p95_median=statistics.median(r["p95"] for r in rows),
                           p95_max=max(r["p95"] for r in rows))
            elif meta.get("phase") == 1:
                c = step_capacity(exp_id, meta["tier_s"])
                row.update(capacity_up=c["capacity_up"], recovered_level_down=c["recovered_level_down"])
            else:
                row.update(burst_metrics(exp_id, meta["burst_start"], meta["burst_s"]))
        except Exception as e:
            row["error"] = str(e)
        out.append(row)
    keys = sorted({k for r in out for k in r}, key=lambda k: (k not in ("cell", "experiment_id", "phase"), k))
    with open(PLAN / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)


# ---------------------------------------------------------------- phases
def phase0():
    """Baseline: burst-flash-sale only: scenarios/burst-flash-sale.env plus the 10->400 variant from panduan.md."""
    flash_old = burst_scenario("burst-flash-sale-10-400", 10, 400, 120, 60, 360, 60)
    runs = [("burst-flash-sale", EXP / "scenarios/burst-flash-sale.env", 1), ("burst-flash-sale-10-400", flash_old, 1)]
    cells = [(n, p, r) for n, p, reps in runs for r in range(1, reps + 1)]
    random.Random(SEED + 9).shuffle(cells)
    if A.smoke:
        cells = cells[:1]
    for name, path, r in cells:
        run_cell(f"p0-{name}-r{r}", {"phase": 0, "profile": name, "setting": "S1", "rep": r}, path, "S1", r, warm_rps=10)
    write_summary()


def phase1():
    tier = 8 if A.smoke else 60
    scn = step_scenario(tier)
    cells = [(s, r) for s in ("S1", "S2", "S3") for r in (1, 2)]
    random.Random(SEED).shuffle(cells)
    if A.smoke:
        cells = cells[:1]
    for s, r in cells:
        run_cell(f"p1-{s}-r{r}", {"phase": 1, "setting": s, "tier_s": tier, "levels": STEP_LEVELS}, scn, s, r)
    caps = {}
    for s in ("S1", "S2", "S3"):
        vals = []
        for r in (1, 2):
            eid = STATE["done"].get(f"p1-{s}-r{r}")
            if eid:
                vals.append(step_capacity(eid, tier))
        if vals:
            caps[s] = {"capacity_up": [v["capacity_up"] for v in vals],
                       "recovered_level_down": [v["recovered_level_down"] for v in vals]}
    STATE["capacity"] = caps
    c1 = caps.get("S1", {}).get("capacity_up", [10])
    L0 = max(10, min(c1) if c1 else 10)
    L0 = min(L0, 150)                    # 4*L0 must stay within what the single-process generator can offer
    STATE["L0"] = L0
    save_state()
    log(f"PHASE 1 done. capacity={json.dumps(caps)} -> L0={L0}")


def burst_cell_scn(L0, mult, start=120, decay=360):
    s = 6 if A.smoke else None
    if A.smoke:
        return burst_scenario(f"burst-smoke-{mult}x", L0, mult * L0, 12, 8, 16, 6), 12, 8
    return burst_scenario(f"burst-{L0}x{mult}-b{start}", L0, mult * L0, start, 60, decay, 60), start, 60


def phase2():
    L0 = STATE["L0"]
    cells = []
    for s in ("S1", "S2", "S3"):
        for m in (4,):
            for r in (1, 2, 3):
                cells.append((f"p2-{s}-{m}x-r{r}", s, m, r, False))
    for r in (1, 2, 3):                       # warm comparison = the regular S2-4x cells (same protocol)
        cells.append((f"p2-S2-4x-cold-r{r}", "S2", 4, r, True))
    random.Random(SEED + 2).shuffle(cells)
    if A.smoke:
        cells = [c for c in cells if c[4]][:1] + cells[:1]
    for cid, s, m, r, cold in cells:
        scn, bs, bd = burst_cell_scn(L0, m)
        run_cell(cid, {"phase": 2, "setting": s, "mult": m, "L0": L0, "cold": cold, "rep": r,
                       "burst_start": bs, "burst_s": bd}, scn, s, r, warm_rps=min(25, L0))
    write_summary()


def best_target():
    rows = {}
    for cid, eid in STATE["done"].items():
        m = json.loads((RES / eid / "cell.json").read_text())
        if m.get("phase") == 2 and m["mult"] == 4 and not m["cold"]:
            rows.setdefault(m["setting"], []).append(burst_metrics(eid, m["burst_start"], m["burst_s"]))
    for s in ("S2", "S3"):
        rs = rows.get(s)
        if rs and statistics.median(r["fail_burst_pct"] for r in rs) < 1 and statistics.median(r["p95_median_burst"] for r in rs) < SLO_P95:
            return s
    return "S3"


def install_metrics_server():
    if subprocess.run(["kubectl", "get", "apiservice", "v1beta1.metrics.k8s.io"], capture_output=True).returncode == 0:
        return True
    log("installing metrics-server")
    try:
        sh("kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml")
        sh(["kubectl", "-n", "kube-system", "patch", "deploy", "metrics-server", "--type=json", "-p",
            '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'])
        sh(["kubectl", "-n", "kube-system", "rollout", "status", "deploy/metrics-server", "--timeout=300s"])
        time.sleep(60)
        sh(["kubectl", "top", "nodes"])
        return True
    except Exception as e:
        log(f"metrics-server install failed: {e}")
        return False


def install_keda():
    if subprocess.run(["kubectl", "get", "ns", "keda"], capture_output=True).returncode == 0:
        return True
    log("installing KEDA")
    try:
        sh("helm repo add kedacore https://kedacore.github.io/charts && helm repo update")
        sh("helm install keda kedacore/keda -n keda --create-namespace --wait --timeout 10m")
        return True
    except Exception as e:
        log(f"KEDA install failed: {e}")
        return False


def clear_autoscalers():
    kubectl("-n", NS, "delete", "hpa", "--all", check=False, capture=True)
    kubectl("-n", NS, "delete", "scaledobject", "--all", check=False, capture=True)


def hpa_cpu_setup(target):
    def f():
        for d in DEPLOYS:
            lo, hi = SETTINGS["S1"][d], SETTINGS[target][d]
            if hi > lo:
                kubectl("-n", NS, "autoscale", "deploy", d, f"--min={lo}", f"--max={hi}", "--cpu-percent=50")
    return f


def keda_setup(target, L0):
    def f():
        for d in DEPLOYS:
            lo, hi = SETTINGS["S1"][d], SETTINGS[target][d]
            if hi <= lo:
                continue
            thr = max(1, round(4 * L0 / hi))
            yaml = f"""apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: {{name: {d}, namespace: {NS}}}
spec:
  scaleTargetRef: {{name: {d}}}
  minReplicaCount: {lo}
  maxReplicaCount: {hi}
  pollingInterval: 5
  cooldownPeriod: 120
  triggers:
  - type: prometheus
    metadata:
      serverAddress: http://monitoring-kube-prometheus-prometheus.monitoring.svc:9090
      query: sum(rate(nginx_ingress_controller_requests{{ingress="online-boutique"}}[30s]))
      threshold: "{thr}"
"""
            subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml, text=True, check=True)
    return f


def phase3():
    L0 = STATE["L0"]
    T = best_target()
    STATE["target_setting"] = T
    save_state()
    log(f"PHASE 3: base=S1, burst 4x L0={L0}, target setting {T}")
    start = 20 if A.smoke else 240
    if A.smoke:
        scn, bs, bd = burst_scenario("burst-smoke-p3", L0, 4 * L0, start, 8, 16, 6), start, 8
        lead_pre, lead_warm = 6, 12
    else:
        scn, bs, bd = burst_scenario(f"burst-{L0}x4-b{start}", L0, 4 * L0, start, 60, 360, 60), start, 60
        lead_pre, lead_warm = 60, 180

    def scheduled(lead):
        def on_start(epoch):
            sleep_until(epoch + start - lead)
            log(f"scheduled pre-scale to {T} ({lead}s before burst)")
            scale(T, wait=False)
        return on_start

    strategies = {
        "prescale": dict(on_start=scheduled(lead_pre)),
        "prescale-warm": dict(on_start=scheduled(lead_warm)),
    }
    if A.allow_install and install_metrics_server():
        strategies["hpa-cpu"] = dict(setup=hpa_cpu_setup(T))
    else:
        log("SKIPPED hpa-cpu (needs metrics-server; run with --allow-install)")
    if A.allow_install and install_keda():
        strategies["keda-rps"] = dict(setup=keda_setup(T, L0))
    else:
        log("SKIPPED keda-rps (needs KEDA; run with --allow-install)")

    cells = [(n, r) for n in strategies for r in (1, 2, 3)]
    random.Random(SEED + 3).shuffle(cells)
    if A.smoke:
        cells = cells[:1]
    for n, r in cells:
        kw = strategies[n]
        run_cell(f"p3-{n}-r{r}", {"phase": 3, "strategy": n, "setting": "S1", "target": T, "mult": 4, "L0": L0,
                                  "rep": r, "burst_start": bs, "burst_s": bd},
                 scn, "S1", r, warm_rps=min(25, L0), setup=kw.get("setup"), on_start=kw.get("on_start"),
                 cleanup=lambda: (clear_autoscalers(), scale("S1", wait=False)))
    write_summary()


def main():
    global A, PLAN, STATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--phases", default="0,1,2,3")
    ap.add_argument("--allow-install", action="store_true",
                    help="allow installing metrics-server and KEDA from the internet (needed for hpa-cpu and keda-rps)")
    A = ap.parse_args()
    PLAN = RES / ("_plan_smoke" if A.smoke else "_plan")
    PLAN.mkdir(parents=True, exist_ok=True)
    sf = PLAN / ("state-smoke.json" if A.smoke else "state.json")
    STATE = json.loads(sf.read_text()) if sf.exists() else {"done": {}}
    log(f"plan start smoke={A.smoke} phases={A.phases} seed={SEED}")
    sysctl_fix()
    ensure_healthy()
    phases = A.phases.split(",")
    if "0" in phases:
        phase0()
    if "1" in phases:
        phase1()
    if "2" in phases:
        phase2()
    if "3" in phases:
        phase3()
    write_summary()
    log(f"ALL DONE. done={len(STATE['done'])} failed={len(STATE.get('failed', {}))} summary={PLAN / 'summary.csv'}")


if __name__ == "__main__":
    main()
