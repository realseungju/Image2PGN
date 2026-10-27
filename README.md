# ChessLens

[English](README.md) · [한국어](README.ko.md)

**Turn a chess screenshot into a reviewed position, then explore it with Stockfish.**

ChessLens runs on your computer. Upload a PNG/JPEG, correct the board if needed,
confirm the game state, and replay engine variations. You can also find matching
historical games and compare a selected recorded move with an engine recommendation.

The repository keeps its original name, `Image2PGN`. A single screenshot does not
contain enough information to reconstruct a game's move history.

[Visual walkthrough](https://whichai.fyi/chesslens#image-flow) · [Report an issue](https://github.com/realseungju/Image2PGN/issues)

The walkthrough uses prerecorded examples. The application below performs local
recognition and analysis. Its explanation UI currently uses Korean labels; this
README includes their English meaning.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and a
separately installed [Stockfish executable](https://stockfishchess.org/download/).
uv prepares Python 3.12 and the project environment. The first run downloads
dependencies; subsequent runs reuse them. No LLM service or API key is required.

```sh
git clone https://github.com/realseungju/Image2PGN.git
cd Image2PGN
uv run chesslens
```

If Stockfish is not on `PATH`, give its executable path:

```powershell
uv run chesslens --engine "C:\tools\stockfish\stockfish.exe"
```

```sh
# Linux/macOS example
uv run chesslens --engine /path/to/stockfish
```

The launcher checks the bundled classifier and the UCI engine, starts the server,
and opens **http://127.0.0.1:8771/**. Stop it with **Ctrl+C** in the terminal.
Stockfish must be extracted from its archive before you select the executable.

```sh
uv run chesslens --doctor                 # Check configuration without serving
uv run chesslens --no-browser             # Print the URL; do not open a browser
uv run chesslens --port 8787              # Use another port
uv run chesslens --model /path/model.pt   # Use a compatible custom checkpoint
```

`CHESSLENS_MODEL_PATH` and `CHESSLENS_ENGINE_PATH` are supported; explicit command
arguments take precedence. Engine discovery also checks `PATH`, `./stockfish/`,
and `~/Documents/stockfish/` for Windows `stockfish*.exe` files. Python imports and
the bundled model do not depend on another repository or a personal directory.

## Upload, review, analyze

1. Click **체스 화면 첨부** (*Attach chess screenshot*) and choose a PNG/JPEG.
   You can try `image/chess_img4.png` from this repository. Uploads are limited
   to 10 MiB and 24 million pixels.
2. Click **분석 시작** (*Start analysis*). Recognition proposes a board; it does
   not establish whose turn it is or what happened earlier in the game.
3. Compare the detected board with the source crop. Open **판 인식 수정**
   (*Correct recognition*), choose a piece or empty square, and click any square
   that needs correction. Yellow squares need particular attention.
4. Choose **백 차례 / 흑 차례** (*White / Black to move*). Open
   **게임 상태와 전체 FEN 확인** (*Game state and full FEN*) to review or change
   castling, en passant, and move counters. Screenshot-derived special rights
   initially default to none (`-`); confirm or correct them yourself.
5. Keep **판 전체 분석** (*Whole-board analysis*) or select a particular opposing
   piece/capture to inspect. Confirm the piece positions and game-state fields,
   and any overlay review requested by the page.
6. Click **이 판으로 분석** (*Analyze this position*). Explore the returned branches
   with playback, previous/next, and board flip. **새로운 분석** (*New analysis*) starts another position.

Known FENs can be entered in **판 정보 직접 입력 (FEN)** instead of uploading an
image. Engine continuations are hypothetical; they are not recovered move history.

## Recorded games and selected-move comparison

- The bundled catalog has **12 selected historical games**, with source links and
  provenance in [the catalog notes](image2pgn/data/README.md).
- After a position is confirmed and analyzed, matching recorded games can be
  replayed from their start or the matching position. A match is a candidate,
  not proof of where a screenshot came from.
- During recorded playback, select a move and use **이 수와 엔진 추천 비교**
  (*Compare this move with the engine*). Recorded and recommended continuations
  remain separate. A different recommendation alone is not labelled a mistake.
- Optional **마스터 DB 연결** (*Master DB connection*) enables Lichess Masters
  lookup. Enter your token directly in the local app. No permission scopes are
  needed for this lookup. Both returned player ratings must be at least 2400;
  ordinary player games are not searched.
- Tokens default to memory. Optional encrypted persistence uses Windows-user
  DPAPI and is unavailable on other operating systems. Disconnecting the local
  app does not revoke a token on Lichess.

## What's included

```text
screenshot → board detection → 64-square classification
           → human review of placement and game state
           → Stockfish → legally replayed variations
                        ↘ matching games → recorded move comparison
```

| Location | Purpose |
| --- | --- |
| `image2pgn/launcher.py` | One-command launch and configuration checks |
| `image2pgn/webapp.py`, `explanation_api.py` | Local upload API and review/analysis jobs |
| `image2pgn/board*.py`, `cnn.py`, `orientation.py` | Board geometry and piece recognition |
| `image2pgn/analyze.py`, `explanations.py` | Engine analysis and verified move explanations |
| `image2pgn/master_games.py`, `move_comparison.py` | Matching recorded games and move comparison |
| `image2pgn/web/` | Browser UI, piece SVGs, and fonts |
| `image2pgn/assets/` | Bundled experimental classifier and its provenance |
| `desktop/` | Optional Electron popup adapter |
| `infra/`, `tests/` | Experiments and regression checks |

The main UI is `/`; `/explain` remains an alias. The older multi-image workspace
is preserved at `/workspace`, with a link from the main app. Its confirmed FEN
can be passed to the explanation screen.

## Models, engines, and limits

A small experimental PieceCNN checkpoint is included so image upload works in
a clean checkout. Its SHA-256 and source experiment are recorded in
[model.json](image2pgn/assets/model.json); see the
[model notes](image2pgn/assets/README.md). Custom checkpoints must have the
compatible PieceCNN architecture and class names.

Stockfish is not bundled or downloaded automatically. Choose a binary compatible
with your CPU from its official distribution. The default uv configuration uses
CPU PyTorch on Windows/Linux. GPU training is optional and not needed to run the app.

- Review every position: alignment, orientation, overlays, unfamiliar themes,
  piece colors, and small pieces can produce recognition errors.
- A screenshot cannot reliably establish turn, castling/en-passant rights,
  move counters, or earlier moves. FEN defaults are not evidence of those facts.
- Limited-time engine search can change with depth, time, or engine version.
  Mate scores are not converted into a guaranteed pawn-loss estimate.
- This is a local prototype, not an internet-facing hosted service. The launcher
  binds to loopback; existing Host/Origin and session-token checks remain enabled.
- Images are processed locally and temporary input files are removed. Result
  crops live in the local session until cancellation/expiry. Optional Masters
  lookup sends a position query, not the screenshot.
- New screenshots, DPI/scaling combinations, Linux, and macOS still need user
  validation. Automated checks and development examples are not general accuracy claims.

## Development and advanced use

```sh
uv sync --group dev
uv run pytest tests -q
uv run python infra/check_javascript.py
uv build
```

The committed `uv.lock` pins the resolved environment. Node.js is needed for
JavaScript regression checks, not for running the local web app. The check
runner works on Windows/Linux and creates synthetic inputs for the label-review
tool; no private training data is required.

Existing CLI recognition/analysis and training commands remain available:

```sh
uv run python -m image2pgn --help
uv run python -m image2pgn analyze-fen --fen "FEN" --engine /path/to/stockfish
```

Historical training commands and development measurements are preserved in
[archived workflows](docs/legacy-workflows.md) and [MODEL_HISTORY.md](MODEL_HISTORY.md).
They are not the current quick start or a performance guarantee. The optional
desktop popup is documented in [desktop/README.md](desktop/README.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Stockfish not found | Extract the download and pass the executable with `--engine`; a folder/ZIP is not an executable. |
| Engine cannot start | Select a build compatible with your OS/CPU; run `uv run chesslens --doctor`. |
| Model missing/checksum mismatch | Restore `image2pgn/assets/` from the repository, or specify your own compatible model. |
| Port already in use | Stop the other local instance or use `--port 8787`. |
| Incorrect board/capture options | Correct pieces, turn, and game-state fields before confirming. |
| Masters unavailable | Offline catalog/analysis still work; external lookup needs a valid user-entered token and network access. |

Third-party artwork and font notices are retained in
[pieces/NOTICE.txt](image2pgn/web/pieces/NOTICE.txt),
[pieces/COPYING.txt](image2pgn/web/pieces/COPYING.txt), and
[Pretendard-LICENSE.txt](image2pgn/web/fonts/Pretendard-LICENSE.txt).
Stockfish and python-chess retain their own licenses; consult their distributions
when redistributing components. No project-wide license is added by this cleanup.
