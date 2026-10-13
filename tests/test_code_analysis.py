from __future__ import annotations

from mcp_tool_suite.services.code_analysis import analyze_python, looks_like_python

_SAMPLE = """\
def compute(a, b=[]):
    try:
        return eval(a)
    except:
        return b
# TODO: replace eval
""".replace("def compute", "def compute")


def test_analyze_python_structure_and_findings():
    report = analyze_python(_SAMPLE).as_dict()
    assert report["syntax_ok"] is True
    assert any(f["name"] == "compute" for f in report["functions"])
    rules = {finding["rule"] for finding in report["findings"]}
    assert {"mutable-default", "bare-except", "dangerous-call", "todo"} <= rules
    assert report["metrics"]["high_severity"] >= 1


def test_analyze_python_syntax_error():
    report = analyze_python("def broken(:").as_dict()
    assert report["syntax_ok"] is False
    assert report["errors"]


def test_long_line_finding():
    report = analyze_python("x = " + "1 + " * 40 + "1\n").as_dict()
    assert any(f["rule"] == "long-line" for f in report["findings"])


def test_looks_like_python():
    assert looks_like_python("x = 1\n") is True
    assert looks_like_python("this is just prose, not code !!") is False
