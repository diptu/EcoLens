# Deploying ecoLens: Namecheap Quasar VPS (backend) + Vercel (dashboard)

Split deployment: the backend services (Postgres, RabbitMQ, Redis,
MinIO/R2, MLflow, ingestion, warehouse, forecast-api) run as
pre-built, registry-pulled containers on a **Namecheap Quasar VPS**;
`services/dashboard` (Next.js static export) deploys to **Vercel**.
The domain is registered/managed at **Namecheap**, split across both:
apex/`www` → Vercel, API subdomains → the VPS.

This replaces building images in-place on the VPS (`git clone` +
`docker compose build`, as an earlier version of this doc described) —
images are built once in CI (or locally) and just *pulled* on the VPS,
so a deploy is `docker compose pull && docker compose up -d`, not a
full rebuild on a small box.

---

## 0. What ends up where

```text
Namecheap (registrar + DNS)
  <DOMAIN>, www.<DOMAIN>     ──▶  Vercel        (dashboard, static export)
  api.<DOMAIN>               ──A──▶  <VPS_IP>   (→ forecast-api :8000)
  ingest.<DOMAIN>            ──A──▶  <VPS_IP>   (→ ingestion :8003)
  warehouse.<DOMAIN>         ──A──▶  <VPS_IP>   (→ warehouse :8004)
  grafana.<DOMAIN>           ──A──▶  <VPS_IP>   (→ observability Grafana :3002)

Vercel
  services/dashboard  — `next build` (output: "export"), NEXT_PUBLIC_*
                         env vars set in Vercel project settings, not
                         baked in locally

GHCR (or Docker Hub)
  ecolens-forecast-api, ecolens-ingestion, ecolens-warehouse, ecolens-mlflow
  — built once (locally or in CI), pulled by the VPS, never built there

Quasar VPS (Ubuntu, Docker)
  Nginx Proxy Manager / Traefik (container) — TLS termination + routing,
                                               only 80/443 public
  docker-compose.yml (prod)  — postgres, rabbitmq, redis, minio, mlflow,
                                ingestion(+worker+beat), warehouse(+consumer),
                                train-worker, api (forecast-api) — all
                                pulled `image:`, no `build:`
  services/observility        — Prometheus/Loki/Tempo/Grafana/Alertmanager
                                 (separate compose project)
```

Only the reverse proxy's ports (80/443) are exposed to the internet;
every container port (`8000`, `8003`, `8004`, `5432`, `5672`, `6379`,
`9000`, `5000`/`5001`, `3001`/`3002`, `9090`/`9091`, etc.) stays behind
the VPS firewall, reached only over `localhost`/the Docker network.

---

## Phase 1 — Build & push images

Build for the VPS's architecture (most Quasar VPS instances are
`linux/amd64` — confirm with `uname -m` on the VPS before assuming),
tag, and push to a registry. GHCR is the path of least friction since
it reuses this repo's own GitHub auth (no separate registry account):

```bash
# One-time: a GitHub PAT with `write:packages`, or use GITHUB_TOKEN in CI (Phase 8)
echo "<GHCR_TOKEN>" | docker login ghcr.io -u <GITHUB_USERNAME> --password-stdin

# Each image below maps to one infra/docker/*.Dockerfile — reused across
# multiple docker-compose services via `command:` overrides (e.g.
# ecolens-forecast-api backs both `api` and `train-worker`; ecolens-ingestion
# backs `ingestion`, `ingestion-worker`, and `ingestion-beat`).
for svc in forecast-api ingestion warehouse mlflow; do
  docker buildx build \
    --platform linux/amd64 \
    -f infra/docker/${svc}.Dockerfile \
    -t ghcr.io/<GITHUB_USERNAME>/ecolens-${svc}:latest \
    --push .
done
```

`--push` builds and pushes in one step via buildx (no local image
needed on your Mac first). Repeat with a real version tag (`:v1.2.0`,
a commit SHA, etc.) instead of `:latest` once you want reproducible,
rollback-able deploys rather than always-newest.

