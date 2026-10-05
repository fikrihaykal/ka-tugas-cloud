# Workload Experiments

Assumes:

- a running kind cluster named `mylab99` (from Modul 6),
- ingress-nginx is already installed,
- Prometheus is reachable at `http://prometheus.127.0.0.1.sslip.io` (or your `HOST_IP`),
- the experiment application is reachable at `http://experiment.127.0.0.1.sslip.io`.

Prefer deploying the app via `../app-sample` (`build-load.sh` + `deploy.sh`). The manifest here (`k8s/experiment-app.yaml`) is an alternate copy with the same Ingress host.

## 1. Install local Python dependencies

```sh
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

## 2. Deploy the experiment application

Create the namespace if needed:

```sh
kubectl create namespace cloud-exp --dry-run=client -o yaml | kubectl apply -f -
```

Build/load the image as `experiment-app:v1` into `mylab99`, then:

```sh
kubectl apply -f k8s/experiment-app.yaml
kubectl get pods -n cloud-exp
curl http://experiment.127.0.0.1.sslip.io/
```

## 3. Verify Prometheus

```sh
curl http://prometheus.127.0.0.1.sslip.io/-/healthy
curl -sG 'http://prometheus.127.0.0.1.sslip.io/api/v1/query' \
  --data-urlencode 'query=up'
```

## 4. What you measure (monitoring)

Every Locust run merges **client-side** and **cluster-side** signals into one CSV.

| Layer | Source | What to watch | Why it matters |
|---|---|---|---|
| Performance | Locust (`locust_stats*.csv`) | `throughput_rps`, `latency_p50/p95/p99`, `failure_rate` | User-visible quality under load |
| Resource | Prometheus (`prometheus.csv`) | `cpu_cores`, `memory_bytes`, `network_rx/tx_bytes_s` | How hard the pod works |
| Capacity | Prometheus + kubectl | `replicas`, `ready_replicas`, pod Restarts | Whether the Deployment stays healthy |
| Cluster UI | Grafana / Octant | CPU/mem charts, pod events | Quick visual check while a run is live |

Suggested PromQL (already used by `export-prometheus.py`):

- CPU: `sum(rate(container_cpu_usage_seconds_total{namespace="cloud-exp",...}[30s]))`
- Memory: `sum(container_memory_working_set_bytes{namespace="cloud-exp",...})`
- Network RX/TX rates on the app pods
- Deployment replica / available replica gauges

Live checks during a run:

```sh
kubectl get pods -n cloud-exp -w
kubectl top pod -n cloud-exp
curl -sG 'http://prometheus.127.0.0.1.sslip.io/api/v1/query' \
  --data-urlencode \
  'query=sum(rate(container_cpu_usage_seconds_total{namespace="cloud-exp",container="app"}[1m]))'
```

**Rule for fair comparison:** keep warmup, measurement window, spawn rate, image tag, resource requests/limits, and replica count **constant** unless that knob is the independent variable of the scenario.

## 5. Experiment menu (possible scenarios)

Default Locust task hits **`/cpu`** (`workload/locustfile.py`). App endpoints from `app-sample`:

| Path | Behavior | Good for |
|---|---|---|
| `/` | cheap OK response | baseline / control traffic |
| `/cpu` | tight CPU loop (~2e6 iters) | Workload → Resource / Performance |
| `/sleep` | fixed 50 ms wait | latency-bound / concurrency queueing |
| `/health` | probe target | readiness noise check (not primary load) |

Knobs you can change **one at a time**:

| Knob | How | Notes |
|---|---|---|
| Locust users | `./scripts/run-experiment.sh <run_id> <users>` | primary workload level |
| Spawn rate | `SPAWN_RATE=5` | ramp speed into steady state |
| Warmup / measure / cooldown | `WARMUP_SECONDS`, `MEASUREMENT_SECONDS`, `COOLDOWN_SECONDS` | defaults 60 / 300 / 30 |
| Endpoint mix | edit `workload/locustfile.py` | `/cpu` vs `/sleep` vs `/` |
| Replicas | `kubectl scale deploy/experiment-app -n cloud-exp --replicas=N` | horizontal capacity |
| CPU/mem limits | edit Deployment `resources` then re-apply | vertical capacity |
| Manual burst | `../app-sample/scripts/manual-load.sh` | quick sanity, not full dataset |

### Menu A — Workload sweep (recommended first)

**Question:** as concurrent users rise, how do CPU/mem and latency/RPS change?

**Fix:** 1 replica, default limits (`cpu` 100m–1, `memory` 128Mi–512Mi), Locust → `/cpu`.

**Vary:** users only.

```sh
./scripts/run-experiment.sh run01 10
./scripts/run-experiment.sh run02 20
./scripts/run-experiment.sh run03 40
./scripts/run-experiment.sh run04 80
```

**Expect:** CPU climbs toward the limit; p95/p99 latency and/or `failure_rate` rise after saturation.

**Interpret:** `Workload → Resource` and `Workload → Performance`.

### Menu B — Saturation / breaking point

**Question:** at what user level does the app stop being “healthy”?

**Fix:** same as Menu A.

**Vary:** keep increasing users (e.g. 100, 160, 240) until `failure_rate` or latency explodes, or pods restart.

```sh
MEASUREMENT_SECONDS=180 ./scripts/run-experiment.sh run-sat-100 100
MEASUREMENT_SECONDS=180 ./scripts/run-experiment.sh run-sat-160 160
```

**Watch:** Locust failures, `ready_replicas` dips, `kubectl describe pod` / Octant events.

### Menu C — Replica scaling (horizontal)

**Question:** does more replicas improve throughput / latency at a **fixed** load?

**Fix:** users = one saturated-but-alive level from Menu A/B (example: 40).

**Vary:** replicas `1 → 2 → 3`.

```sh
kubectl scale deployment experiment-app -n cloud-exp --replicas=1
./scripts/run-experiment.sh run-rep1 40

