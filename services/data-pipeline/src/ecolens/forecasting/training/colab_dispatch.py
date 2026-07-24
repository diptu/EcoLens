"""Best-effort Colab T4 GPU dispatch for `train_model()`.

Companion to `services/data-pipeline/scripts/colab_server.py` (run inside a
Colab notebook cell): that script starts a tunnelled Jupyter server on a
free Colab GPU runtime and publishes `{url, token}` to a private ntfy.sh
topic. This module polls that topic and, if a live kernel is published:

  1. Bundles every `.py` file under `ecolens/{config.py,shared,forecasting}`
     as plain text (needed so a `torch.load()` of the `WindowedDataset`
     below can resolve the same classes remotely, and so `train_model()`
     itself is importable) -- whole directories, not hand-picked files,
     since every `__init__.py` in this repo is empty (nothing is eagerly
     imported just by being on disk), so unused modules cost nothing.
  2. `torch.save()`s the already-fetched `WindowedDataset` and base64-encodes
     it -- the dataset is fetched from the warehouse Postgres locally as
     always; Colab never sees a database connection.
  3. Runs one bootstrap cell on the remote kernel over the Jupyter
     websocket protocol: writes the bundle, pip-installs the handful of
     pure-Python deps `train_model()` needs (torch itself ships
     preinstalled on Colab), loads the dataset, and calls
     `train_model(..., log_to_mlflow=False)` -- MLflow logging is skipped
     remotely on purpose, see `log_remote_result_to_mlflow` below.
  4. Reads the returned state_dict + metrics back out of the cell's stdout
     and rebuilds a local `DemandLSTM` from them.

Only ever sends the training-hyperparameter subset of `Settings` (see
`REMOTE_HYPERPARAM_FIELDS`) to the remote kernel -- never the full object,
which carries the warehouse Postgres DSN, Mongo URI, Redis DSN, and
MinIO/S3 credentials.

Never raises: any bridge-unavailable condition (no kernel published,
network error, websocket error, remote exception) is caught and logged,
and `try_remote_train` returns `None` so the caller falls back to a plain
local `train_model()` call -- this is a pure "use it when available"
accelerator, never a hard dependency.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests
import torch
import websocket
from dotenv import dotenv_values

from ecolens.config import Settings
from ecolens.shared.observability.logging import get_logger

from ..features import Split, WindowedDataset
from ..models.lstm import DemandLSTM
from .train import TrainResult

log = get_logger(__name__)

# Must match NTFY_TOPIC in scripts/colab_server.py -- set your own random
# value in services/data-pipeline/.env (edit that one line per Colab
# session) or via a real NTFY_TOPIC environment variable (which always
# wins), rather than committing one to source control. ntfy.sh topics are
# unauthenticated and guessable/enumerable by design; treat this as a
# shared secret for the life of the Colab kernel. Unset (the default)
# disables the bridge entirely -- this feature is strictly opt-in.
#
# Deliberately `dotenv_values()`, not `load_dotenv()`: the latter injects
# *every* key from .env into the real process `os.environ` as a side
# effect of merely importing this module -- including WAREHOUSE_PG_DSN/
# MONGO_URI/etc, which then leaks into any other code (tests included)
# that later checks those vars, for the rest of the process's life.
# `dotenv_values()` just parses the file into a plain dict; only the one
# key this module actually cares about gets touched.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or dotenv_values().get("NTFY_TOPIC") or ""

REMOTE_HYPERPARAM_FIELDS = (
    "model_hidden_size",
    "model_num_layers",
    "model_dropout",
    "model_train_lr",
    "model_train_epochs",
    "model_early_stop_patience",
    "model_batch_size",
)


class NoRemoteKernelError(Exception):
    """Nothing published on the ntfy.sh topic -- no live Colab kernel."""


BRIDGE_UNAVAILABLE_ERRORS = (
    NoRemoteKernelError,
    requests.exceptions.RequestException,
    websocket.WebSocketException,
    OSError,
    KeyError,
    json.JSONDecodeError,
)

CHECKPOINT_MARKER = "___ECOLENS_COLAB_STATE_DICT_B64___"
METRICS_MARKER = "___ECOLENS_COLAB_METRICS_JSON___"


def fetch_latest_connection(topic: str, stale_after: int = 20 * 60) -> tuple[str, str]:
    """Poll ntfy.sh for the latest `{url, token}` colab_server.py published.

    Raises `NoRemoteKernelError` if nothing has been published yet.
    """
    resp = requests.get(f"https://ntfy.sh/{topic}/json?poll=1", timeout=15)
    resp.raise_for_status()

    latest = None
    for line in resp.text.splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("event") != "message":
            continue
        if latest is None or entry["time"] > latest["time"]:
            latest = entry

    if latest is None:
        raise NoRemoteKernelError(
            f"No connection info found on ntfy.sh/{topic}. "
            "Run scripts/colab_server.py in a Colab cell first."
        )

    payload = json.loads(latest["message"])
    age = time.time() - payload["ts"]
    if age > stale_after:
        log.warning("colab_dispatch.stale_kernel", age_seconds=round(age))
    return payload["url"], payload["token"]


def _ws_message(msg_type: str, content: dict, session_id: str) -> dict:
    return {
        "header": {
            "msg_id": str(uuid.uuid4()),
            "username": "ecolens-colab-dispatch",
            "session": session_id,
            "msg_type": msg_type,
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "content": content,
        "buffers": [],
        "channel": "shell",
    }


def _run_cell(ws: websocket.WebSocket, session_id: str, code: str) -> tuple[bool, str]:
    """Execute one cell over an open kernel websocket, return (ok, stdout).

    Echoes the remote kernel's stdout to this process's stdout as it
    arrives (so e.g. the remote's own "training.device: cuda" / per-epoch
    log lines show up live in `make model-train`'s output) -- except for
    the two result-marker lines (`CHECKPOINT_MARKER`/`METRICS_MARKER`),
    which carry a full base64-encoded state_dict and would otherwise dump
    a very long line to the terminal.
    """
    msg = _ws_message(
        "execute_request",
        {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        },
        session_id,
    )
    ws.send(json.dumps(msg))
    my_msg_id = msg["header"]["msg_id"]

    ok = True
    stdout_chunks: list[str] = []
    while True:
        raw = ws.recv()
        if not raw:
            continue
        reply = json.loads(raw)
        if reply.get("parent_header", {}).get("msg_id") != my_msg_id:
            continue  # message for a different request; ignore

        msg_type = reply["header"]["msg_type"]
        content = reply["content"]
        if msg_type == "stream":
            if content.get("name") == "stderr":
                log.info("colab_dispatch.remote_stderr", text=content["text"])
            else:
                text = content["text"]
                stdout_chunks.append(text)
                for line in text.splitlines(keepends=True):
                    if CHECKPOINT_MARKER in line or METRICS_MARKER in line:
                        marker = (
                            CHECKPOINT_MARKER
                            if CHECKPOINT_MARKER in line
                            else METRICS_MARKER
                        )
                        print(
                            f"[colab] received {marker.strip('_')} ({len(line)} bytes)"
                        )
                    else:
                        sys.stdout.write(line)
                        sys.stdout.flush()
        elif msg_type == "error":
            ok = False
            log.error(
                "colab_dispatch.remote_error",
                traceback="\n".join(content["traceback"]),
            )
        elif msg_type == "status" and content["execution_state"] == "idle":
            break

    return ok, "".join(stdout_chunks)


def _collect_sources() -> dict[str, str]:
    """Every `.py` file needed to import `train_model()` and unpickle a
    `WindowedDataset` remotely -- see module docstring for why whole
    directories are bundled rather than individual files.
    """
    src_root = Path(__file__).resolve().parents[3]  # .../services/data-pipeline/src
    if src_root.name != "src":
        raise RuntimeError(f"expected .../src, got {src_root}")

    files: dict[str, str] = {
        "ecolens/__init__.py": (src_root / "ecolens" / "__init__.py").read_text(),
        "ecolens/config.py": (src_root / "ecolens" / "config.py").read_text(),
    }
    for rel_dir in ("ecolens/shared", "ecolens/forecasting"):
        for path in (src_root / rel_dir).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(src_root).as_posix()
            files[rel] = path.read_text()
    return files


def _build_remote_script(
    files: dict[str, str], dataset_filename: str, hyperparams: dict[str, float | int]
) -> str:
    """A self-contained script for the remote kernel: writes the bundle,
    installs deps, loads the (already-uploaded, see `_upload_dataset`)
    dataset, trains, and prints the resulting state_dict + metrics as
    base64/JSON so the caller can parse them out of the cell's stdout.

    Deliberately does NOT embed the dataset here -- at real data scale
    (hundreds of MB) a single WebSocket `execute_request` frame that large
    reliably breaks (Jupyter/Tornado's default websocket message-size cap
    is ~10 MB; anything past it silently kills the connection, which reads
    as a mid-transfer "Broken pipe"). The dataset travels as a separate
    plain-HTTP file upload instead -- see `_upload_dataset` -- and this
    script just reads it back off disk.
    """
    files_json = json.dumps(files)
    hyperparams_json = json.dumps(hyperparams)
    return f'''
import json, subprocess, sys
from pathlib import Path

files = json.loads({files_json!r})
for rel_path, content in files.items():
    p = Path(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)

# torch ships preinstalled (with CUDA) on Colab -- everything else
# train_model()'s import chain needs, deliberately minimal.
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q",
     "mlflow-skinny>=2.18.0", "pydantic>=2", "pydantic-settings",
     "python-dotenv", "pandas>=3.0.3", "numpy>=2.5.1"],
    check=True,
)

sys.path.insert(0, str(Path.cwd()))
import base64, io
import torch
from ecolens.config import Settings
from ecolens.forecasting.training.train import DEVICE, train_model

print("ecolens_colab_dispatch.device:", DEVICE, flush=True)

dataset = torch.load({dataset_filename!r}, weights_only=False)
# env="dev" pinned explicitly: Settings.env is case-insensitive-matched
# against OS env vars (case_sensitive=False), and Colab's container sets
# a system ENV var (POSIX shells' startup-script convention, e.g.
# "ENV=/root/.bashrc") that otherwise collides with this field and fails
# validation -- an explicit kwarg always outranks an environment-sourced
# value, so this pins it regardless of whatever ENV happens to be set to.
settings = Settings(env="dev", **json.loads({hyperparams_json!r}))
result = train_model(dataset, settings=settings, log_to_mlflow=False)

state_buf = io.BytesIO()
torch.save(result.model.state_dict(), state_buf)
metrics = {{
    "best_val_loss": result.best_val_loss,
    "epochs_trained": result.epochs_trained,
    "arch_kwargs": result.model.architecture_dict(),
}}
print("{METRICS_MARKER}" + json.dumps(metrics), flush=True)
print("{CHECKPOINT_MARKER}" + base64.b64encode(state_buf.getvalue()).decode(), flush=True)
'''


def _trim_to_train_val(dataset: WindowedDataset) -> WindowedDataset:
    """Drops `calibration`/`test` before shipping the dataset to Colab.

    `train_model()` only ever touches `dataset.train`/`dataset.val` (plus
    `.horizon`/`.scaler` for logging, which we skip remotely via
    `log_to_mlflow=False` anyway) -- evaluation against calibration/test
    happens locally afterward, against the real `dataset` this function's
    caller already has, not whatever comes back from Colab. Sending empty
    placeholders for the two unused splits cuts the transfer by roughly
    the fraction of `split_fractions` they'd otherwise account for (20% at
    this repo's default 0.7/0.1/0.1/0.1), on top of the bigger win from
    not embedding any of it in the WebSocket message at all (see
    `_build_remote_script`).
    """
    empty = Split(
        x=torch.empty(0, dataset.lookback, dataset.train.x.shape[-1]),
        y=torch.empty(0, dataset.horizon),
        as_of=dataset.train.as_of.iloc[0:0],
        region=dataset.train.region.iloc[0:0],
    )
    return WindowedDataset(
        train=dataset.train,
        val=dataset.val,
        calibration=empty,
        test=empty,
        scaler=dataset.scaler,
        lookback=dataset.lookback,
        horizon=dataset.horizon,
    )


def _upload_dataset(url: str, headers: dict[str, str], dataset_bytes: bytes) -> str:
    """Uploads the dataset to the Colab kernel's filesystem via Jupyter's
    Contents API -- a plain HTTP PUT, not a WebSocket frame (see
    `_build_remote_script`'s docstring for why that distinction matters at
    this data scale). Returns the filename it was written to.
    """
    filename = "ecolens_dataset.pt"
    resp = requests.put(
        f"{url}/api/contents/{filename}",
        headers=headers,
        json={
            "type": "file",
            "format": "base64",
            "content": base64.b64encode(dataset_bytes).decode(),
        },
        timeout=300,
    )
    resp.raise_for_status()
    return filename


def try_remote_train(
    dataset: WindowedDataset, settings: Settings
) -> TrainResult | None:
    """Attempt to run `train_model()` on a live Colab GPU kernel.

    Returns a `TrainResult` (with `run_id=""` -- see `log_remote_result_to_
    mlflow`, no local MLflow run exists for it yet) on success, or `None` if
    the bridge isn't usable right now -- callers should then fall back to
    a plain local `train_model(dataset, settings=settings)` call.
    """
    if not NTFY_TOPIC:
        return None

    if "://" in NTFY_TOPIC or NTFY_TOPIC.startswith(("http", "www.")):
        # A common mistake: exporting the printed Jupyter "URL with token"
        # line instead of the plain NTFY_TOPIC value colab_server.py prints
        # separately -- ntfy.sh then 404s on the resulting nonsense path,
        # which reads as "bridge unavailable" (silently falls back to
        # local) rather than the actual misconfiguration it is.
        log.warning(
            "colab_dispatch.ntfy_topic_looks_like_a_url",
            ntfy_topic=NTFY_TOPIC,
            hint=(
                "NTFY_TOPIC should be the short random string colab_server.py "
                "prints on its own 'NTFY_TOPIC: ...' line, not the Jupyter "
                "URL+token."
            ),
        )
        return None

    try:
        url, token = fetch_latest_connection(NTFY_TOPIC)
    except BRIDGE_UNAVAILABLE_ERRORS as e:
        log.info("colab_dispatch.bridge_unavailable", error=str(e))
        return None

    trimmed = _trim_to_train_val(dataset)
    dataset_buf = io.BytesIO()
    torch.save(trimmed, dataset_buf)
    dataset_bytes = dataset_buf.getvalue()
    hyperparams = {f: getattr(settings, f) for f in REMOTE_HYPERPARAM_FIELDS}

    headers = {"Authorization": f"token {token}"}
    try:
        log.info(
            "colab_dispatch.uploading_dataset",
            url=url,
            size_mb=round(len(dataset_bytes) / 1e6, 1),
        )
        dataset_filename = _upload_dataset(url, headers, dataset_bytes)
        remote_script = _build_remote_script(
            _collect_sources(), dataset_filename, hyperparams
        )

        kernel_id = requests.post(
            f"{url}/api/kernels", headers=headers, timeout=15
        ).json()["id"]
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
        ws = websocket.create_connection(
            f"{ws_url}/api/kernels/{kernel_id}/channels?token={token}", timeout=None
        )
        session_id = str(uuid.uuid4())
        try:
            log.info("colab_dispatch.dispatching", url=url)
            ok, stdout = _run_cell(ws, session_id, remote_script)
        finally:
            ws.close()
            requests.delete(
                f"{url}/api/kernels/{kernel_id}", headers=headers, timeout=15
            )
    except BRIDGE_UNAVAILABLE_ERRORS as e:
        log.warning("colab_dispatch.dispatch_failed", error=str(e))
        return None

    if not ok:
        log.warning("colab_dispatch.remote_training_failed")
        return None

    metrics_idx = stdout.find(METRICS_MARKER)
    checkpoint_idx = stdout.find(CHECKPOINT_MARKER)
    if metrics_idx == -1 or checkpoint_idx == -1:
        log.warning("colab_dispatch.no_result_markers")
        return None

    try:
        metrics = json.loads(
            stdout[metrics_idx + len(METRICS_MARKER) : checkpoint_idx].strip()
        )
        state_dict_bytes = base64.b64decode(
            stdout[checkpoint_idx + len(CHECKPOINT_MARKER) :].strip()
        )
        model = DemandLSTM(**metrics["arch_kwargs"])
        model.load_state_dict(
            torch.load(io.BytesIO(state_dict_bytes), weights_only=True)
        )
    except BRIDGE_UNAVAILABLE_ERRORS as e:
        log.warning("colab_dispatch.result_parse_failed", error=str(e))
        return None

    log.info(
        "colab_dispatch.success",
        best_val_loss=metrics["best_val_loss"],
        epochs_trained=metrics["epochs_trained"],
    )
    return TrainResult(
        run_id="",
        model=model,
        dataset=dataset,
        best_val_loss=metrics["best_val_loss"],
        epochs_trained=metrics["epochs_trained"],
    )


def log_remote_result_to_mlflow(
    remote_result: TrainResult, dataset: WindowedDataset, settings: Settings
) -> TrainResult:
    """Creates the local MLflow run a Colab-trained model doesn't have yet.

    The remote kernel trains with `log_to_mlflow=False` and never touches
    MLflow at all (its own ephemeral filesystem disappears with the Colab
    session anyway) -- this is the one place a Colab-trained model's real
    `run_id` gets created, logging exactly what `train_model()` would have
    logged locally, just skipping the epoch loop since the weights already
    exist. Everything downstream (`registry.register()`, `promote_if_
    better()`) then works identically to a local run.
    """
    import mlflow

    from ..mlops.registry import log_model_artifacts

    mlflow.set_experiment(settings.mlflow_experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "lookback": dataset.lookback,
                "horizon": dataset.horizon,
                "n_features": remote_result.model.n_features,
                "hidden_size": settings.model_hidden_size,
                "num_layers": settings.model_num_layers,
                "dropout": settings.model_dropout,
                "lr": settings.model_train_lr,
                "batch_size": settings.model_batch_size,
                "train_samples": len(dataset.train.x),
                "val_samples": len(dataset.val.x),
                "trained_on": "colab_gpu",
            }
        )
        mlflow.log_metric("best_val_loss", remote_result.best_val_loss)
        mlflow.log_dict(dataset.scaler.to_dict(), "scaler.json")
        log_model_artifacts(remote_result.model)
        run_id = run.info.run_id

    return TrainResult(
        run_id=run_id,
        model=remote_result.model,
        dataset=dataset,
        best_val_loss=remote_result.best_val_loss,
        epochs_trained=remote_result.epochs_trained,
    )


__all__ = [
    "NTFY_TOPIC",
    "NoRemoteKernelError",
    "BRIDGE_UNAVAILABLE_ERRORS",
    "fetch_latest_connection",
    "try_remote_train",
    "log_remote_result_to_mlflow",
]
