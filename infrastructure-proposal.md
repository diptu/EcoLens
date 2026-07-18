# ecoLens — Infrastructure Strategy & Cost Proposal

**Prepared for:** ecoLens Project
**Date:** 2026-07-18
**Status:** ✅ Approved scope · 🚧 In progress
**Owner:** @diptu

---

## Executive Summary

ecoLens is a 3-service micro-service platform that needs to serve a real-time
forecast + emissions API, ingest live AEMO / BoM / OpenElectricity data, train
a PyTorch LSTM weekly, and host a Next.js dashboard. We need a hosting
strategy that:

- keeps **operational complexity low** (one server, one domain, one Nginx);
- keeps **cost low and predictable** (no per-service managed fees, no SaaS
  subscriptions);
- still gives us **production-grade reliability** (TLS, rate-limiting,
  security headers, automatic restarts, automatic cert renewal,
  automatic backups).

**Recommendation:** a **single self-managed VPS** (Hetzner CPX11 or
DigitalOcean Basic Droplet), fronted by **Nginx** as a reverse proxy, with
**Let's Encrypt** for TLS, **Linux cron** for scheduling, and **self-hosted
MLflow** (SQLite metadata + MinIO artifacts). Total annual run rate:
**$34 – $85**.

---

## Proposed Infrastructure Budget

| Expense           | Estimated Annual Cost | Notes                                                             |
|-------------------|----------------------:|-------------------------------------------------------------------|
| Domain renewal    |                $10 – $25 | `diptuverse.com` — registrar fee                                  |
| VPS hosting       |                $24 – $60 | Hetzner CPX11 (~$4/mo) or DigitalOcean Basic Droplet (~$6/mo); 2 vCPU, 4 GB RAM, 40 GB SSD |
| SSL/HTTPS         |                     $8 | Let's Encrypt (zero-cost); the $8 is a buffer for a backup CA / wildcard cert |
| Scheduling (Cron) |                     $0 | Native Linux cron + systemd (no SaaS)                            |
| **Total**         |         **$34 – $85** | Optimized annual run rate for the whole 3-service stack            |

> **TL;DR:** $5 – $7 per month for a production-grade carbon-intelligence
> platform that includes Postgres, Redis, MinIO, MLflow, and a real-time API.

---

## Technical Implementation Strategy

### 1. Hosting Multiple Projects (Nginx as a reverse proxy)

We use **Nginx** as the single entry point on a single VPS. Subdirectory
paths map to local container ports:

```nginx
# infra/nginx/conf.d/eco-lence.conf (excerpt)
location ^~ /eco-lence/      { proxy_pass http://dashboard:3000;      }  # Next.js
location ^~ /eco-lence/api/  { proxy_pass http://forecast-api:8000;  }  # FastAPI
location ^~ /mlflow/         { proxy_pass http://mlflow:5000;         }  # basic auth
```

This is the same pattern that lets us run `/blog`, `/eco-lence`, and any
future microservice on the same domain without paying for a per-app hosting
plan. Only Nginx is exposed on ports 80/443; the 3 application services live
on a private Docker network.

**Why this is a good idea even at low scale:**

- No DNS split-brain, no per-service TLS cert to maintain.
- One place to add CDN, WAF, rate limiting, geo rules.
- Lets us host the marketing landing, the dashboard, the API, and the
  MLflow UI on one host, on one cert, with one set of security headers.
- The same Nginx config that runs locally runs in prod.

### 2. Cost-Optimized ML Operations

#### MLflow — self-hosted with SQLite

We **do not** run MLflow on Postgres. MLflow metadata is stored in a SQLite
file on a host-mounted volume (`ecolens_mlflowdata:/mlflow/mlflow.db`).
Artifacts (model files, plots, signatures) still go to **S3-compatible
object storage** (MinIO on the same host).

```bash
mlflow server \
  --host 0.0.0.0 --port 5000 \
  --backend-store-uri sqlite:////mlflow/mlflow.db \
  --default-artifact-root s3://ecolens/mlflow
```