---

## Phase 2 — Provision the Quasar VPS ✅ done

Real values for this deployment: VPS IP `159.198.41.61`, hostname
`server1.diptuverse.com`, Ubuntu 24.04.5 LTS, `linux/amd64`.

1. Namecheap → **Hosting List** → order/open the **Quasar VPS** plan.
2. Deploy an **Ubuntu 24.04 LTS** (or 22.04) image — not a
   cPanel-managed image; you want raw root SSH access.
3. Note the assigned public IPv4 and the root password/initial SSH key
   the panel gives you.
4. Confirm login: `ssh root@159.198.41.61`

As `root`:

```bash
apt update && apt -y upgrade

# Non-root sudo user — everything from here on runs as this user, not root.
# The account (username: deployer) already existed on this box, created by
# Namecheap's own provisioning — useradd was a no-op, the rest wasn't:
useradd -m -s /bin/bash deployer   # skipped here — already existed
usermod -aG sudo deployer
mkdir -p /home/deployer/.ssh && chmod 700 /home/deployer/.ssh
echo "<DEPLOY_PUBLIC_KEY>" >> /home/deployer/.ssh/authorized_keys
chmod 600 /home/deployer/.ssh/authorized_keys
chown -R deployer:deployer /home/deployer/.ssh

# Passwordless sudo for this account (it's a dedicated deploy/ops user,
# not a personal login) — real, not hypothetical: this repo's Phase 8 CI
# workflow SSHes in as this same user to run `docker compose` non-interactively.
echo 'deployer ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/deployer
chmod 440 /etc/sudoers.d/deployer
visudo -c
```

The key used is a **dedicated deploy keypair**
(`~/.ssh/ecolens_deploy` locally, no passphrase — generated specifically
for this VPS), not a personal key — same reasoning Phase 8 already gives
for the CI secret. A personal passphrase-protected key works fine for
interactive use too, but non-interactive tooling (scripts, CI) needs a
passphrase-free key or an unlocked agent.

**Before touching `sshd_config`**: verify the new user can actually log
in with the key and use sudo — do this *before* disabling root/password
login, or a mistake locks you out with no fallback:

```bash
ssh -i ~/.ssh/ecolens_deploy deployer@159.198.41.61 "whoami && sudo whoami"
```

Harden SSH. **Real gotcha hit here**: Ubuntu's default
`/etc/ssh/sshd_config` has `Include /etc/ssh/sshd_config.d/*.conf` near
the *top* of the file (line 12), and OpenSSH uses **first-value-wins**
per keyword — so a cloud-init drop-in
(`/etc/ssh/sshd_config.d/50-cloud-init.conf`, `PasswordAuthentication
yes`) silently overrides anything set later in the main file's own body.
Don't edit `sshd_config` directly expecting it to take effect — add a
new drop-in that sorts *before* `50-cloud-init.conf` instead:

```bash
cat > /etc/ssh/sshd_config.d/10-hardening.conf << 'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
EOF
sshd -t   # validate before restarting, not after
systemctl restart ssh
```

Reconnect as `ssh deployer@159.198.41.61` from here on — root login
(both password and key) is closed; verify all three outcomes before
moving on:

```bash
ssh -i ~/.ssh/ecolens_deploy deployer@159.198.41.61 whoami   # -> works
ssh root@159.198.41.61 whoami                                # -> Permission denied
```

Firewall (UFW) — **on this box, already done** by an earlier manual
session (confirmed via `/var/log/auth.log`) before this runbook's
scripted pass reached it; commands below are what to run if starting
from scratch:

```bash
sudo ufw allow OpenSSH      # do this BEFORE enabling, or you lock yourself out
sudo ufw allow 80/tcp       # reverse proxy HTTP (→ redirected to HTTPS)
sudo ufw allow 443/tcp      # reverse proxy HTTPS
sudo ufw enable
sudo ufw status verbose
```

