# App Sample

Deploy a small Flask/Gunicorn app into the lab kind cluster (`mylab99`).

Default assumptions:

- kind cluster name: `mylab99` (override with `KIND_CLUSTER`)
- application namespace: `cloud-exp`
- application image: `experiment-app:v1`
- Ingress class: `nginx`
- Host IP for sslip.io (same as Prometheus script): `127.0.0.1`
- application endpoint: `http://experiment.127.0.0.1.sslip.io`
- Prometheus endpoint: `http://prometheus.127.0.0.1.sslip.io`

If your host IP differs, edit the Ingress host in `k8s/deployment.yaml` and set `APP_HOST` / `PROM_HOST` / `HOST_IP` accordingly. Prometheus must already be installed (`setup-cluster/kind/5-install-prometheus.sh`).

## Contents

```sh
kind get clusters
```

Override cluster name if needed:

```sh
export KIND_CLUSTER=mylab99
```

## Build and load the image into kind

```sh
./scripts/build-load.sh
```

This performs:

```sh
docker build -t experiment-app:v1 .
kind load docker-image experiment-app:v1 --name "$KIND_CLUSTER"
```

## Deploy

```sh
./scripts/deploy.sh
```

This creates the `cloud-exp` namespace and deploys:

- Deployment
- ClusterIP Service
- nginx Ingress

## Verify

```sh
./scripts/verify.sh
```

Or test manually:

```sh
curl http://experiment.127.0.0.1.sslip.io/
curl http://experiment.127.0.0.1.sslip.io/health
curl http://experiment.127.0.0.1.sslip.io/cpu
curl http://experiment.127.0.0.1.sslip.io/sleep
```

## Generate a small manual load

```sh
./scripts/manual-load.sh
```

Change the number of concurrent requests:

```sh
REQUESTS=50 ./scripts/manual-load.sh
```

## Verify Prometheus sees the application

CPU:

```sh
curl -sG \
  'http://prometheus.127.0.0.1.sslip.io/api/v1/query' \
  --data-urlencode \
  'query=sum(rate(container_cpu_usage_seconds_total{namespace="cloud-exp",container="app"}[1m]))'
```

Memory:

```sh
curl -sG \
  'http://prometheus.127.0.0.1.sslip.io/api/v1/query' \
  --data-urlencode \
  'query=container_memory_working_set_bytes{namespace="cloud-exp",container="app"}'
```

## One-command setup

If all prerequisites are already available:

```sh
./scripts/install-all.sh
```

## Override defaults

```sh
KIND_CLUSTER=mylab99 ./scripts/build-load.sh
IMAGE=experiment-app:v2 ./scripts/build-load.sh
APP_HOST=http://other-host.example ./scripts/verify.sh
```

## Request behavior

| Path | Behavior | Typical use in experiments |
|---|---|---|
| `/` | lightweight OK | control / high-RPS cheap traffic |
| `/cpu` | CPU-heavy loop (~2e6 iters) | **default** Locust target; Workload→Resource |
| `/sleep` | fixed 50 ms wait | latency/queueing without heavy CPU |
| `/health` | readiness/liveness | probes only — not primary load |

Default Deployment knobs (edit `k8s/deployment.yaml` when a scenario needs it):

- `replicas: 1`
- requests: `cpu 100m`, `memory 128Mi`
- limits: `cpu 1`, `memory 512Mi`

The `/cpu` endpoint is intended for the first workload-resource-performance experiment (Menu A in `../experiments/README.md`).

## Experiment hooks (what this app enables)

This sample is a **load target**, not the load generator. After deploy, scenarios live in `../experiments`:

| You change… | Via | Scenario idea |
|---|---|---|
| Concurrent users | `run-experiment.sh <id> <users>` | workload sweep / saturation |
| HTTP path under test | `experiments/workload/locustfile.py` | `/cpu` vs `/sleep` vs `/` |
| Replica count | `kubectl scale … --replicas=N` | horizontal scaling |
| CPU/memory limits | Deployment `resources` | vertical throttling |
| Quick burst | `./scripts/manual-load.sh` | smoke before a long run |

**Monitor while / after load:** Prometheus queries in this README, Grafana, `kubectl top pod -n cloud-exp`, Octant pod events, and the merged CSV from each experiment run.

Full menu (A–G), constants to keep fixed, and report order: see `../experiments/README.md`.
