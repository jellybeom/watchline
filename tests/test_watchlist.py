"""관심종목 CSV 입출력 테스트."""

from __future__ import annotations

import shutil

import pytest

from watchline import watchlist as W

# 예시 출력 파일의 값
LINES = {
    "900290": (3355, 3215, 3105),
    "025900": (6320, 6100, 5900),
    "010950": (127600, 123700, 120000),
}
DATES = {"900290": "2026-07-31", "025900": "2026-08-07", "010950": "2026-08-07"}
TAGS = {
    "025900": ["#KOSPI하락횡보장", "#상한가", "#테마주", "#시장을이기는종목"],
    "010950": ["#KOSPI하락횡보장", "#시장을이기는종목"],
}


# ────────────────────────── 값 변환 ──────────────────────────


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("'900290", "900290"),
        ("900290", "900290"),
        ("  '025900 ", "025900"),
        ("'0015N0", "0015N0"),
        ("0015n0", "0015N0"),  # 영문 코드는 대문자로 통일
    ],
)
def test_normalize_code(raw, want):
    assert W.normalize_code(raw) == want


def test_tag_roundtrip():
    tags = ["#A", "#B", "#C"]
    assert W.format_tags(tags) == '"#A, #B, #C"'
    assert W.parse_tags(W.format_tags(tags)) == tags


def test_tag_empty():
    assert W.format_tags([]) == ""
    assert W.parse_tags("") == []


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (3355.0, "3355"),
        (3355, "3355"),
        ("", ""),
        (None, ""),
        (1234.5, "1234.5"),
    ],
)
def test_format_price(raw, want):
    assert W.format_price(raw) == want


# ──────────────────────────── 읽기 ────────────────────────────


def test_load_drops_blank_rows(sample_input):
    wl = W.load(sample_input)
    assert [r.code for r in wl.rows] == ["900290", "025900", "010950"]
    assert len(wl.dropped) == 9
    assert not wl.had_extra_cols


def test_load_preserves_existing_values(sample_output):
    wl = W.load(sample_output)
    assert wl.had_extra_cols
    by = {r.code: r for r in wl.rows}
    assert by["025900"].lines == ["6320", "6100", "5900"]
    assert by["025900"].ref_date == "2026-08-07"
    assert by["025900"].tags == TAGS["025900"]
    assert by["900290"].tags == []


def test_load_rejects_missing_code_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_bytes("종목명,현재가\r\nGRT,3895\r\n".encode("cp949"))
    with pytest.raises(ValueError, match="종목코드"):
        W.load(bad)


def test_load_drops_duplicate_codes(tmp_path, sample_input):
    src = sample_input.read_bytes().decode("cp949")
    dup = tmp_path / "dup.csv"
    dup.write_bytes((src + src.splitlines()[1] + "\r\n").encode("cp949"))
    wl = W.load(dup)
    assert len(wl.rows) == 3
    assert any("중복" in why for _, why in wl.dropped)


# ──────────────────────────── 쓰기 ────────────────────────────


def test_roundtrip_is_byte_identical(tmp_path, sample_output):
    """읽고 그대로 저장하면 원본과 바이트 단위로 같아야 한다."""
    work = tmp_path / "rt.csv"
    shutil.copy(sample_output, work)
    W.save(W.load(work))
    assert work.read_bytes() == sample_output.read_bytes()


def test_input_to_output_matches_example(tmp_path, sample_input, sample_output):
    """입력에 값을 채워 저장하면 예시 출력과 바이트 단위로 같아야 한다."""
    work = tmp_path / "work.csv"
    shutil.copy(sample_input, work)

    wl = W.load(work)
    W.apply_lines(wl, LINES)
    for row in wl.rows:
        row.ref_date = DATES[row.code]
        row.tags = TAGS.get(row.code, [])
    W.save(wl)

    assert work.read_bytes() == sample_output.read_bytes()


def test_save_to_new_path(tmp_path, sample_input):
    """다른 이름으로 저장하면 원본은 남고 경로가 새 파일로 바뀐다."""
    src = tmp_path / "today.csv"
    shutil.copy(sample_input, src)
    before = src.read_bytes()

    wl = W.load(src)
    wl.rows[0].ref_date = "2026-08-07"
    dst = tmp_path / "sub" / "복사본.csv"
    saved = W.save(wl, dst)

    assert saved == dst and dst.exists()
    assert src.read_bytes() == before  # 원본 불변
    assert wl.path == dst  # 이후 저장은 새 경로로
    assert W.load(dst).rows[0].ref_date == "2026-08-07"


def test_save_without_path_uses_current(tmp_path, sample_input):
    work = tmp_path / "w.csv"
    shutil.copy(sample_input, work)
    wl = W.load(work)
    wl.rows[0].ref_date = "2026-08-07"
    assert W.save(wl) == work
    assert W.load(work).rows[0].ref_date == "2026-08-07"


def test_save_failure_leaves_original(tmp_path, monkeypatch, sample_output):
    work = tmp_path / "w.csv"
    shutil.copy(sample_output, work)
    before = work.read_bytes()

    def boom(*a, **k):
        raise OSError("디스크 오류")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        W.save(W.load(work))
    assert work.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


# ────────────────────────── 선 채우기 ──────────────────────────


