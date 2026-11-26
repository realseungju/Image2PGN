"""Rebuild the bundled piece-set references from a labelled screenshot manifest.

The screenshots are local evaluation material and are not distributed. This script
documents exactly how ``image2pgn/assets/piece_sets/references.npz`` was produced:

    uv run python infra/build_piece_set_references.py \
        --manifest path/to/chesslens-screenshots-2026-11-25/manifest.jsonl \
        --group evaluation --exclude alpha

Each manifest row needs ``file``, ``group``, ``piece_set``, ``theme``, ``orientation``,
``piece_placement`` and ``board_box_px`` ([x, y, width, height]).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import chess
import cv2
import numpy as np

from image2pgn.board import load_image, split_squares
from image2pgn.piece_sets import _hog, _normalize, square_descriptor

# Cutoffs from the 2026-11-25 hybrid-routing calibration (first percentiles of correctly
# identified development scenes on board themes held out from the references).
CUTOFFS = {"similarity": 0.6892, "margin": 0.0237}


def screen_labels(placement: str, orientation: str) -> list[str]:
    board = chess.BaseBoard(placement)
    cells = [piece.symbol() if (piece := board.piece_at(square)) else "." for square in chess.SQUARES_180]
    return cells[::-1] if orientation == "black" else cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--group", default="evaluation")
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--out", type=Path, default=Path("image2pgn/assets/piece_sets"))
    args = parser.parse_args()
    cv2.setNumThreads(1)

    rows = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("group") == args.group and row.get("piece_set") not in set(args.exclude)]
    if not rows:
        raise SystemExit("No manifest rows selected.")
    hog = _hog()
    samples = defaultdict(list)
    strengths = {False: [], True: []}
    for row in rows:
        image = load_image(args.manifest.parent / row["file"])
        x, y, width, height = row["board_box_px"]
        crop = cv2.resize(image[y:y + height, x:x + width], (640, 640), interpolation=cv2.INTER_AREA)
        tiles = [tile for line in split_squares(crop) for tile in line]
        for index, (piece, tile) in enumerate(zip(screen_labels(row["piece_placement"], row["orientation"]), tiles, strict=True)):
            vector, occupancy = square_descriptor(tile, hog)
            strengths[piece != "."].append(occupancy)
            if piece != ".":
                parity = (index % 8 + index // 8) % 2
                samples[row["piece_set"], piece, row["theme"], parity].append(vector)

    empty_top = float(np.quantile(strengths[False], .995))
    occupied_bottom = float(np.quantile(strengths[True], .005))
    groups = sorted(samples)
    vectors = np.stack([_normalize(np.mean(samples[group], axis=0)) for group in groups]).astype(np.float32)
    args.out.mkdir(parents=True, exist_ok=True)
    reference_path = args.out / "references.npz"
    np.savez_compressed(
        reference_path, vectors=vectors,
        sets=np.asarray([group[0] for group in groups]), pieces=np.asarray([group[1] for group in groups]),
        themes=np.asarray([group[2] for group in groups]), parity=np.asarray([group[3] for group in groups], dtype=np.int8),
        occupancy_threshold=np.float64((empty_top + occupied_bottom) / 2),
    )
    config = {
        "description": "Per piece-set square descriptors for ChessLens piece-set routing.",
        "cutoffs": CUTOFFS,
        "reference_images": len(rows),
        "reference_games": len({row["game_id"] for row in rows}),
        "piece_sets": sorted({group[0] for group in groups}),
        "board_themes": sorted({group[2] for group in groups}),
        "excluded_piece_sets": sorted(args.exclude),
        "occupancy_quantiles": {"empty_q995": empty_top, "occupied_q005": occupied_bottom},
        "references_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
    }
    (args.out / "references.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(groups)} references from {len(rows)} images -> {reference_path}")


if __name__ == "__main__":
    main()
