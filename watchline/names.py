"""종목코드 → 종목명 캐시.

작도 파일에는 종목코드만 있어서 HUD 혼자서는 이름을 알 수 없다.
편집기가 관심종목 CSV를 열 때마다 이름을 여기에 쌓아두고,
HUD는 시작할 때 한 번 읽는다.

캐시가 없거나 종목이 빠져 있어도 코드로 표시하면 되므로,
이 파일이 없다고 해서 어느 쪽도 멈추지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import settings


def load(path: str | Path | None = None) -> dict[str, str]:
    """캐시를 읽는다. 없거나 깨져 있으면 빈 사전을 준다."""
    p = Path(path) if path else settings.names_file
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k).upper(): str(v)
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    }


def save(mapping: dict[str, str], path: str | Path | None = None) -> Path:
    """임시 파일에 쓰고 교체한다. 실패해도 기존 캐시가 남는다."""
    p = Path(path) if path else settings.names_file
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(mapping.items())), f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return p


def merge(mapping: dict[str, str], rows) -> int:
    """관심종목 행에서 이름을 거둬 사전에 더한다. 새로 들어온 개수를 준다.

    이름이 바뀐 종목은 최신 이름으로 덮어쓴다.
    """
    added = 0
    for row in rows:
        code = (getattr(row, "code", "") or "").upper()
        name = (getattr(row, "name", "") or "").strip()
        if not code or not name:
            continue
        if mapping.get(code) != name:
            added += code not in mapping
            mapping[code] = name
    return added


def update_from(rows, path: str | Path | None = None) -> int:
    """읽고, 더하고, 바뀌었을 때만 다시 쓴다."""
    p = Path(path) if path else settings.names_file
    before = load(p)
    after = dict(before)
    merge(after, rows)
    if after == before:
        return 0
    save(after, p)
    return len(after) - len(before)
