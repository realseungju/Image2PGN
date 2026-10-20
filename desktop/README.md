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


## Famous and high-rated games

After a confirmed position reaches `ready`, the result page searches the bundled
historical catalog immediately, then the Lichess Masters database. The catalog
currently contains 12 selected games (744 plies), with sources and source-file
SHA-256 fingerprints in `image2pgn/data/famous_games.json`. See
`image2pgn/data/README.md` for the full list and historical-score caveats. No
historical Elo is fabricated.
Online results require **both** recorded player ratings to be at least 2400;
ordinary Lichess player games are never queried.

`GET /api/explanations/{job_id}/master-games` returns catalog matches. Add
`?remote=true` for the Masters lookup under the same session-token boundary.
Matches require piece placement, side to move, castling rights and legal en
passant rights; move counters are ignored. Every candidate PGN is legally
replayed before it is displayed. A matching position identifies candidate games,
not proof that the screenshot came from one particular game.

Use **이 장면부터** or **처음부터** to replay the recorded moves, and
**엔진 분석으로 돌아가기** to restore the engine branch. Recorded game playback
hides the engine evaluation. Its final result comes from the PGN; an engine
continuation after resignation is not presented as a played move.

Outbound requests use only `https://explorer.lichess.org/masters`, one at a time,
with 5-second network-operation timeouts, a 128 KiB response cap, at most three
PGN downloads from 15 candidate references, and a 32-entry five-minute cache.
HTTP 429 enforces a shared 60-second pause. Images are never sent to this service.
Opening Explorer now requires Lichess authentication. Open **마스터 DB 연결** on
`/explain`, create a personal token with no permission scopes selected, paste it
into the local password field, then click **연결**. The server verifies a real
Masters response before applying the token and clearing stale failure caches.
Do not send the token through chat. The UI clears the field before submission.

By default the token lives only in service memory. If the user checks
**이 Windows 계정에 암호화해 저장**, Windows-user DPAPI encrypts it into the
Git-ignored `.tmp/lichess-token.dpapi`. It is not written in plaintext or kept in
browser storage. `CHESSLENS_LICHESS_TOKEN` remains supported for existing server
setups. **연결 해제** removes the local ciphertext and running connection; it does
not revoke the token on Lichess. Environment variables remain in the launcher's
environment and may configure the token again after a restart.

`GET /api/explanations/master-connection` returns configured/verified/source flags
without the token. POST JSON with `action=connect`, `token`, and optional
`remember=true` verifies and applies credentials. `action=test` rechecks the
existing connection; `action=disconnect` clears the local connection. All routes
require the existing ChessLens session token and loopback/Origin checks. Request
validation uses fixed errors that never echo token input. HTTP 429 cooldown is
preserved across reconnect/disconnect.

The original unauthenticated HTTP 401 was reproduced and is explained by the
current official API security definition and lichess-org/mobile issue #3161.
Authenticated live validation on 2026-10-20 returned three Carlsen/Caruana
master games after 1.e4 (both ratings 2835 or higher), with complete legal replay
of 72/128/132 plies, plus a matching Kasparov–Topalov middlegame query. The latter
was deduplicated against the catalog. The browser replay reached the recorded
draw and hid engine scores. No fallback to ordinary player games is made.

The Masters year type starts at 1952. The original `since=0` parameter produced
HTTP 400 after authentication; it was removed in favor of the valid default
range. Earlier historical games are covered by the selected offline catalog.

Checks: `python -m pytest tests -q` and
`node --test tests/test_history_replay.cjs tests/test_external_source.cjs tests/test_explain_copy.cjs tests/test_popup.cjs`.

## Actual move versus engine recommendation

In historical playback, select a move and click **이 수와 엔진 추천 비교**.
The overview shows the recorded move in orange and Stockfish's recommendation
in teal on the same starting board. Identical moves use one arrow. Both scores
use White's perspective; the difference is explained from the mover's side.
Mate scores and contradictory short searches are not converted into pawn loss.
A different recommendation alone is not labelled a mistake.

**실제 경기 이어보기** plays the original record. **엔진 추천 이어보기** plays
a hypothetical engine continuation (up to 12 plies). Close comparison to restore
the selected historical position, or return to the original engine analysis.
Previously compared moves receive same/different markers in the move list.

Authenticated POST `/api/explanations/{job_id}/compare-move` takes only `game_id`
and zero-based `ply`. The server resolves that game against the job's confirmed
position and trusted catalog or position-associated remote cache. Refresh the
list if a remote game has left the cache. The shared single worker serializes
engine work: Threads 1, Hash 64 MiB, 700 ms per search, at most two searches.
One comparison is admitted at a time, including after a request timeout until
the worker finishes. Results use a 64-entry cache. Cancelled sessions cannot
publish results; browser step/game/session changes discard late responses.

Additional checks: `python -m pytest tests/test_move_comparison.py -q` and
`node --test tests/test_history_comparison.cjs`.
