from __future__ import annotations

from mcp_tool_suite.services.data_analysis import profile_csv

_CSV = "name,age,city\nAlice,30,NY\nBob,25,LA\nCara,,NY\n"


def test_profile_csv_numeric_and_categorical():
    profile = profile_csv(_CSV)
    assert profile["rows"] == 3
    assert profile["columns"] == ["name", "age", "city"]

    age = profile["profiles"]["age"]
    assert age["type"] == "numeric"
    assert age["count"] == 2
    assert age["missing"] == 1
    assert age["mean"] == 27.5

    city = profile["profiles"]["city"]
    assert city["type"] == "categorical"
    assert city["unique"] == 2
    assert city["top"][0] == {"value": "NY", "count": 2}


def test_profile_csv_empty():
    profile = profile_csv("   ")
    assert profile["rows"] == 0
    assert profile["columns"] == []
