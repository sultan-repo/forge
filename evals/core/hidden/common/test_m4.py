import json
from datetime import date
from decimal import Decimal

from ledger import cli

# budgets.load_budgets is the API named by REQ-4.1; a missing module fails the required tests.
from ledger.models import Transaction


def load_budgets(path):
    from ledger.budgets import load_budgets as implementation
    return implementation(path)


def test_req_4_1_budgets_are_decimal(tmp_path):
    p = tmp_path / "b.json"; p.write_text(json.dumps({"food": 100, "rent": "900.50"}))
    b = load_budgets(p)
    assert b == {"food": Decimal(100), "rent": Decimal("900.50")}
    assert all(isinstance(v, Decimal) for v in b.values())


def test_req_4_2_check_over_and_within(store, tmp_path, monkeypatch, capsys):
    store.add(Transaction("a", date(2024, 3, 1), Decimal("120.00"), "food"))
    b = tmp_path / "b.json"; b.write_text(json.dumps({"food": 100}))
    monkeypatch.setenv("LEDGER_FILE", str(store.path))
    assert cli.main(["check", "2024-03", str(b)]) == 1
    assert "OVER food by 20.00" in capsys.readouterr().out
    assert cli.main(["check", "2024-04", str(b)]) == 0
    assert "within budget" in capsys.readouterr().out


def test_req_4_1_json_numeric_limit_is_exact_cents(tmp_path):
    # INV-1: amounts are Decimal quantised to cents. A JSON limit written as the number 100.10
    # denotes exactly 100.10; decoding it through binary float would yield 100.0999... and a
    # wrong `OVER ... by` amount in REQ-4.2.
    p = tmp_path / "b.json"; p.write_text('{"food": 100.10}')
    assert load_budgets(p) == {"food": Decimal("100.10")}


def test_req_4_2_over_amount_exact_to_the_cent(store, tmp_path, monkeypatch, capsys):
    store.add(Transaction("a", date(2024, 3, 1), Decimal("100.11"), "food"))
    b = tmp_path / "b.json"; b.write_text('{"food": 100.10}')
    monkeypatch.setenv("LEDGER_FILE", str(store.path))
    assert cli.main(["check", "2024-03", str(b)]) == 1
    assert "OVER food by 0.01" in capsys.readouterr().out
