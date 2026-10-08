# ChessLens companion popup

Start the existing Python environment with a local PieceCNN model and Stockfish:

```powershell
.\.venv\Scripts\python.exe -m image2pgn.companion --port 8771
```

Open `http://127.0.0.1:8771/explain` for standalone image upload, board editing,
explicit game-state review, and verified move playback. The old `/` desk also
links a confirmed FEN to this page. No LLM API key is needed by ChessLens.

For a native transparent popup, set `CHESSLENS_ELECTRON_PATH` to an existing
Electron executable. The default reuses the sibling shared-brain Frieren runtime.
No Electron package is downloaded by this module. With the service running:

```powershell
& $env:CHESSLENS_ELECTRON_PATH desktop/main.cjs
```

External callers get an ephemeral token from `GET /api/explanations/session` and
send it in `X-ChessLens-Token`. Submit multipart `POST /api/explanations` with
`request_id`, `question`, `image` (PNG/JPEG), `show_popup=true`, and optional
physical-pixel `source_bounds` JSON (`x`, `y`, `width`, `height`). Instead of an
image, a manually known full `fen` may be submitted. `confirmed_history=true`
means the caller explicitly confirmed every game-state field, never inferred
them from piece placement. Optional `before_fen` plus legal `target_uci` must
reproduce the current board, side and special rights. PGN/video inputs are not
implemented in this version.

Poll `GET /api/explanations/{job_id}`. For `needs_input`, show the supplied local
`gui_url`. The GUI posts `revision`, `question_id=confirm-position`, full `fen`,
`confirmed_history=true`, and optional `before_fen`/`target_uci` to `/answers`.
Only `ready` contains a completed verified result and short `brief_en`.
`POST /cancel` is idempotent and closes the attached popup through its status
poll. Cancellation does not erase an already completed result; source crops
are removed. Sessions expire after 30 minutes when new jobs are created.

The service uses one worker, at most 24 sessions, loopback Host/peer and Origin
checks, and token authentication for explanation jobs. It rejects remote image
URLs and oversized images. The older recognition/analysis routes keep their
existing interface but now reject nonlocal or cross-origin API requests.
Screenshot originals are temporary; browser-cache responses for jobs use
`no-store`. Popup profiles/cache live under ignored `.tmp/desktop/`.

The engine uses one thread, 64 MiB hash, 700 ms per call, at most three calls.
Capture variations are labelled conditional unless the reply is the sole legal
move. Score viewpoint is fixed; each branch also identifies its evaluated FEN.
All step captures/checkmate facts and before/after FENs come from legal replay.
The limited-time PV is not an independently proven game-history reconstruction
or certification of Chess.com's Brilliant badge.

Checks: `python -m pytest tests -q`, `node --test tests/test_popup.cjs`.
`--smoke --job=<public-fixture-id>` on the Electron entry runs only that app's
public-fixture replay/flip/close diagnostic. It expects the queen-sacrifice mate
fixture from `tests/test_explanations.py`. Screenshots and checks are stored
under `.tmp/popup-smoke/` or `CHESSLENS_SMOKE_DIR`.
