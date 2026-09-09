"""REQ-2.1/2.2/2.3 through the public CLI and Store contracts only."""
import csv
from decimal import Decimal

from ledger import cli
from ledger.storage import Store

CSV = "date,amount,category,note\n2024-04-01,10.00,food,a\n2024-04-02,2.50,transport,b\n2024-04-01,10.00,food,a\n"


def _import(tmp_path, monkeypatch, capsys, text=CSV, name="x.csv"):
    ledger = tmp_path / "l.json"
    monkeypatch.setenv("LEDGER_FILE", str(ledger))
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    rc = cli.main(["import", str(path)])
    return rc, capsys.readouterr().out, Store(ledger), path


def test_req_2_1_parses_columns(tmp_path, monkeypatch, capsys):
    rc, _, store, _ = _import(tmp_path, monkeypatch, capsys)
    assert rc == 0
    txs = store.load()
    assert {t.category for t in txs} == {"food", "transport"}
    assert {str(t.amount) for t in txs} == {"10.00", "2.50"}
    assert all(isinstance(t.amount, Decimal) for t in txs)
    assert {t.note for t in txs} == {"a", "b"}


def test_req_2_2_skips_duplicates(tmp_path, monkeypatch, capsys):
    rc, _, store, path = _import(tmp_path, monkeypatch, capsys)
    assert rc == 0 and len(store.load()) == 2
    assert cli.main(["import", str(path)]) == 0
    assert len(store.load()) == 2


def test_req_2_3_cli_summary(tmp_path, monkeypatch, capsys):
    rc, out, _, _ = _import(tmp_path, monkeypatch, capsys)
    assert rc == 0
    assert "imported 2, skipped 1" in out


def _quoted_newline_csv():
    # Two valid RFC 4180 records: same date and amount, notes "ab\ncd" (quoted, embedded newline)
    # and "abcd". They are distinct transactions under REQ-2.2 identity (date, amount, note).
    import io
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "amount", "category", "note"])
    writer.writerow(["2024-04-01", "10.00", "food", "ab\ncd"])
    writer.writerow(["2024-04-01", "10.00", "food", "abcd"])
    return buffer.getvalue()


def test_req_2_1_quoted_newline_note_preserved(tmp_path, monkeypatch, capsys):
    rc, _, store, _ = _import(tmp_path, monkeypatch, capsys, text=_quoted_newline_csv(), name="q.csv")
    assert rc == 0
    assert sorted(t.note for t in store.load()) == ["ab\ncd", "abcd"]


def test_req_2_2_duplicate_identity_includes_note(tmp_path, monkeypatch, capsys):
    rc, _, store, path = _import(tmp_path, monkeypatch, capsys, text=_quoted_newline_csv(), name="q.csv")
    assert rc == 0 and len(store.load()) == 2
    assert cli.main(["import", str(path)]) == 0
    assert sorted(t.note for t in store.load()) == ["ab\ncd", "abcd"]


def test_req_2_3_summary_across_repeated_imports(tmp_path, monkeypatch, capsys):
    rc, first, _, path = _import(tmp_path, monkeypatch, capsys, text=_quoted_newline_csv(), name="q.csv")
    assert rc == 0 and "imported 2, skipped 0" in first
    assert cli.main(["import", str(path)]) == 0
    assert "imported 0, skipped 2" in capsys.readouterr().out
