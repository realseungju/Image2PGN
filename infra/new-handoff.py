#!/usr/bin/env python3
"""new-handoff — system/handoff.md 맨 위에 구조-정확한 handoff 항목을 추가한다.

손편집으로 인한 오류(#N 덮어쓰기·번호 비연속·필드 누락)를 구조적으로 차단한다.
- `#N`은 현재 맨 위 항목 +1로 자동 계산(손으로 못 건드림).
- 날짜는 오늘로 자동.
- 추가 후 10개 초과 시 가장 오래된(#N 최소) 항목을 자동 삭제(이력은 git).
- 의존성 0(표준 라이브러리만).

사용:
  python infra/new-handoff.py --agent Claude --title "T008 툴링" \
      --did "..." --next "..." [--caution "없음"]

근거: ADR-006 / T008. 포맷 규칙: system/conventions.md «handoff.md 포맷».
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

HEADER = re.compile(r"^##\s*#(\d+)\s*·")
MAX_ENTRIES = 10


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def split_entries(lines: list[str]) -> tuple[list[str], list[tuple[int, list[str]]], list[str]]:
    """파일을 (머리말, [(번호, 블록라인)], 꼬리말)로 분리."""
    idxs = [i for i, ln in enumerate(lines) if HEADER.match(ln)]
    if not idxs:
        return lines, [], []
    head = lines[: idxs[0]]
    # 꼬리말: 마지막 항목 뒤의 `>` 주석 등은 마지막 블록에 함께 둔다(단순화)
    entries: list[tuple[int, list[str]]] = []
    bounds = idxs + [len(lines)]
    for k in range(len(idxs)):
        block = lines[bounds[k] : bounds[k + 1]]
        num = int(HEADER.match(block[0]).group(1))
        entries.append((num, block))
    return head, entries, []


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="handoff 항목 추가(구조 자동)")
    ap.add_argument("--agent", required=True, help="에이전트명 (예: Claude)")
    ap.add_argument("--title", required=True, help="괄호 안 한줄 제목")
    ap.add_argument("--did", required=True, help="'한 것' 내용")
    ap.add_argument("--next", required=True, dest="next_", help="'다음에 할 것' 내용")
    ap.add_argument("--caution", default="없음", help="'주의' 내용 (기본: 없음)")
    ap.add_argument("--root", default=None, help="repo 루트 오버라이드(테스트용)")
    args = ap.parse_args()

    for label, val in (("--did", args.did), ("--next", args.next_), ("--title", args.title)):
        if not val.strip():
            print(f"[ERROR] {label} 가 비어있다 — handoff 필드는 비울 수 없다.", file=sys.stderr)
            return 2

    base = Path(args.root).resolve() if args.root else repo_root()
    path = base / "system" / "handoff.md"
    if not path.exists():
        print(f"[ERROR] {path} 없음", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8").splitlines()
    head, entries, _ = split_entries(lines)

    next_n = (entries[0][0] + 1) if entries else 1
    today = date.today().isoformat()

    new_block = [
        f"## #{next_n} · {today} — {args.agent} ({args.title.strip()})",
        f"- 한 것: {args.did.strip()}",
        f"- 다음에 할 것: {args.next_.strip()}",
        f"- 주의: {args.caution.strip()}",
        "",
    ]

    # prepend
    entries.insert(0, (next_n, new_block))

    # 회전: 10개 초과 시 최소 번호 제거
    removed = None
    if len(entries) > MAX_ENTRIES:
        entries.sort(key=lambda e: e[0], reverse=True)
        kept = entries[:MAX_ENTRIES]
        removed = min(e[0] for e in entries)
        entries = sorted(kept, key=lambda e: e[0], reverse=True)

    # 재조립: head + 항목들(번호 내림차순)
    out: list[str] = list(head)
    for _, block in sorted(entries, key=lambda e: e[0], reverse=True):
        out += block
    text = "\n".join(out).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")

    print(f"✓ handoff #{next_n} 추가 ({today}, {args.agent})")
    if removed is not None:
        print(f"  회전: 가장 오래된 #{removed} 삭제 (이력은 git)")
    print("  → 내용 검토 후 'chore(handoff): ...' 로 커밋 (pre-commit 게이트가 형식 재검사)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
