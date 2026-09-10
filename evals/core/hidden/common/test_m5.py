import json
from datetime import date
from decimal import Decimal

from ledger import cli

# REQ-5.1 is a CLI contract (`ledger export`); no module name is assumed.
from ledger.models import Transaction


def test_req_5_1_export_cli(store, tmp_path, monkeypatch, capsys):
    store.add(Transaction("a", date(2024, 3, 1), Decimal("1.50"), "food", "x"))
    store.add(Transaction("b", date(2024, 3, 2), Decimal("2.50"), "food", "y"))
    monkeypatch.setenv("LEDGER_FILE", str(store.path))
    out = tmp_path / "out.json"
    assert cli.main(["export", str(out)]) == 0
    assert "exported 2 transactions" in capsys.readouterr().out
    data = json.loads(out.read_text())
    assert [d["amount"] for d in data] == ["1.50", "2.50"]