Confirmed active state: default deny incoming, `22/80/443` allowed
(IPv4 + IPv6), nothing else.

No other port is opened — Postgres/RabbitMQ/Redis/MinIO/MLflow/the app
services stay reachable only via `localhost` or the Docker network.

`fail2ban` + `unattended-upgrades` (recommended, done):

```bash
sudo apt -y install fail2ban unattended-upgrades
sudo systemctl enable --now fail2ban
sudo systemctl enable --now unattended-upgrades
```

---

## Phase 3 — Install Docker on the VPS

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deployer
newgrp docker   # or log out/in
docker compose version   # confirm the compose plugin is present
```

---

## Phase 4 — Configure DNS ✅ done

Real domain: `diptuverse.com`. Namecheap → **Domain List** →
`diptuverse.com` → **Manage** → **Advanced DNS**.

**Backend subdomains → the VPS**, via one A record for the VPS's real
hostname plus CNAMEs aliasing each subdomain to it (chosen over 4 plain
A records so a future IP change only means editing one row):

| Type | Host | Value | TTL |
| --- | --- | --- | --- |
| A | `server1` | `159.198.41.61` | Automatic |
| CNAME | `api` | `server1.diptuverse.com.` | Automatic |
| CNAME | `ingest` | `server1.diptuverse.com.` | Automatic |
| CNAME | `warehouse` | `server1.diptuverse.com.` | Automatic |
| CNAME | `grafana` | `server1.diptuverse.com.` | Automatic |

A CNAME's value must be a hostname, never a bare IP — that's why
`server1` needs its own A record for the others to chain through.

Drop any subdomain you don't intend to expose publicly.

**Apex + `www` → Vercel** (added once the Vercel project exists —
Phase 7 — since Vercel's dashboard tells you the exact target values):

| Type | Host | Value |
| --- | --- | --- |
| A | `@` | `76.76.21.21` (Vercel's anycast IP — confirm the current value in Vercel's own Domains UI, it's shown live when you add the domain there) |
| CNAME | `www` | `cname.vercel-dns.com.` |

A `ecolense` CNAME already points at a Vercel-issued target
(`*.vercel-dns-017.com.`) from an earlier, separate pass — worth
reconciling with whatever the real Phase 7 Vercel domain setup turns
out to be, so it doesn't end up as an orphaned/duplicate entry.

**Real gotcha hit here**: even Namecheap's own authoritative
nameservers (`dns1`/`dns2.registrar-servers.com`) took about **17
minutes** to become internally consistent after saving — querying the
same hostname twice in a row returned two different SOA serials
(their backend is a pool of nodes, not a single server), so a record
that looks saved in the UI can still `NXDOMAIN` for a while even
directly against "the" authoritative server. Don't assume a save
failed just because `dig` comes back empty immediately — poll instead:

```bash
until [ "$(dig +short server1.diptuverse.com @dns1.registrar-servers.com)" = "159.198.41.61" ]; do
  sleep 30
