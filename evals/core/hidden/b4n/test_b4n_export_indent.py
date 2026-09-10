import json

from ledger import cli


def test_req_b4_export_uses_four_space_indent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "l.json"))
    assert cli.main(["add", "2024-03-01", "1.50", "food", "x"]) == 0
    assert cli.main(["add", "2024-03-02", "2.50", "food", "y"]) == 0
    out = tmp_path / "out.json"
    capsys.readouterr()
    assert cli.main(["export", str(out)]) == 0
    assert "exported 2 transactions" in capsys.readouterr().out
    text = out.read_text()
    data = json.loads(text)
    assert [d["amount"] for d in data] == ["1.50", "2.50"]
    # Same content, rendered with 4-space indentation (standard JSON pretty-printing).
    assert text.strip() == json.dumps(data, indent=4)