def test_apply_lines_keeps_existing_when_missing(sample_output):
    wl = W.load(sample_output)
    stat = W.apply_lines(wl, {"025900": (1, 2, 3)})
    by = {r.code: r for r in wl.rows}
    assert by["025900"].lines == ["1", "2", "3"]
    assert by["900290"].lines == ["3355", "3215", "3105"]  # 기존 값 보존
    assert stat == {"filled": 1, "kept": 2, "blank": 0}


def test_apply_lines_blank_when_no_data(sample_input):
    wl = W.load(sample_input)
    stat = W.apply_lines(wl, {})
    assert stat["blank"] == 3
    assert all(not r.has_lines for r in wl.rows)


# ──────────────────────────── 태그 ────────────────────────────


def test_load_tags_creates_default(tmp_path):
    p = tmp_path / "tags.txt"
    tags = W.load_tags(p)
    assert p.exists()
    assert tags == W.DEFAULT_TAGS


def test_load_tags_skips_comments_and_dupes(tmp_path):
    p = tmp_path / "tags.txt"
    p.write_text("#A\n\n#! 주석\n#B\n#A\n", encoding="utf-8")
    assert W.load_tags(p) == ["#A", "#B"]


# ─────────────────── 기준봉·태그 가져오기 ───────────────────


def test_merge_copies_only_date_and_tags(sample_input, sample_output):
    """가격·메모 등 원본 열과 1~3선은 절대 바뀌지 않아야 한다."""
    target = W.load(sample_input)
    source = W.load(sample_output)

    W.apply_lines(target, {"900290": (1, 2, 3)})
    base_before = [dict(r.base) for r in target.rows]
    lines_before = [list(r.lines) for r in target.rows]

    stat = W.merge_metadata(target, source)

    by = {r.code: r for r in target.rows}
    assert by["900290"].ref_date == "2026-07-31"
    assert by["025900"].tags == [
        "#KOSPI하락횡보장",
        "#상한가",
        "#테마주",
        "#시장을이기는종목",
    ]
    assert stat["matched"] == 3
    assert stat["date_filled"] == 3

    assert [dict(r.base) for r in target.rows] == base_before
    assert [list(r.lines) for r in target.rows] == lines_before


def test_merge_keeps_existing_values(sample_input, sample_output):
    target = W.load(sample_input)
    target.rows[0].ref_date = "2026-01-01"
    target.rows[0].tags = ["#상한가"]

    stat = W.merge_metadata(target, source=W.load(sample_output))

    assert target.rows[0].ref_date == "2026-01-01"  # 사용자가 넣은 값 보존
    assert target.rows[0].tags == ["#상한가"]
    assert stat["date_kept"] == 1
    assert stat["tags_kept"] == 0  # 원본에 태그가 없던 종목


def test_merge_overwrite_mode(sample_input, sample_output):
    target = W.load(sample_input)
    target.rows[1].ref_date = "2026-01-01"

    W.merge_metadata(target, W.load(sample_output), overwrite=True)
    assert target.rows[1].ref_date == "2026-08-07"


def test_merge_counts_unmatched(sample_input, sample_output):
    target = W.load(sample_input)
    source = W.load(sample_output)
    source.rows = [r for r in source.rows if r.code != "900290"]

    stat = W.merge_metadata(target, source)
    assert stat["matched"] == 2
    assert stat["unmatched"] == 1


# ─────────────────── 여러 파일 이어붙이기 ───────────────────


def test_append_merges_rows(sample_input, sample_output):
    base = W.load(sample_input)
    other = W.load(sample_output)
    other.rows = other.rows[:1]
    other.rows[0].code = "111111"
    other.rows[0].code_raw = "'111111"

    stat = W.append_watchlist(base, other)
    assert stat["added"] == 1
    assert [r.code for r in base.rows] == ["900290", "025900", "010950", "111111"]


def test_append_skips_duplicate_codes(sample_input, sample_output):
    base = W.load(sample_input)
    stat = W.append_watchlist(base, W.load(sample_output))
    assert stat["added"] == 0
    assert stat["duplicate"] == 3
    assert set(stat["dup_codes"]) == {"900290", "025900", "010950"}
    assert len(base.rows) == 3  # 먼저 들어온 쪽이 남는다


def test_append_keeps_first_values(sample_input, sample_output):
    """중복 종목은 나중 파일의 값으로 덮이지 않는다."""
    base = W.load(sample_input)
    base.rows[0].ref_date = "2026-01-01"
    W.append_watchlist(base, W.load(sample_output))
    assert base.rows[0].ref_date == "2026-01-01"


def test_append_reports_column_difference(sample_input, sample_output):
    base = W.load(sample_input)
    other = W.load(sample_output)
    other.header = other.header + ["추가열"]
    stat = W.append_watchlist(base, other)
    assert "추가열" in stat["col_diff"]


def test_merged_list_saves_as_one_file(tmp_path, sample_input, sample_output):
    """입력이 둘이어도 결과는 파일 하나이며 열 구성은 첫 파일을 따른다."""
    base = W.load(sample_input)
    other = W.load(sample_output)
    for i, r in enumerate(other.rows):
        r.code = f"90000{i}"
        r.code_raw = f"'90000{i}"
    W.append_watchlist(base, other)

    out = tmp_path / "merged.csv"
    W.save(base, out)

    again = W.load(out)
    assert len(again.rows) == 6
    assert again.header == base.header
    assert again.rows[3].ref_date == "2026-07-31"  # 두 번째 파일의 값 유지
