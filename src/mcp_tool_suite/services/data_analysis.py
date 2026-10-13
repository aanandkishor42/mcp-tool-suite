"""Tabular data profiling with the standard library only (no pandas needed).

Detects the delimiter, then profiles each column as numeric (count/mean/median/
stdev/min/max) or categorical (unique count + top values), and returns a small
sample. The LLM turns this profile into plain-language insights.
"""

from __future__ import annotations

import csv
import io
import statistics

_MAX_PROFILE_ROWS = 20000


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _to_float(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def profile_csv(text: str, *, sample_rows: int = 5) -> dict[str, object]:
    """Return a JSON-friendly profile of a CSV/TSV blob."""
    text = text.strip()
    if not text:
        return {"rows": 0, "columns": [], "profiles": {}, "sample": []}

    delimiter = _detect_delimiter(text.splitlines()[0] if text.splitlines() else text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []

    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= _MAX_PROFILE_ROWS:
            break
        rows.append(row)

    profiles: dict[str, dict[str, object]] = {}
    for column in headers:
        values = [row.get(column, "") for row in rows]
        non_missing = [v for v in values if v not in (None, "")]
        numeric = [_to_float(v) for v in non_missing]
        is_numeric = bool(non_missing) and all(v is not None for v in numeric)
        if is_numeric:
            numbers = [v for v in numeric if v is not None]
            profiles[column] = {
                "type": "numeric",
                "count": len(numbers),
                "missing": len(values) - len(non_missing),
                "min": min(numbers),
                "max": max(numbers),
                "mean": round(statistics.fmean(numbers), 4),
                "median": round(statistics.median(numbers), 4),
                "stdev": round(statistics.pstdev(numbers), 4) if len(numbers) > 1 else 0.0,
            }
        else:
            counts: dict[str, int] = {}
            for value in non_missing:
                counts[value] = counts.get(value, 0) + 1
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            profiles[column] = {
                "type": "categorical",
                "count": len(non_missing),
                "missing": len(values) - len(non_missing),
                "unique": len(counts),
                "top": [{"value": v, "count": c} for v, c in top],
            }

    return {
        "rows": len(rows),
        "columns": headers,
        "profiles": profiles,
        "sample": rows[:sample_rows],
    }