done
```

---

## Phase 5 — Deploy the reverse proxy ✅ done

Either works; **Nginx Proxy Manager** (NPM) is the simpler pick for a
single-box deploy (GUI, no hand-written config files) — Traefik is the
better pick if you'd rather everything be declarative via Docker
labels. Steps below use NPM.

**Real problem hit here**: this VPS has slow/unstable connectivity to
Docker Hub specifically (plain internet speed is fine — 400+ KB/s to a
generic speed-test host — but `docker pull jc21/nginx-proxy-manager`
crawled at ~10 KB/s and an SSH session died mid-transfer with
`Connection reset by peer`). General internet on this box is fine;
Docker Hub's CDN path from this box isn't. Two workarounds that
combined actually fixed it:

1. Pull via **Google's Docker Hub mirror** instead of Docker Hub
   directly — same public image, different (much better-routed) CDN:
   ```bash
   docker pull --platform linux/amd64 mirror.gcr.io/jc21/nginx-proxy-manager:latest
   docker tag mirror.gcr.io/jc21/nginx-proxy-manager:latest jc21/nginx-proxy-manager:latest
   ```
2. Run it **detached on the VPS itself** (`nohup ... & disown`,
   logging to a file), not as a long-lived foreground SSH command —
   even the mirror needed a few retries before a transient stall
   didn't hit, and a dropped SSH session otherwise kills the pull with
   it. Poll the log file with short, separate SSH connections instead
   of holding one connection open:
   ```bash
   nohup bash -c 'for i in $(seq 1 30); do
     docker pull --platform linux/amd64 mirror.gcr.io/jc21/nginx-proxy-manager:latest \
       && echo PULL_SUCCESS && break
     sleep 10
   done' > ~/npm_pull.log 2>&1 < /dev/null &
   disown
   ```
   This will very likely be needed again in Phase 6 for the 4
   `diptu/ecolense:*` backend images — those aren't on any mirror
   (private-ish repo, Docker Hub only), so budget for retries there
   too.

```bash
mkdir -p /opt/npm && cd /opt/npm
```

`/opt/npm/docker-compose.yml`:

```yaml
name: npm
services:
  app:
    image: jc21/nginx-proxy-manager:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "127.0.0.1:81:81"   # admin UI — SSH tunnel in, don't expose publicly
    volumes:
      - npm_data:/data
      - npm_letsencrypt:/etc/letsencrypt
    networks:
      - ecolens_default   # join the app stack's network so it can proxy by service name

volumes:
  npm_data:
  npm_letsencrypt:

networks:
  ecolens_default:
    external: true   # created by the app stack in Phase 6 — bring that up first, or `docker network create ecolens_default` now
```

```bash
docker network create ecolens_default || true   # if the app stack isn't up yet
docker compose up -d
```

Reach the admin UI via an SSH tunnel (it's bound to `127.0.0.1:81`,
not public): `ssh -L 8181:127.0.0.1:81 deployer@<VPS_IP>`, then
`http://localhost:8181` locally.

