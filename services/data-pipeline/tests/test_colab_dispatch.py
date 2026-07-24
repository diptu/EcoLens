"""Tests for ecolens.forecasting.training.colab_dispatch.

The deep end-to-end path (a real Colab kernel over a real websocket)
is out of scope for a unit test -- these cover every piece that's
deterministic and network-free: the ntfy.sh polling logic, the Jupyter
kernel-protocol message building/parsing, source bundling, the remote
script template, dataset trimming, and try_remote_train's early-return
guards (NTFY_TOPIC unset/misconfigured, no kernel published).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import torch

from ecolens.forecasting.features import FeatureScaler, Split, WindowedDataset
from ecolens.forecasting.training import colab_dispatch as cd


def _make_split(n: int, n_features: int = 3) -> Split:
    return Split(
        x=torch.randn(n, 4, n_features),
        y=torch.randn(n, 2),
        as_of=pd.Series(pd.date_range("2026-01-01", periods=n, freq="30min")),
        region=pd.Series(["NSW1"] * n),
    )


def _make_dataset() -> WindowedDataset:
    scaler = FeatureScaler(mean=np.zeros(3), std=np.ones(3), columns=("a", "b", "c"))
    return WindowedDataset(
        train=_make_split(10),
        val=_make_split(4),
        calibration=_make_split(4),
        test=_make_split(4),
        scaler=scaler,
        lookback=4,
        horizon=2,
    )


class TestFetchLatestConnection:
    def test_raises_when_nothing_published(self, monkeypatch):
        fake_resp = MagicMock(text="")
        fake_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(cd.requests, "get", MagicMock(return_value=fake_resp))

        with pytest.raises(cd.NoRemoteKernelError):
            cd.fetch_latest_connection("some-topic")

    def test_picks_the_latest_message_by_time(self, monkeypatch):
        older = json.dumps(
            {
                "event": "message",
                "time": 100,
                "message": json.dumps(
                    {"url": "https://old", "token": "t-old", "ts": 100}
                ),
            }
        )
        newer = json.dumps(
            {
                "event": "message",
                "time": 200,
                "message": json.dumps(
                    {"url": "https://new", "token": "t-new", "ts": 200}
                ),
            }
        )
        fake_resp = MagicMock(text=f"{older}\n{newer}\n")
        fake_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(cd.requests, "get", MagicMock(return_value=fake_resp))
        monkeypatch.setattr(cd.time, "time", lambda: 200)

        url, token = cd.fetch_latest_connection("some-topic")
        assert (url, token) == ("https://new", "t-new")

    def test_ignores_non_message_events(self, monkeypatch):
        open_event = json.dumps({"event": "open"})
        message = json.dumps(
            {
                "event": "message",
                "time": 1,
                "message": json.dumps({"url": "https://u", "token": "t", "ts": 1}),
            }
        )
        fake_resp = MagicMock(text=f"{open_event}\n{message}\n")
        fake_resp.raise_for_status = MagicMock()
        monkeypatch.setattr(cd.requests, "get", MagicMock(return_value=fake_resp))
        monkeypatch.setattr(cd.time, "time", lambda: 1)

        url, token = cd.fetch_latest_connection("some-topic")
        assert (url, token) == ("https://u", "t")


class TestWsMessage:
    def test_shape(self):
        msg = cd._ws_message("execute_request", {"code": "1+1"}, "session-1")
        assert msg["header"]["msg_type"] == "execute_request"
        assert msg["header"]["session"] == "session-1"
        assert msg["content"] == {"code": "1+1"}
        assert msg["channel"] == "shell"


class _FakeWebSocket:
    """Records sends, replays a canned queue of recv() replies."""

    def __init__(self, replies: list[dict]) -> None:
        self.sent: list[dict] = []
        self._replies = list(replies)

    def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def recv(self) -> str:
        return json.dumps(self._replies.pop(0))


def _reply(msg_id: str, msg_type: str, content: dict) -> dict:
    return {
        "parent_header": {"msg_id": msg_id},
        "header": {"msg_type": msg_type},
        "content": content,
    }


class TestRunCell:
    def test_streams_stdout_and_returns_ok(self, monkeypatch, capsys):
        ws = _FakeWebSocket([])

        def fake_send(raw):
            msg = json.loads(raw)
            ws.sent.append(msg)
            msg_id = msg["header"]["msg_id"]
            ws._replies = [
                _reply(msg_id, "stream", {"name": "stdout", "text": "hello\n"}),
                _reply(msg_id, "status", {"execution_state": "idle"}),
            ]

        ws.send = fake_send
        ok, stdout = cd._run_cell(ws, "session-1", "print('hello')")
        assert ok is True
        assert stdout == "hello\n"
        assert "hello" in capsys.readouterr().out

    def test_ignores_replies_for_other_requests(self):
        ws = _FakeWebSocket([])

        def fake_send(raw):
            msg = json.loads(raw)
            msg_id = msg["header"]["msg_id"]
            ws._replies = [
                _reply(
                    "someone-elses-msg-id",
                    "stream",
                    {"name": "stdout", "text": "nope\n"},
                ),
                _reply(msg_id, "status", {"execution_state": "idle"}),
            ]

        ws.send = fake_send
        ok, stdout = cd._run_cell(ws, "session-1", "code")
        assert ok is True
        assert stdout == ""

    def test_error_reply_sets_not_ok(self):
        ws = _FakeWebSocket([])

        def fake_send(raw):
            msg = json.loads(raw)
            msg_id = msg["header"]["msg_id"]
            ws._replies = [
                _reply(
                    msg_id, "error", {"traceback": ["Traceback...", "ValueError: boom"]}
                ),
                _reply(msg_id, "status", {"execution_state": "idle"}),
            ]

        ws.send = fake_send
        ok, _ = cd._run_cell(ws, "session-1", "code")
        assert ok is False

    def test_suppresses_result_marker_lines_from_stdout_echo(self, capsys):
        ws = _FakeWebSocket([])
        marker_line = cd.METRICS_MARKER + json.dumps({"a": 1}) + "\n"

        def fake_send(raw):
            msg = json.loads(raw)
            msg_id = msg["header"]["msg_id"]
            ws._replies = [
                _reply(msg_id, "stream", {"name": "stdout", "text": marker_line}),
                _reply(msg_id, "status", {"execution_state": "idle"}),
            ]

        ws.send = fake_send
        ok, stdout = cd._run_cell(ws, "session-1", "code")
        assert ok is True
        assert stdout == marker_line  # still captured for parsing...
        out = capsys.readouterr().out
        assert cd.METRICS_MARKER not in out  # ...but not dumped to the terminal
        assert "received" in out


class TestCollectSources:
    def test_bundles_expected_packages(self):
        files = cd._collect_sources()
        assert "ecolens/__init__.py" in files
        assert "ecolens/config.py" in files
        assert any(p.startswith("ecolens/forecasting/") for p in files)
        assert any(p.startswith("ecolens/shared/") for p in files)
        assert all("__pycache__" not in p for p in files)


class TestBuildRemoteScript:
    def test_embeds_dataset_filename_and_hyperparams_not_the_dataset_itself(self):
        script = cd._build_remote_script(
            {"ecolens/__init__.py": ""}, "ecolens_dataset.pt", {"model_hidden_size": 64}
        )
        assert "ecolens_dataset.pt" in script
        assert "model_hidden_size" in script
        assert cd.METRICS_MARKER in script
        assert cd.CHECKPOINT_MARKER in script
        assert 'env="dev"' in script


class TestTrimToTrainVal:
    def test_keeps_train_and_val_empties_the_rest(self):
        dataset = _make_dataset()
        trimmed = cd._trim_to_train_val(dataset)

        assert torch.equal(trimmed.train.x, dataset.train.x)
        assert torch.equal(trimmed.val.x, dataset.val.x)
        assert trimmed.calibration.x.shape[0] == 0
        assert trimmed.test.x.shape[0] == 0
        assert trimmed.lookback == dataset.lookback
        assert trimmed.horizon == dataset.horizon

    def test_round_trips_through_torch_save(self):
        import io

        trimmed = cd._trim_to_train_val(_make_dataset())
        buf = io.BytesIO()
        torch.save(trimmed, buf)
        buf.seek(0)
        reloaded = torch.load(buf, weights_only=False)
        assert torch.equal(reloaded.train.x, trimmed.train.x)


class TestUploadDataset:
    def test_puts_base64_content_to_contents_api(self, monkeypatch):
        put_calls = []

        def fake_put(url, headers, json, timeout):  # noqa: A002 - matches requests.put's kwarg name
            put_calls.append((url, headers, json, timeout))
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr(cd.requests, "put", fake_put)
        filename = cd._upload_dataset(
            "https://colab.example", {"Authorization": "token t"}, b"raw-bytes"
        )

        assert filename == "ecolens_dataset.pt"
        assert len(put_calls) == 1
        url, headers, body, timeout = put_calls[0]
        assert url == "https://colab.example/api/contents/ecolens_dataset.pt"
        assert body["type"] == "file"
        assert body["format"] == "base64"


class TestTryRemoteTrainEarlyReturns:
    def test_returns_none_when_ntfy_topic_unset(self, monkeypatch):
        monkeypatch.setattr(cd, "NTFY_TOPIC", "")
        assert cd.try_remote_train(_make_dataset(), settings=MagicMock()) is None

    def test_returns_none_when_ntfy_topic_looks_like_a_url(self, monkeypatch):
        monkeypatch.setattr(
            cd, "NTFY_TOPIC", "https://dispatched-quote.trycloudflare.com/?token=abc"
        )
        assert cd.try_remote_train(_make_dataset(), settings=MagicMock()) is None

    def test_returns_none_when_no_kernel_published(self, monkeypatch):
        monkeypatch.setattr(cd, "NTFY_TOPIC", "some-real-topic")
        monkeypatch.setattr(
            cd,
            "fetch_latest_connection",
            MagicMock(side_effect=cd.NoRemoteKernelError("nothing published")),
        )
        assert cd.try_remote_train(_make_dataset(), settings=MagicMock()) is None
