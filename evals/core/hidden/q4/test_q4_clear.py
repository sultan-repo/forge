import json

import pytest
from ledger import cli


def _seed(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "l.json"
    monkeypatch.setenv("LEDGER_FILE", str(ledger))
    assert cli.main(["add", "2024-03-01", "1.50", "food", "x"]) == 0
    assert cli.main(["add", "2024-03-02", "2.50", "food", "y"]) == 0
    capsys.readouterr()
    return ledger


@pytest.mark.parametrize("args", [[], ["--yes-please"], ["--no"]])
def test_req_b4_clear_refuses_without_yes(tmp_path, monkeypatch, capsys, args):
    ledger = _seed(tmp_path, monkeypatch, capsys)
    before = ledger.read_text()
    assert cli.main(["clear", *args]) == 2
    assert "refusing to clear without --yes" in capsys.readouterr().out
    assert ledger.read_text() == before
    assert len(json.loads(ledger.read_text())) == 2


def test_req_b4_clear_with_yes_empties_store(tmp_path, monkeypatch, capsys):
    ledger = _seed(tmp_path, monkeypatch, capsys)
    assert cli.main(["clear", "--yes"]) == 0
    assert "cleared 2 transactions" in capsys.readouterr().out
    assert json.loads(ledger.read_text()) == []
    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_req_b4_clear_empty_store_reports_zero(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "l.json"
    ledger.write_text("[]")
    monkeypatch.setenv("LEDGER_FILE", str(ledger))
    assert cli.main(["clear", "--yes"]) == 0
    assert capsys.readouterr().out.strip() == "cleared 0 transactions"
    assert json.loads(ledger.read_text()) == []