**Real gotcha**: NPM 2.15 (what's actually deployed here) has **no**
seeded `admin@example.com`/`changeme` account — the user table starts
empty and the frontend's first-run setup wizard is what normally
creates the first admin. Skipping the wizard and hitting the API
directly, `POST /api/users` (unauthenticated) works specifically when
no users exist yet — this is how the real admin account was created
here, no GUI needed:

```bash
curl -s -X POST http://127.0.0.1:81/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Admin","nickname":"Admin","email":"<YOUR_EMAIL>",
       "roles":["admin"],"is_disabled":false,
       "auth":{"type":"password","secret":"<YOUR_PASSWORD>"}}'
```

Then `POST /api/tokens` with that same email/password to get a bearer
token for everything else below.

In the UI (or via the API, which is what was actually used here — see
`GET /api/` for the version/schema), add one **Proxy Host** per
backend subdomain:

| Domain | Forward to |
| --- | --- |
| `api.<DOMAIN>` | `api:8000` (Docker service name, since NPM shares the app network) |
| `ingest.<DOMAIN>` | `ingestion:8003` |
| `warehouse.<DOMAIN>` | `warehouse:8004` |
| `grafana.<DOMAIN>` | `observility-grafana-1:3000` (container port, not the host-mapped `3002`) |

Enable **Force SSL** + **Request a new SSL Certificate** (Let's
Encrypt) on each — NPM handles issuance and renewal, no manual
certbot. **Real API quirk**: `POST /api/nginx/proxy-hosts` with
`certificate_id: "new"` issues the cert correctly, but silently resets
`ssl_forced`/`hsts_enabled` back to `false` in the same response even
if you sent `true` — a separate follow-up `PUT
/api/nginx/proxy-hosts/{id}` with just `{"ssl_forced":true,
"hsts_enabled":true,"http2_support":true}` after the cert exists is
what actually makes it stick. Verify with a real request, not just the
API response:

```bash
curl -sv https://api.<DOMAIN> 2>&1 | grep -i 'subject:\|issuer:'
```

Put an **Access List** (basic auth) on the `grafana` host at minimum,
since Grafana isn't multi-tenant auth'd beyond one admin account —
`POST /api/nginx/access-lists` (not `/api/access-lists` — real 404 hit
first), then reference its `id` as `access_list_id` on that one proxy
host. A `401` from `curl -sk https://grafana.<DOMAIN>` (before you've
supplied Basic-Auth credentials) confirms it's actually gating —
NPM checks the access list before even reaching the (still-nonexistent
until Phase 6) backend, so `401` here is correct, not a bug.

`502` on `api`/`ingest`/`warehouse` at this point is expected — those
containers don't exist until Phase 6. The cert + TLS + routing config
is real and already working; only the proxied destination is missing.

---

## Phase 6 — Deploy the backend services ✅ done

Real registry used: **Docker Hub**, `diptu/ecolense`, not GHCR —
Phase 1's GHCR example was the original plan; what was actually built
and pushed (see Phase 1's real history) lives at
`docker.io/diptu/ecolense:<service>-V2.0.0`, both public.

On the VPS:

```bash
sudo mkdir -p /opt/ecolens && sudo chown deployer:deployer /opt/ecolens
git clone https://github.com/diptu/EcoLens.git /opt/ecolens
cd /opt/ecolens
git checkout dev-v2   # real gotcha: git clone defaults to `main`, which
                       # is stale here (still has a `data-pipeline`
                       # service, plus `prefect`/`web` that don't exist
                       # on dev-v2) -- confirm with
                       # `grep -n '^  [a-z].*:$' docker-compose.yml`
                       # before trusting whatever branch you land on.
```

`docker-compose.prod.yml` (real version, Docker Hub tags):

```yaml
name: ecolens
services:
  mlflow:
    build: !reset null
    image: diptu/ecolense:mlflow-V2.0.0
  ingestion:
    build: !reset null
    image: diptu/ecolense:ingestion-V2.0.0
  ingestion-worker:
    build: !reset null
    image: diptu/ecolense:ingestion-V2.0.0
  ingestion-beat:
    build: !reset null
    image: diptu/ecolense:ingestion-V2.0.0
  warehouse:
    build: !reset null
    image: diptu/ecolense:warehouse-V2.0.0
  warehouse-consumer:
    build: !reset null
    image: diptu/ecolense:warehouse-V2.0.0
  train-worker:
    build: !reset null
    image: diptu/ecolense:forecast-api-V2.0.0
  api:
    build: !reset null
    image: diptu/ecolense:forecast-api-V2.0.0
```

`docker compose -f docker-compose.yml -f docker-compose.prod.yml config --services`
should list all 18 services with no errors before going further — cheap
sanity check that the override actually merges.

**Env files**: copy every example as a starting scaffold, then
overwrite with the **real** production values — do this by `scp`ing
your own already-configured local `.env` files to the VPS rather than
hand-typing secrets over SSH:

```bash
# On the VPS (scaffolding only):
cp .env.example .env
cp services/ingestion/.env.example services/ingestion/.env
cp services/forecast-api/.env.example services/forecast-api/.env
cp services/waerehouse/.env.example services/waerehouse/.env
cp services/observility/.env.example services/observility/.env
```

```bash
# From your own machine, real secrets (Neon DATABASE_URL, R2 creds, etc.):
scp .env ecolens-vps:/opt/ecolens/.env
scp services/ingestion/.env ecolens-vps:/opt/ecolens/services/ingestion/.env
scp services/forecast-api/.env ecolens-vps:/opt/ecolens/services/forecast-api/.env
scp services/waerehouse/.env ecolens-vps:/opt/ecolens/services/waerehouse/.env
```

Also add `SLACK_WEBHOOK_URL` to the root `.env` if you want real
Alertmanager notifications — without it, `alertmanager` fails to start
at all (`unsupported scheme "" for URL`, not a graceful no-op the way
`infra/alertmanager/alertmanager.yml.template`'s own comment implies).
A syntactically-valid placeholder (`https://hooks.slack.com/services/PLACEHOLDER/REPLACE/ME`)
at least keeps it running until you have a real one.

Both public images (Docker Hub `diptu/ecolense` and the GitHub repo)
need no login to pull/clone.

### Real, hard blocker: this VPS's CPU can't run stock numpy wheels

Bringing the stack up the first time (`docker compose ... up -d`)
surfaced two serious, unrelated problems — read this before you hit
the same thing on a different Quasar (or any budget/shared-hypervisor)
VPS instance:

**1. Third-party images get Docker-Hub-anonymous-pull-rate-limited.**
`minio/mc`/other infra images failed with `pull access denied for
minio/mc, repository does not exist or may require 'docker login'` —
Docker Hub's generic anonymous-rate-limit error, not an actual
permissions issue. Fix: pull through **`mirror.gcr.io`** instead
(works for *any* public Docker Hub image, official or user
namespace — `mirror.gcr.io/library/redis:7.4-alpine` for official
images, `mirror.gcr.io/diptu/ecolense:...` for user-namespaced ones),
then `docker tag` back to the name `docker-compose.yml` expects:

```bash
docker pull mirror.gcr.io/library/redis:7.4-alpine
docker tag mirror.gcr.io/library/redis:7.4-alpine redis:7.4-alpine
```

Two of MinIO's own images (`minio/minio:RELEASE.2024-08-29T01-40-52Z`,
`minio/mc:latest`) weren't cached by that mirror at all (`not found`,
not a timeout) — MinIO also publishes to **`quay.io/minio/...`**,
which worked directly.

The mirror itself is also **not instantaneous after a fresh push** —
pulling a tag immediately after pushing it can serve a stale cached
copy for a while (confirmed: pulled 4 hours stale once). If a rebuilt
image doesn't seem to have your latest changes, compare
`docker inspect <image> --format '{{index .RepoDigests 0}}'` against
the real digest from `curl -s
https://hub.docker.com/v2/repositories/<repo>/tags/<tag> | python3 -c
"import sys,json;print(json.load(sys.stdin)['digest'])"` — if they
differ, pull **by digest** instead of tag
(`mirror.gcr.io/<repo>@sha256:...`), which bypasses the mirror's
tag-level cache and fetches the real content.

**2. The VPS's virtual CPU doesn't meet numpy's compiled baseline.**
Namecheap's hypervisor exposes only a generic `QEMU Virtual CPU
version 2.5+` (check with `cat /proc/cpuinfo | grep flags` — missing
`sse4_2`/`popcnt`/etc means below "x86-64-v2"). Every PyPI `numpy`
wheel since numpy's meson-based build (~2.x) is *compiled* requiring
that baseline — not a runtime-togglable dispatch feature, so no env
var fixes it. Symptom: `RuntimeError: NumPy was built with baseline
optimizations: (X86_V2) but your machine doesn't support: (X86_V2)`,
crash-looping every service that imports `pandas`/`numpy` at module
load (`ingestion`, `ingestion-beat`, `warehouse-consumer`, `api`,
`train-worker`, and — easy to miss, no healthcheck to flag it —
`mlflow` itself). `warehouse`'s own FastAPI app was the one exception,
purely because it doesn't import `pandas` until a request actually
needs it.

Verified **not** the problem: `torch` (imports fine on this CPU, no
baseline requirement in its wheel) and `scipy`'s own *prebuilt* wheel
once numpy alone is fixed (tried rebuilding scipy from source too —
`ERROR: Unknown option: "cpu-baseline"`, it has no equivalent meson
option and doesn't need one).

**Fix** (now baked into `infra/docker/{ingestion,warehouse,forecast-api,mlflow}.Dockerfile`,
unconditional — a no-op on modern CPUs beyond ~3 min extra build time):
rebuild numpy from source in the builder stage with SIMD baseline
disabled, using whatever version the lockfile (or, for `mlflow`, pip's
own resolution) actually picked:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gfortran pkg-config libopenblas-dev \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install pip \
    && .venv/bin/pip install --force-reinstall --no-deps --no-binary numpy \
         --config-settings=setup-args=-Dcpu-baseline=none \
         --config-settings=setup-args=-Dcpu-dispatch=none \
         numpy==2.5.1
```

(`mlflow.Dockerfile`'s builder is a plain `venv`, not `uv` — use plain
`pip` there instead of `uv pip install pip` + `.venv/bin/pip`, and
resolve the version dynamically since that image doesn't pin numpy
directly: `NUMPY_VERSION=$(python -c "import numpy; print(numpy.__version__)")`.)

**Real second-order bug this introduces**: the rebuilt numpy links
against OpenBLAS, but only `libopenblas-dev` was installed in the
*builder* stage — multi-stage `COPY --from=builder` only carries the
finished venv across, never apt packages. The **runtime** stage needs
`libopenblas0` (the shared-lib-only package, not `-dev`) added to its
own `apt-get install` line too, or numpy import fails at runtime with
`libopenblas.so.0: cannot open shared object file` even though the
build itself succeeded.

### Bringing it up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
sleep 20 && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Every service should show `Up`/`healthy` — the ones with an explicit
`healthcheck:` in `docker-compose.yml` will say so; the rest (`mlflow`,
`train-worker`, `ingestion-worker`, `ingestion-beat`,
`warehouse-consumer`) just need to *not* be `Restarting`. Check
`docker inspect <container> --format '{{.RestartCount}}'` if in doubt —
`0` and climbing slowly over real uptime is fine, a number that keeps
increasing every few seconds means it's still crash-looping.

Then bring up observability the same way it already runs (own compose
project, same shared network):

```bash
cd services/observility
docker compose up -d
```

`restart: unless-stopped` is already set on every app service in
`docker-compose.yml`, and Docker's systemd unit being enabled by
default (from the install script in Phase 3) means the whole stack
survives a VPS reboot.

---

## Phase 7 — Configure CORS & connect Vercel

**Backend CORS**: all three services (`forecast-api`, `ingestion`,
`waerehouse`) read `api_cors_origins` (default `["*"]`,
`app/core/config.py` in each) from the env var `API_CORS_ORIGINS` — a
JSON array, not comma-separated. Tighten this to the real dashboard
origin(s) in each service's `.env` on the VPS:

```bash
# services/forecast-api/.env, services/ingestion/.env, services/waerehouse/.env
API_CORS_ORIGINS=["https://<DOMAIN>","https://www.<DOMAIN>"]
```

Restart the affected services after editing:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d api ingestion warehouse`.

If you want Vercel's per-branch preview deployments (`*.vercel.app`)
to also reach the backend during testing, add that origin too — but
keep production `.env` scoped to the real domain, not `*`.

**Vercel project**:

1. [vercel.com](https://vercel.com) → **Add New… → Project** → import
   this GitHub repo.
2. **Root Directory**: `services/dashboard` (this is a monorepo — the
   dashboard isn't at the repo root).
3. Framework preset: **Next.js** (auto-detected). Build command
   `next build` / output directory is handled automatically for
   `output: "export"` — no custom build command needed.
4. **Project Settings → Environment Variables** (Production
   environment — these are inlined into the JS bundle at Vercel's
   build time, matching `services/dashboard/src/lib/env.ts`):

   | Key | Value |
   | --- | --- |
   | `NEXT_PUBLIC_FORECAST_API_URL` | `https://api.<DOMAIN>/v1` |
   | `NEXT_PUBLIC_INGESTION_API_URL` | `https://ingest.<DOMAIN>/v1` |
   | `NEXT_PUBLIC_WAREHOUSE_API_URL` | `https://warehouse.<DOMAIN>/v1` |

   Leave `NEXT_PUBLIC_IAM_API_URL` / `NEXT_PUBLIC_DATA_PIPELINE_API_URL`
   unset — `services/iam` was scaffolded then deleted and
   `data-pipeline` was retired (see
   `docs/runbooks/independent-service-deployment.md`), neither has a
   real backend to point at.
5. Deploy. Then **Project Settings → Domains** → add `<DOMAIN>` and
   `www.<DOMAIN>` — Vercel shows the exact A/CNAME records to add at
   Namecheap (Phase 4); add them there and Vercel verifies
   automatically once DNS propagates.

Every subsequent push to the connected branch auto-redeploys the
dashboard on Vercel — no manual rebuild/upload step for it going
forward.

---

## Phase 8 — CI/CD pipeline

`.github/workflows/deploy-backend.yml` — builds and pushes the 4
backend images on every push to `main` that touches a backend
service's source, then SSHes into the VPS to pull and restart. Follows
the same SSH-deploy shape `docs/runbooks/github-actions-secrets.md`
already documents for the observability stack.

```yaml
name: Deploy backend
on:
  push:
    branches: [main]
    paths:
      - "services/ingestion/**"
      - "services/forecast-api/**"
      - "services/waerehouse/**"
      - "infra/docker/**"
  workflow_dispatch:

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    strategy:
      matrix:
        svc: [forecast-api, ingestion, warehouse, mlflow]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: infra/docker/${{ matrix.svc }}.Dockerfile
          platforms: linux/amd64
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/ecolens-${{ matrix.svc }}:latest

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_SSH_HOST }}
          username: ${{ secrets.VPS_SSH_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/ecolens
            docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
            docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Secrets needed (repo → **Settings → Secrets and variables → Actions**):

| Secret | Notes |
| --- | --- |
| `VPS_SSH_HOST` | `<VPS_IP>` |
| `VPS_SSH_USER` | `deployer` |
| `VPS_SSH_KEY` | Private key for a **dedicated deploy keypair** (`~/.ssh/ecolens_deploy` locally — already generated in Phase 2, its public half is already in `deployer`'s `~/.ssh/authorized_keys` on the VPS) — don't reuse a personal key. |

`GITHUB_TOKEN` (used for the GHCR push) is provided automatically by
Actions — no separate secret needed as long as the repo's **Settings →
Actions → General → Workflow permissions** allows "Read and write
permissions" (needed for `packages: write`).

The dashboard needs no equivalent workflow — Vercel's own GitHub
integration (Phase 7) already redeploys it on every push.

---

## Verify

- `https://<DOMAIN>` loads the dashboard (served by Vercel).
- `https://api.<DOMAIN>/v1/healthz`, `https://ingest.<DOMAIN>/v1/healthz`,
  `https://warehouse.<DOMAIN>/v1/healthz` all return healthy, via the
  VPS reverse proxy.
- `https://grafana.<DOMAIN>` prompts for the NPM access-list login,
  then Grafana's own login.
- Open the dashboard in a browser, check the Network tab — API calls
  go to `https://api.<DOMAIN>/...` etc. with no CORS errors in the
  console.
- `dig api.<DOMAIN>` resolves to `<VPS_IP>`; `dig <DOMAIN>` resolves to
  Vercel's IP.

---

## Ongoing operations

- **Redeploy backend after a code change**: push to `main` (Phase 8
  handles the rest), or manually on the VPS:
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml pull && ... up -d`.
- **Redeploy dashboard**: push to `main` — Vercel handles it.
- **Backups**: `pgdata`/`miniodata`/`rabbitmqdata` are named Docker
  volumes on this one host — if you're not using managed Neon/R2, back
  these up separately (e.g. `docker run --rm -v ecolens_pgdata:/data ...`
  to a tarball shipped off-box), since nothing here replicates them.
- **Logs**: `docker compose logs -f <service>` on the VPS, or
  Grafana/Loki via `services/observility` for centralized/queryable
  logs; Vercel's own dashboard has the frontend's build/runtime logs.
- **Firewall review**: `sudo ufw status verbose` on the VPS — only
  22/80/443 should ever be listed as allowed from the internet.
