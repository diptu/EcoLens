"""
run_remote.py
=============
Ad-hoc runner for the Colab GPU bridge — mainly useful for a quick sanity
check (e.g. confirming `torch.cuda.is_available()` on the remote kernel)
before trusting it with a real `make model-train` run. For that real run,
`ecolens.forecasting.training.colab_dispatch` handles everything (bundling
the `ecolens` package + the training dataset) automatically — you don't
need this script for normal use.

Once `colab_server.py` is running in a Colab cell, it auto-publishes its
tunnel URL + token to an ntfy.sh topic (see NTFY_TOPIC below). This script
fetches that live connection info, then executes a local .py file directly
on the remote GPU kernel over the Jupyter websocket protocol and streams
the output back to your terminal — no VS Code kernel picker, no copy/paste.

Usage:
    export NTFY_TOPIC=<same value colab_server.py printed>
    python scripts/run_remote.py scripts/gpu_sanity_check.py
    python scripts/run_remote.py some_self_contained_script.py --stale-after 30

Note: this executes the target file's raw source on an ephemeral Colab
kernel that does NOT have this repo's `ecolens` package installed. Only use
it for genuinely self-contained scripts (no `from ecolens... import`
statements) — for anything that needs the real package + a training
dataset, use `make model-train` (NTFY_TOPIC set) instead.

If the file contains `# %%` cell markers, each cell is executed and printed
separately (like "Run All Cells"). Otherwise the whole file runs as one cell.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid

import requests
import websocket  # from the `websocket-client` package
from dotenv import dotenv_values

# Must match NTFY_TOPIC in colab_server.py — set your own random value in
# services/data-pipeline/.env (edit that one line per Colab session) or a
# real NTFY_TOPIC environment variable (or --topic below), which always
# wins, rather than relying on a value committed to source control. ntfy.sh
# topics are unauthenticated and guessable/enumerable by design, so treat
# this name as a shared secret for the lifetime of the Colab kernel.
#
# `dotenv_values()`, not `load_dotenv()`: only pulls this one key out of
# .env as a plain dict rather than injecting every key in that file
# (WAREHOUSE_PG_DSN, MONGO_URI, ...) into this process's real os.environ.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or dotenv_values().get("NTFY_TOPIC") or ""

CELL_MARKER_RE = re.compile(r"^# ?%%.*$", re.MULTILINE)


class NoRemoteKernelError(Exception):
    """Nothing published on the ntfy.sh topic — no live Colab kernel to connect to."""


def fetch_latest_connection(topic: str, stale_after: int) -> tuple[str, str]:
    """Poll ntfy.sh for the latest ``{url, token}`` published by colab_server.py.

    Parameters
    ----------
    topic : str
        ntfy.sh topic to poll.
    stale_after : int
        Warn (not raise) if the latest entry is older than this, in seconds.

    Returns
    -------
    tuple of (str, str)
        ``(url, token)``.

    Raises
    ------
    NoRemoteKernelError
        If nothing has been published on ``topic``.
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
            f"No connection info found on ntfy.sh/{topic}.\n"
            "Run colab_server.py in a Colab cell first."
        )

    payload = json.loads(latest["message"])
    age = time.time() - payload["ts"]
    if age > stale_after:
        print(
            f"⚠️  Latest published kernel is {age / 60:.1f} min old — "
            f"the Colab session may have died. Re-run colab_server.py if this fails.",
            file=sys.stderr,
        )
    return payload["url"], payload["token"]


def split_cells(source: str) -> list[str]:
    """Split source on ``# %%`` cell markers.

    Parameters
    ----------
    source : str

    Returns
    -------
    list of str
        One entry per cell; ``[source]`` unchanged if there are no markers.
    """
    parts = CELL_MARKER_RE.split(source)
    cells = [p.strip("\n") for p in parts if p.strip()]
    return cells or [source]


