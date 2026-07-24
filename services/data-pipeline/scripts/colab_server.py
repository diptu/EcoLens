"""
colab_server.py
================
Run this inside Google Colab to expose a GPU-backed Jupyter server
through a public tunnel that `ecolens.forecasting.training.colab_dispatch`
(back on your laptop) connects to for GPU-accelerated `make model-train`.

How to use:
  1. Open https://colab.research.google.com  ->  New notebook
  2. Runtime  ->  Change runtime type  ->  Hardware accelerator: GPU (T4)
  3. Paste this whole file into a single cell and run it (Ctrl+F9)
  4. On your laptop, set NTFY_TOPIC=<the value this cell prints> in
     services/data-pipeline/.env (edit that one line each session -- if
     you've ever `export NTFY_TOPIC=...`'d in this shell, `unset` it first
     so the .env value actually takes effect), then run `make model-train`
     from the repo root as usual -- it picks the bridge up automatically.
     (Or `python scripts/run_remote.py <script.py>` for a quick ad-hoc
     sanity check first -- see that file.)

Colab sessions are temporary (max ~12 h, often less if idle) — re-run this
script whenever your session dies.

Tested on: Python 3.10/3.11, Colab free tier T4.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import time

import requests

# ----------------------------------------------------------------------
# CONFIG — pick the tunnel provider you want
# ----------------------------------------------------------------------
# "cloudflared" -> no signup, free, easiest. RECOMMENDED.
# "ngrok"       -> needs a free authtoken (https://dashboard.ngrok.com)
# "localhostrun"-> no signup, SSH-based, occasionally flaky
TUNNEL = "cloudflared"

# Optional: only used if TUNNEL == "ngrok".
# Easiest: store it as a Colab secret named "NGROK_AUTHTOKEN" before running.
NGROK_AUTHTOKEN = os.environ.get("NGROK_AUTHTOKEN", "")

# Jupyter port (rare to need changing)
PORT = 8888

# ntfy.sh topic used to hand the URL+token to colab_dispatch.py/run_remote.py
# automatically — no signup needed, but treat the topic name itself as a
# shared secret since ntfy.sh topics are unauthenticated and
# guessable/enumerable by design: anyone who learns this topic name while
# this cell is running could fetch the token and get arbitrary code
# execution on this kernel. Must match NTFY_TOPIC on the laptop side (both
# ecolens.forecasting.training.colab_dispatch and scripts/run_remote.py
# read it from the same env var) — set your own random value via the
# NTFY_TOPIC environment variable (a Colab secret of the same name works
# too) rather than relying on a value committed to source control.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
if not NTFY_TOPIC:
    NTFY_TOPIC = secrets.token_hex(12)
    print(
        f"⚠️  NTFY_TOPIC not set — generated a random one-off topic:\n"
        f"    {NTFY_TOPIC}\n"
        f"Set NTFY_TOPIC={NTFY_TOPIC} in services/data-pipeline/.env on "
        f"your laptop before running `make model-train` / run_remote.py — "
        f"otherwise it won't find this kernel.",
        file=sys.stderr,
    )


def sh(cmd: str, **kw) -> None:
    """Print and run a shell command, raising on non-zero exit.

    Parameters
    ----------
    cmd : str
    **kw
        Passed through to ``subprocess.run``.
    """
    print(f"$ {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True, text=True, **kw)


# ----------------------------------------------------------------------
# 1. Verify GPU
# ----------------------------------------------------------------------
try:
    import torch  # type: ignore

    have_torch = True
except ImportError:
    have_torch = False

if have_torch:
    print(f"GPU available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU device:    {torch.cuda.get_device_name(0)}")
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"VRAM: {vram_gb:.1f} GB")
    else:
        print(
            "⚠️  No GPU detected. Go to Runtime → Change runtime type → "
            "Hardware accelerator → GPU, then re-run.",
            file=sys.stderr,
        )
else:
    print("PyTorch not installed yet — installing now.")

# ----------------------------------------------------------------------
# 2. Install Jupyter + a few niceties
# ----------------------------------------------------------------------
sh("pip install -q --upgrade pip")
sh("pip install -q jupyterlab notebook ipykernel requests")

# ----------------------------------------------------------------------
# 3. Random token for security
# ----------------------------------------------------------------------
TOKEN = secrets.token_urlsafe(24)

# ----------------------------------------------------------------------
# 4. Start Jupyter in the background
# ----------------------------------------------------------------------
jupyter_log = "/tmp/jupyter.log"
os.system(
    f"nohup jupyter lab --no-browser --allow-root "
    f"--ip=0.0.0.0 --port={PORT} "
    f"--ServerApp.token={TOKEN} "
    f"--ServerApp.password='' "
    f"--ServerApp.allow_origin='*' "
    f"--ServerApp.disable_check_xsrf=True "
    f"--ServerApp.allow_remote_access=True "
    # The training dataset travels via the Contents API (a plain PUT to
    # /api/contents/<file>, see colab_dispatch.py's _upload_dataset), not
    # inline in a WebSocket frame -- Tornado's default websocket message
    # cap (~10MB) can't carry it, but Contents API uploads have their own,
    # much larger, separately-configured ceiling. Bumped here rather than
    # relying on the (already generous, but not unlimited) default.
    f"--ServerApp.max_body_size=1073741824 "  # 1 GiB
    f"--ServerApp.max_buffer_size=1073741824 "
    f"> {jupyter_log} 2>&1 &"
)
time.sleep(6)  # give it a moment to boot

# quick sanity check
if not os.path.exists(jupyter_log):
    print("⚠️  Jupyter didn't start; check /tmp/jupyter.log", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------------
# 5. Start the tunnel
# ----------------------------------------------------------------------
url = None

if TUNNEL == "cloudflared":
    sh(
        "curl -fsSL "
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64 -o /usr/local/bin/cloudflared "
        "&& chmod +x /usr/local/bin/cloudflared"
    )
    proc = subprocess.Popen(
        [
            "cloudflared",
            "tunnel",
            "--no-autoupdate",
            "--url",
            f"http://localhost:{PORT}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print("Tunnel starting… (this takes ~10 s)")
    for line in proc.stdout:
        m = re.search(r"https://[\w-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break
    if not url:
        print("⚠️  Failed to parse cloudflared URL.", file=sys.stderr)
        sys.exit(1)

elif TUNNEL == "ngrok":
    sh("pip install -q pyngrok")
    if not NGROK_AUTHTOKEN:
        print(
            "⚠️  Set NGROK_AUTHTOKEN env var (Colab Secrets) before using ngrok.",
            file=sys.stderr,
        )
        sys.exit(1)
    from pyngrok import ngrok  # type: ignore

    ngrok.set_auth_token(NGROK_AUTHTOKEN)
    url = ngrok.connect(PORT).public_url

elif TUNNEL == "localhostrun":
    proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-R",
            f"80:localhost:{PORT}",
            "nokey@localhost.run",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in proc.stdout:
        m = re.search(r"https://[\w-]+\.lhr\.life", line)
        if m:
            url = m.group(0)
            break
    if not url:
        print("⚠️  Failed to parse localhost.run URL.", file=sys.stderr)
        sys.exit(1)

else:
    print(f"Unknown TUNNEL={TUNNEL!r}", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------------
# 6. Publish the connection info so colab_dispatch.py/run_remote.py can
#    pick it up automatically
# ----------------------------------------------------------------------
try:
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=json.dumps({"url": url, "token": TOKEN, "ts": time.time()}),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    print(f"Published connection info to ntfy.sh/{NTFY_TOPIC} for auto-connect.")
except Exception as e:
    print(
        f"⚠️  Could not auto-publish to ntfy.sh ({e}). Paste the URL manually instead."
    )

# ----------------------------------------------------------------------
# 7. Print the connection info
# ----------------------------------------------------------------------
banner = "=" * 64
print()
print(banner)
print("  🚀  JUPYTER IS LIVE ON COLAB GPU")
print(banner)
print("  URL with token (paste this whole thing):")
print(f"    {url}/?token={TOKEN}")
print()
print(f"  Just the URL:    {url}")
print(f"  Just the TOKEN:  {TOKEN}")
print(f"  NTFY_TOPIC:      {NTFY_TOPIC}")
print(banner)
print("  On your laptop, in services/data-pipeline/.env:")
print(f"    NTFY_TOPIC={NTFY_TOPIC}")
print("  (if you've ever `export NTFY_TOPIC=...`'d in that shell, `unset` it")
print("   first -- a real env var overrides the .env file)")
print("  Then, from the repo root:")
print("    make model-train")
print(banner)
print()
print("Keeping this cell alive so the server stays up.")
print("Do NOT close this Colab tab or the GPU disconnects.\n")

# ----------------------------------------------------------------------
# 8. Keep-alive heartbeat
# ----------------------------------------------------------------------
try:
    while True:
        time.sleep(60)
        if torch.cuda.is_available():
            mem = torch.cuda.memory_allocated() / 1e9
            print(
                f"[heartbeat {time.strftime('%H:%M:%S')}] GPU mem in use: {mem:.2f} GB",
                flush=True,
            )
        else:
            print(f"[heartbeat {time.strftime('%H:%M:%S')}] alive", flush=True)
except KeyboardInterrupt:
    print("shutting down…")
