from ledger import cli


def test_req_b4_header_usd(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "l.json"))
    assert cli.main(["add", "2024-03-01", "1.00", "x"]) == 0
    capsys.readouterr()
    assert cli.main(["report", "2024-03"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "Monthly report 2024-03 (USD)"