def _ws_message(msg_type: str, content: dict, session_id: str) -> dict:
    """Build a Jupyter kernel-protocol websocket message.

    Parameters
    ----------
    msg_type : str
        e.g. ``"execute_request"``.
    content : dict
    session_id : str

    Returns
    -------
    dict
    """
    return {
        "header": {
            "msg_id": str(uuid.uuid4()),
            "username": "run_remote",
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


def run_cell(ws: websocket.WebSocket, session_id: str, code: str) -> tuple[bool, str]:
    """Execute one cell over an open kernel websocket.

    Parameters
    ----------
    ws : websocket.WebSocket
        Open connection to the kernel.
    session_id : str
    code : str
        Source to execute.

    Returns
    -------
    tuple of (bool, str)
        ``(ok, captured_stdout)`` — ``captured_stdout`` accumulates only
        stdout `stream` text (not stderr, which carries pip/tqdm noise), so
        callers that need to parse a cell's output get a clean buffer.
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
        parent_id = reply.get("parent_header", {}).get("msg_id")
        if parent_id != my_msg_id:
            continue  # message for a different request; ignore

        msg_type = reply["header"]["msg_type"]
        content = reply["content"]

        if msg_type == "stream":
            is_stderr = content.get("name") == "stderr"
            stream = sys.stderr if is_stderr else sys.stdout
            stream.write(content["text"])
            stream.flush()
            if not is_stderr:
                stdout_chunks.append(content["text"])
        elif msg_type in ("execute_result", "display_data"):
            text = content.get("data", {}).get("text/plain")
            if text:
                print(text)
        elif msg_type == "error":
            ok = False
            print("\n".join(content["traceback"]), file=sys.stderr)
        elif msg_type == "status" and content["execution_state"] == "idle":
            break

    return ok, "".join(stdout_chunks)


def main() -> None:
    if "-f" in sys.argv and any(a.endswith(".json") for a in sys.argv):
        sys.exit(
            "run_remote.py was launched inside a Jupyter/IPython kernel "
            "(e.g. VS Code's ▶ Run/Interactive Window), not as a plain script — "
            "that's why argv contains a kernel connection file instead of your "
            "arguments.\n\n"
            "Run it from a terminal instead:\n"
            "    python run_remote.py <script.py>"
        )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", help="Local .py file to run on the remote GPU kernel")
    parser.add_argument("--topic", default=NTFY_TOPIC, help="ntfy.sh topic to poll")
    parser.add_argument(
        "--stale-after",
        type=int,
        default=20 * 60,
        help=(
            "Warn if the published kernel is older "
            "than this many seconds (default 1200)"
        ),
    )
    args = parser.parse_args()

    if not args.topic:
        sys.exit(
            "No ntfy.sh topic configured. Set the NTFY_TOPIC environment "
            "variable to the same random value colab_server.py printed/used "
            "(or pass --topic explicitly) — this must match on both ends."
        )

    with open(args.script) as f:
        source = f.read()

    try:
        url, token = fetch_latest_connection(args.topic, args.stale_after)
    except NoRemoteKernelError as e:
        sys.exit(str(e))
    print(f"Connecting to {url} ...")

    headers = {"Authorization": f"token {token}"}
    kernel = requests.post(f"{url}/api/kernels", headers=headers, timeout=15).json()
    kernel_id = kernel["id"]
    print(f"Kernel created: {kernel_id}")

    ws_url = url.replace("https://", "wss://").replace("http://", "ws://")
    ws = websocket.create_connection(
        f"{ws_url}/api/kernels/{kernel_id}/channels?token={token}", timeout=300
    )
    session_id = str(uuid.uuid4())

    success = True
    try:
        for i, cell in enumerate(split_cells(source), start=1):
            print(f"\n--- cell {i} " + "-" * 40)
            ok, _ = run_cell(ws, session_id, cell)
            if not ok:
                success = False
                print(f"Stopped at cell {i} due to error.", file=sys.stderr)
                break
    finally:
        ws.close()
        requests.delete(f"{url}/api/kernels/{kernel_id}", headers=headers, timeout=15)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
