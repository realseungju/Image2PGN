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