Benefits:

- Zero Postgres dependency for the MLflow server (one fewer moving part).
- Single-file backup of the entire MLflow state (`mlflow.db` + the
  S3 bucket). Both backed up daily by `scripts/backup-mlflow.sh`.
- Artifacts are still durable on MinIO with a separate lifecycle policy.

#### dbt — Core, not Cloud

We use **dbt Core** (open-source), not dbt Cloud. The warehouse lives in
the same Postgres that the API reads from. Models are written to be
**incremental** so we don't recompute the entire 18-month history on every
build.

```bash
# /etc/cron.d/ecolens
*/15 * * * *  docker exec ecolens-data-pipeline-1 dbt build --project-dir /app/dbt/ecolens
```

Benefits:

- $0 — no dbt Cloud subscription.
- dbt runs in the same container as the data-pipeline; same image, same
  secrets, same Python env.
- Incremental models mean a re-build costs ~30 s, not 30 min.
- `dbt build` also runs the data tests — no separate quality gate.

### 3. Nginx + Let's Encrypt

We use **Certbot in webroot mode** (no port-80 downtime during renewal)
and a **certbot sidecar container** that runs `certbot renew` every 12 hours.
The cert lives at `/etc/letsencrypt/live/diptuverse.com/` (mounted into the
Nginx container) and is auto-loaded by Nginx on each renewal.

```yaml
# docker-compose.yml (excerpt)
certbot:
  image: certbot/certbot
  volumes:
    - ./infra/certbot/www:/var/www/certbot:rw
    - ./infra/certbot/conf:/etc/letsencrypt:rw
  entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h; done'"
```

