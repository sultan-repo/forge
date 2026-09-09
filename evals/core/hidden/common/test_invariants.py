"""INV-1 / INV-2 / INV-3: cent-quantised Decimals; legacy files loadable; core CLI output unchanged."""
import json

from ledger import cli
from ledger.storage import Store


def test_inv_2_legacy_file_loads(tmp_path):
    p = tmp_path / "l.json"
    p.write_text(json.dumps([{"id": "q", "date": "01/02/2024", "amount": 3.3, "category": "c"}]))
    txs = Store(p).load()
    assert len(txs) == 1 and str(txs[0].amount) == "3.30" and txs[0].date.month == 2


def test_inv_3_list_format(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "l.json"))
    cli.main(["add", "2024-03-01", "5.00", "food", "bagel"])
    cli.main(["list"])
    assert "2024-03-01        5.00  food         bagel" in capsys.readouterr().out


def test_inv_1_add_quantises_to_cents(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "l.json"
    monkeypatch.setenv("LEDGER_FILE", str(ledger))
    assert cli.main(["add", "2024-03-01", "5.5", "food"]) == 0
    txs = Store(ledger).load()
    assert len(txs) == 1 and str(txs[0].amount) == "5.50"
    assert json.loads(ledger.read_text())[0]["amount"] == "5.50"
