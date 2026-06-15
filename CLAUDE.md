# CLAUDE.md — Image2PGN / ChessLens (code repo)

이 repo는 **코드 전용**이다. 프로젝트의 두뇌(지식·spec·task)는 별도 repo에 있다:
→ https://github.com/realseungju/shared-brain

## 작업 규칙

1. 구현 전 두뇌에서 읽기 (해당 프로젝트 docs가 있을 경우):
   - `docs/projects/image2pgn.md` (프로젝트 컨텍스트)
   - 담당 task 파일 + 연결된 spec
2. 이 repo에는 코드/데이터/결과물만 커밋한다. 지식·결정·task 갱신은 두뇌 repo에.
3. 작업 완료 시: 커밋/PR 링크를 두뇌 repo의 task 파일과 handoff.md에 기록한다.
4. 커밋 형식: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:` ...)
5. Python: 가상환경 사용 (`venv/`), `requirements.txt` 갱신 필수

## 프로젝트 핵심 (요약)

- ChessLens: 체스 보드 스크린샷 → FEN → Stockfish 분석 → 최고 수, 위협, 전략 추천
- 원래 Image2PGN에서 방향 전환: 단일 이미지로 PGN 복원은 불가능 → FEN 추출 + 엔진 분석이 핵심
- Python 패키지 (`image2pgn`), CNN 모델 실험 병행
- 메인 도구: `python -m image2pgn analyze-image --image <path> --engine <stockfish>`
- 상세·리스크·실험 현황은 두뇌 repo 참고

## 종료 절차 (필수 — 출력 계약)

모든 작업의 마지막 출력은 **반드시 아래 HANDOFF 블록으로 끝낸다.**
이 블록 없이 응답을 끝내면 작업은 미완료이며, 다음 세션에서 처리되지 않는다.
빈칸을 남기지 마라 — 채울 수 없으면 작업이 끝나지 않은 것이다.

```
=== HANDOFF (필수) ===
1. 두뇌 repo handoff.md 맨 위에 아래 항목 추가:

## {YYYY-MM-DD} — Claude
- 한 것: {요약 + 커밋 해시}
- 다음에 할 것: {다음 에이전트가 집어들 것}
- 주의: {함정 / 미해결 / 없으면 "없음"}

2. task 상태 이동: doing/ → done/ (또는 backlog 복귀 + 사유)
3. 커밋: chore(handoff): update after {task-id}
======================
```

- "한 것"의 커밋 해시는 실제 커밋 후에만 존재한다 → 이 칸을 채우려면 작업을 실제로 끝내고 회고해야 한다.
- handoff는 최신 10개만 유지 (초과 시 가장 오래된 항목 삭제, 이력은 git에 남는다).