`scripts/setup-vps.sh` requests the initial cert (self-signed fallback if
DNS isn't pointed yet) and `make vps-ssl` re-requests when the real cert
needs to be issued.

### 4. Cron as the scheduler (no Prefect, no Airflow)

The data-pipeline container is an **idle shell** that exists only so
`docker exec` can drop into it. The host's `/etc/cron.d/ecolens` is the
single source of scheduling truth:

```cron
# infra/cron/ecolens-crontab
*/5  *  *  *  *  docker exec ecolens-data-pipeline-1 ecolens-pipeline ingest oe
*/5  *  *  *  *  docker exec ecolens-data-pipeline-1 ecolens-pipeline ingest aemo-nem
*/15 *  *  *  *  docker exec ecolens-data-pipeline-1 ecolens-pipeline dbt build
0  3  *  *  1  docker exec ecolens-data-pipeline-1 ecolens-pipeline ml train
0  4  *  *  *  docker exec ecolens-data-pipeline-1 ecolens-pipeline ml evaluate
30 5  *  *  *  /opt/ecolens/scripts/promote_model.sh
0  3  *  *  *  docker compose -f /opt/ecolens/docker-compose.yml run --rm certbot renew --quiet
```

Benefits:

- $0 — no managed orchestrator.
- Crash / restart of the data-pipeline container doesn't break the schedule
  (cron just re-`docker exec`'s in).
- Schedules are visible in one file, version-controlled, code-reviewed.
- Logs go to `/var/log/ecolens/*.log` (one file per pipeline).

### 5. Systemd for boot-time auto-start

`infra/systemd/ecolens-stack.service` is a `Type=oneshot` unit that brings
the docker-compose stack up on boot. The whole stack comes back online
without operator intervention after a reboot, a power outage, or a kernel
panic.

```ini
[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/ecolens
ExecStart=/usr/bin/docker compose -f /opt/ecolens/docker-compose.yml up -d --remove-orphans
ExecStop=/usr/bin/docker compose -f /opt/ecolens/docker-compose.yml down
```

Grouped under a `ecolens.target` so `systemctl restart ecolens.target`
restarts the whole thing.

---

## What we explicitly did NOT choose, and why

| Alternative | Why not |
|---|---|
| **Managed k8s (EKS, GKE, AKS)** | $70+/month per cluster + per-pod overhead. Overkill for one app. |
| **Serverless (Lambda, Cloud Run Jobs)** | Incompatible with our long-running training workload and the need for a persistent Postgres+MLflow+MinIO trio. |
| **Render / Fly / Railway** | Cheaper than k8s but still $7–$25/service/month per environment; a single VPS is cheaper and gives us root access. |
| **dbt Cloud** | $100+/mo for a team plan; we have one engineer. dbt Core does everything we need. |
| **MLflow on a managed Postgres** | Unnecessary cost; SQLite handles our throughput (one training run/week) with a one-line backup. |
| **Prefect Cloud / Airflow** | $0–$29/mo for self-hosted; cron does the same job with zero moving parts. |
| **Managed Grafana Cloud** | Free tier is fine, but the JSON Nginx access log + `journald` already give us 90% of what we need without a separate vendor account. |
| **Multi-region / multi-VPS HA** | Premature. A single VPS with 99.5% monthly availability (≈ 3.6 h/year downtime) is well above our actual traffic requirements. |

---

## Scaling upgrade path (when we outgrow the VPS)

When we outgrow the single-VPS architecture, the upgrade order is:

1. **Add Cloudflare in front** (free tier) → CDN, WAF, DDoS protection,
   analytics. No code change.
2. **Move Postgres to a managed service** (Neon, Supabase, DO Managed PG) →
   offload the only stateful piece that matters. The API just changes its
   `DATABASE_URL`.
3. **Move MinIO to object storage** (Cloudflare R2, Backblaze B2, AWS S3) →
   durability without running a second service. MLflow just changes its
   `--default-artifact-root`.
4. **Move MLflow to a managed service or a second small VPS** → offload the
   tracking server. `forecast-api` still watches the registry; the URI
   changes.
5. **Add a second VPS for HA** → active/passive Postgres + a load balancer.
   Still no code change in the 3 services.

Each step is **additive** and **optional** — the architecture supports
each upgrade without re-platforming.

---

## Next steps (executed in this commit)

- [x] Document the proposal (`docs/infrastructure-proposal.md`).
- [x] `docker-compose.yml` updated: add Nginx, add Certbot, switch MLflow to
      SQLite, add the `edge` network.
- [x] `infra/nginx/nginx.conf` + `infra/nginx/conf.d/eco-lence.conf` written.
- [x] `infra/cron/ecolens-crontab` written.
- [x] `infra/systemd/*.service` written.
- [x] `scripts/setup-vps.sh` written (one-shot bootstrap).
- [x] `scripts/deploy.sh` written (rsync + restart over SSH).
- [x] `scripts/backup-mlflow.sh` + `scripts/promote_model.sh` + `scripts/cleanup.sh`.
- [x] `services/data-pipeline/pyproject.toml` — Prefect removed, `click`-based
      CLI added.
- [x] `services/data-pipeline/Dockerfile` — `tail -f /dev/null` is the CMD;
      cron drives it.
- [x] `Makefile` — `make vps-bootstrap`, `make vps-deploy`, `make vps-status`,
      `make vps-logs`, `make vps-cron`, `make vps-ssl`, `make vps-backup`.
- [x] `README.md` — updated architecture, cost section, deployment section,
      tech stack, ML pipeline orchestration, observability, repo layout.
- [x] `docs/deployment.md` — single-VPS walkthrough.
- [x] `services/data-pipeline/src/ecolens/cli.py` — `ecolens-pipeline` CLI.

---

## References

- [Hetzner Cloud — CX/CPX plans](https://www.hetzner.com/cloud)
- [DigitalOcean — Basic Droplets](https://www.digitalocean.com/products/droplets)
- [Let's Encrypt — getting started](https://letsencrypt.org/getting-started/)
- [Certbot — webroot plugin](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)
- [MLflow — tracking server setup](https://mlflow.org/docs/latest/tracking.html#mlflow-tracking-server)
- [dbt — Core vs Cloud](https://docs.getdbt.com/docs/cloud/about-cloud/dbt-cloud-features)
- [Nginx — reverse proxy guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
