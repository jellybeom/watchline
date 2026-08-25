"""names: 종목코드 → 종목명 캐시."""

from __future__ import annotations

import json
from pathlib import Path

from watchline import names, watchlist


def row(code: str, name: str) -> watchlist.Row:
    return watchlist.Row(base={"종목명": name}, code=code, code_raw=f"'{code}'")


def test_load_missing_file_is_empty(tmp_path: Path):
    assert names.load(tmp_path / "없음.json") == {}


def test_load_broken_file_is_empty(tmp_path: Path):
    p = tmp_path / "names.json"
    p.write_text("{망가진", encoding="utf-8")
    assert names.load(p) == {}


def test_load_wrong_shape_is_empty(tmp_path: Path):
    p = tmp_path / "names.json"
    p.write_text('["목록"]', encoding="utf-8")
    assert names.load(p) == {}


def test_load_drops_bad_entries(tmp_path: Path):
    p = tmp_path / "names.json"
    p.write_text(
        json.dumps({"005930": "삼성전자", "000660": "", "111111": 7}),
        encoding="utf-8",
    )
    assert names.load(p) == {"005930": "삼성전자"}


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "names.json"
    names.save({"005930": "삼성전자", "0015N0": "아로마티카"}, p)
    assert names.load(p) == {"005930": "삼성전자", "0015N0": "아로마티카"}


def test_save_writes_readable_utf8(tmp_path: Path):
    p = tmp_path / "names.json"
    names.save({"005930": "삼성전자"}, p)
    assert "삼성전자" in p.read_text(encoding="utf-8")  # \uXXXX로 도망가지 않는다


def test_save_leaves_no_temp_files(tmp_path: Path):
    p = tmp_path / "names.json"
    names.save({"005930": "삼성전자"}, p)
    assert [x.name for x in tmp_path.iterdir()] == ["names.json"]


def test_load_uppercases_codes(tmp_path: Path):
    p = tmp_path / "names.json"
    p.write_text(json.dumps({"0015n0": "아로마티카"}), encoding="utf-8")
    assert names.load(p) == {"0015N0": "아로마티카"}


def test_merge_adds_and_counts_new(tmp_path: Path):
    m = {"005930": "삼성전자"}
    added = names.merge(m, [row("005930", "삼성전자"), row("000660", "SK하이닉스")])
    assert added == 1
    assert m["000660"] == "SK하이닉스"


def test_merge_updates_renamed_stock():
    m = {"005930": "옛이름"}
    names.merge(m, [row("005930", "삼성전자")])
    assert m["005930"] == "삼성전자"


def test_merge_skips_rows_without_name():
    m: dict[str, str] = {}
    names.merge(m, [row("005930", ""), row("", "이름만")])
    assert m == {}


def test_update_from_writes_only_when_changed(tmp_path: Path):
    p = tmp_path / "names.json"
    assert names.update_from([row("005930", "삼성전자")], p) == 1
    before = p.stat().st_mtime_ns
    assert names.update_from([row("005930", "삼성전자")], p) == 0
    assert p.stat().st_mtime_ns == before  # 손대지 않는다


def test_update_from_preserves_existing_entries(tmp_path: Path):
    p = tmp_path / "names.json"
    names.save({"000660": "SK하이닉스"}, p)
    names.update_from([row("005930", "삼성전자")], p)
    assert names.load(p) == {"000660": "SK하이닉스", "005930": "삼성전자"}
