from __future__ import annotations

from typing import Literal

Severity = Literal["critical", "high", "medium", "low"]
IssueCategory = Literal[
    "completeness", "validity", "uniqueness", "consistency", "timeliness"
]
IssueStatus = Literal["open", "acknowledged", "resolved", "suppressed"]
DriftKind = Literal[
    "column_added", "column_removed", "type_changed", "nullable_changed"
]
