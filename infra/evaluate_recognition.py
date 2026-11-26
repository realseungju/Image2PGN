"""Compare CNN-only and piece-set routed recognition on labelled screenshots.

Usage:
    uv run python infra/evaluate_recognition.py manifest.jsonl [more.jsonl ...] --out results.json

Each JSONL row needs ``file`` (relative to its manifest) and ``piece_placement`` (FEN board
field in standard white-at-bottom orientation). Optional ``subset`` groups the summary.
The score is whether all 64 squares match after automatic orientation, using the same
recognition settings as the web app.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import chess

from image2pgn.cnn import recognize_fen_cnn_result

MODEL = Path(__file__).resolve().parents[1] / "image2pgn" / "assets" / "piece_classifier.pt"


def squares(placement: str) -> list[str]:
    board = chess.BaseBoard(placement)
    return [piece.symbol() if (piece := board.piece_at(square)) else "." for square in chess.SQUARES]


def recognize(path: Path, routing: bool):
    return recognize_fen_cnn_result(
        image_path=path, model_path=MODEL, orientation="auto", device="cpu", threshold=0.5,
        board_detector="grid-v2", suppress_empty_background=False, low_confidence_policy="review",
        infer_color_from_image=True, piece_set_routing=routing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for manifest in args.manifests:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_path"] = manifest.parent / row["file"]
                rows.append(row)
    results = []
    started = time.time()
    for number, row in enumerate(rows, 1):
        truth = squares(row["piece_placement"])
        entry = {"file": row["file"], "subset": row.get("subset", "all")}
        for name, routing in (("cnn", False), ("routed", True)):
            result = recognize(row["_path"], routing)
            predicted = squares(result.placement)
            wrong = [chess.square_name(i) for i, (a, b) in enumerate(zip(predicted, truth)) if a != b]
            entry[name] = {"exact": not wrong, "wrong_squares": wrong, "placement": result.placement,
                           "review_squares": [f"{r['screen_row']}:{r['screen_col']}" for r in result.review_squares],
                           "wrong_flagged": None}
            if routing:
                entry["piece_set"] = result.piece_set
            # How many wrong squares were highlighted for review (screen coordinates differ by orientation).
            flagged = set()
            for review in result.review_squares:
                index = review["screen_row"] * 8 + review["screen_col"]
                rank, file = divmod(index, 8)
                square = chess.square(file, 7 - rank) if result.orientation == "white" else chess.square(7 - file, rank)
                flagged.add(chess.square_name(square))
            entry[name]["wrong_flagged"] = sum(square in flagged for square in wrong)
        results.append(entry)
        print(f"{number}/{len(rows)} {row['file']} cnn={entry['cnn']['exact']} routed={entry['routed']['exact']} "
              f"({(entry.get('piece_set') or {}).get('strategy')})", flush=True)

    summary = defaultdict(lambda: defaultdict(int))
    for entry in results:
        for key in (entry["subset"], "total"):
            bucket = summary[key]
            bucket["images"] += 1
            bucket["cnn_exact"] += entry["cnn"]["exact"]
            bucket["routed_exact"] += entry["routed"]["exact"]
            bucket["routed_to_piece_set"] += (entry.get("piece_set") or {}).get("strategy") == "piece_set"
            for name in ("cnn", "routed"):
                bucket[f"{name}_wrong_squares"] += len(entry[name]["wrong_squares"])
                bucket[f"{name}_wrong_flagged"] += entry[name]["wrong_flagged"]
    report = {"metric": "64-square match after automatic orientation; web app recognition settings",
              "seconds": round(time.time() - started, 1),
              "summary": {key: dict(value) for key, value in summary.items()}, "rows": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
