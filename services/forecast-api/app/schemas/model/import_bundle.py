"""`POST /v1/model/versions/import`'s response -- registers an
already-trained model bundle (`service/ml/model_import.py`'s own
docstring has the bundle format) as a new registry version, without
going through this service's own training loop. Mirrors just enough of
`EvaluationSummaryOut` to show the caller the live-evaluation-gate
result that ran immediately after registration, without a second
`GET .../evaluation` round-trip.

`eval_gate_passed=None` means the gate itself failed to run (a real,
logged, non-fatal degradation -- see `model_import.py`'s
`_run_eval_gate`), not that it ran and failed -- `False` is reserved for
"ran, and failed", same "absent signal isn't a negative result"
convention this codebase already uses elsewhere (e.g. `GET .../
evaluation`'s own `null` for "never evaluated")."""

from __future__ import annotations

from app.schemas.base import AppBaseModel
from app.schemas.model.evaluation import RegionEvaluationOut


class ModelImportResponse(AppBaseModel):
    run_id: str
    model_version: str
    model_name: str
    architecture: str
    eval_gate_passed: bool | None = None
    eval_gate_mape: float | None = None
    eval_gate_regions: list[RegionEvaluationOut] = []