kubectl scale deployment experiment-app -n cloud-exp --replicas=2
./scripts/run-experiment.sh run-rep2 40

kubectl scale deployment experiment-app -n cloud-exp --replicas=3
./scripts/run-experiment.sh run-rep3 40
```

**Watch:** per-pod CPU vs aggregate CPU, RPS, p95, `ready_replicas`.

**Interpret:** `Resource → Performance` (capacity via replicas).

### Menu D — CPU limit (vertical)

**Question:** with the same load, how does a tighter CPU limit change performance?

**Fix:** users + replicas constant (example: 40 users, 1 replica).

**Vary:** Deployment `resources.limits.cpu` (e.g. `250m` / `500m` / `1`), rebuild not needed — edit + `kubectl apply`, wait Ready, then run.

```sh
# after each limit change + Ready:
./scripts/run-experiment.sh run-cpu250 40
./scripts/run-experiment.sh run-cpu500 40
./scripts/run-experiment.sh run-cpu1000 40
```

**Watch:** `cpu_cores` plateau near the limit, latency climb under throttle.

**Interpret:** `Resource → Performance`.

### Menu E — Endpoint character (`/cpu` vs `/sleep` vs `/`)

**Question:** does “heavy CPU work” behave differently from “just waiting” under the same user count?

**Fix:** users (e.g. 40), 1 replica, default limits.

**Vary:** Locust task path only (edit `locustfile.py`, one endpoint per run series).

| Run series | Task path | Typical signal |
|---|---|---|
| E1 | `/cpu` | high CPU, latency tied to compute |
| E2 | `/sleep` | lower CPU, latency ≥ ~50 ms + queueing |
| E3 | `/` | low CPU, high RPS ceiling |

**Interpret:** workload type matters; don’t mix endpoints inside one comparative series.

### Menu F — Duration sensitivity (optional method check)

**Question:** is 60s measurement enough, or do metrics stabilize only after 5 minutes?

**Fix:** users = mid level (e.g. 40).

**Vary:** `MEASUREMENT_SECONDS` only (120 vs 300 vs 600).

```sh
MEASUREMENT_SECONDS=120 ./scripts/run-experiment.sh run-dur120 40
MEASUREMENT_SECONDS=300 ./scripts/run-experiment.sh run-dur300 40
```

Use this to justify your chosen window, not as the main research claim.

### Menu G — Smoke / manual (no full Locust pipeline)

Quick checks before a long run:

```sh
../app-sample/scripts/verify.sh
REQUESTS=50 ../app-sample/scripts/manual-load.sh
```

Good for “is Ingress/Prometheus alive?”, not for Level-3 dataset claims.

### Suggested path for Modul 6 report

1. **Menu A** (core) — 4 workload levels.
2. Pick **one** of Menu C or D — show that capacity (replicas or CPU limit) changes the outcome.
3. Optional: Menu E or B if you need a richer discussion.

Do **not** try every menu in one lab session; each full measurement is ~warmup + 5 min + cooldown.

## 6. Run experiments (commands)

```sh
./scripts/run-experiment.sh run01 10
./scripts/run-experiment.sh run02 20
./scripts/run-experiment.sh run03 40
./scripts/run-experiment.sh run04 80
```

Environment variables can override defaults:

```sh
APP_HOST=http://experiment.127.0.0.1.sslip.io \
PROM_HOST=http://prometheus.127.0.0.1.sslip.io \
MEASUREMENT_SECONDS=300 \
./scripts/run-experiment.sh run05 100
```

## 7. Output

Each run produces raw files under:

```text
data/raw/<run_id>/
```

and a processed Level-3 dataset under:

```text
data/processed/<run_id>.csv
```

Typical columns include:

- timestamp
- run_id
- workload_level
- request_rate
- throughput_rps
- latency_mean_ms
- latency_p50_ms
- latency_p95_ms
- latency_p99_ms
- failure_rate
- error_fraction
- cpu_cores
- memory_bytes
- network_rx_bytes_s
- network_tx_bytes_s
- replicas
- ready_replicas

## 8. Research interpretation

The dataset supports analysis of:

`Workload -> Resource`

`Workload -> Performance`

`Resource -> Performance`

Keep warm-up, measurement duration, resource limits, image version, and Prometheus step constant when comparing workload levels.
