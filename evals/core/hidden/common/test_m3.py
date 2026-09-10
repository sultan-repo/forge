import json
from decimal import Decimal

from ledger import cli

# report.monthly_totals is the API named by REQ-3.1; a missing module fails the required tests.
from ledger.storage import Store


def monthly_totals(*args):
    from ledger.report import monthly_totals as implementation
    return implementation(*args)


LEGACY = [
    {"id": "z1", "date": "2024-05-02", "amount": 0.1, "category": "a", "note": ""},
    {"id": "z2", "date": "2024-05-02", "amount": 0.2, "category": "a", "note": "x"},
    {"id": "z3", "date": "07/05/2024", "amount": "$7.25", "category": "b", "note": ""},
    {"id": "z4", "date": "2024-05-30", "amount": "1.00", "category": "b", "note": ""},
    {"id": "z5", "date": "2024-06-01", "amount": "99.00", "category": "a", "note": ""},
]


def test_req_3_1_totals_exact_on_legacy_data(tmp_path):
    p = tmp_path / "l.json"; p.write_text(json.dumps(LEGACY))
    assert monthly_totals(Store(p), 2024, 5) == {"a": Decimal("0.30"), "b": Decimal("8.25")}


def test_req_3_1_totals_sorted_and_month_scoped(tmp_path):
    p = tmp_path / "l.json"; p.write_text(json.dumps(LEGACY))
    assert list(monthly_totals(Store(p), 2024, 5)) == ["a", "b"]
    assert monthly_totals(Store(p), 2024, 6) == {"a": Decimal("99.00")}


def test_req_3_2_cli_table(tmp_path, monkeypatch, capsys):
    p = tmp_path / "l.json"; p.write_text(json.dumps(LEGACY))
    monkeypatch.setenv("LEDGER_FILE", str(p))
    assert cli.main(["report", "2024-05"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("Monthly report 2024-05 (")
    assert lines[-1].startswith("TOTAL") and "8.55" in lines[-1]
