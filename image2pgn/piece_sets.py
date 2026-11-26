"""Recognize boards drawn with a known piece set by comparing them with per-set references.

The bundled CNN struggles with some screen piece designs. When a board clearly matches
one of the reference piece sets, each occupied square is compared with that set's
reference descriptors instead. Otherwise the caller keeps the CNN reading.

The method and cutoffs come from the 2026-11-25 offline audit: references were built
from 435 Lichess screenshots (86 games), and the cutoffs are the first percentiles of
correctly identified development scenes on board themes held out from the references.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .board import split_squares


ASSET_DIR = Path(__file__).parent / "assets" / "piece_sets"
REFERENCE_PATH = ASSET_DIR / "references.npz"
CONFIG_PATH = ASSET_DIR / "references.json"


def _hog():
    return cv2.HOGDescriptor((32, 32), (16, 16), (8, 8), (8, 8), 9)


def _normalize(vector: np.ndarray) -> np.ndarray:
    return vector / max(float(np.linalg.norm(vector)), 1e-8)


def square_descriptor(tile: np.ndarray, hog=None) -> tuple[np.ndarray, float]:
    """Return a shape/shading descriptor and an occupancy strength for one BGR square."""
    hog = hog or _hog()
    pixels = cv2.resize(tile, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    corners = np.concatenate([pixels[y:y + 4, x:x + 4].reshape(-1, 3) for y in (2, 26) for x in (2, 26)])
    background = np.median(corners, axis=0)
    difference = pixels - background
    strength = np.max(np.abs(difference), axis=2)
    occupancy = float(np.percentile(strength[5:27, 5:27], 85))
    gray = cv2.cvtColor(pixels.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    brightness = cv2.cvtColor(difference, cv2.COLOR_BGR2GRAY)
    for array in (gray, strength, brightness):
        border = int(np.rint(background @ [.114, .587, .299])) if array is gray else 0
        array[:2] = border
        array[-2:] = border
        array[:, :2] = border
        array[:, -2:] = border
    gradient = _normalize(hog.compute(gray).ravel())
    shape = _normalize(cv2.resize(strength, (16, 16), interpolation=cv2.INTER_AREA).ravel())
    shading = _normalize(cv2.resize(brightness, (16, 16), interpolation=cv2.INTER_AREA).ravel())
    descriptor = _normalize(np.concatenate((gradient, .85 * shape, .90 * shading))).astype(np.float32)
    return descriptor, occupancy


def board_descriptors(board_image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Descriptors and occupancy strengths for the 64 squares in screen order."""
    hog = _hog()
    pairs = [square_descriptor(tile, hog) for row in split_squares(board_image) for tile in row]
    return np.stack([pair[0] for pair in pairs]), np.asarray([pair[1] for pair in pairs])


@dataclass(frozen=True)
class References:
    vectors: np.ndarray
    sets: tuple[str, ...]
    pieces: tuple[str, ...]
    occupancy_threshold: float
    similarity_cutoff: float
    margin_cutoff: float


@lru_cache(maxsize=4)
def load_references(reference_path: Path = REFERENCE_PATH, config_path: Path = CONFIG_PATH) -> References:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    with np.load(reference_path, allow_pickle=False) as data:
        vectors = data["vectors"].astype(np.float32)
        sets = tuple(str(value) for value in data["sets"])
        pieces = tuple(str(value) for value in data["pieces"])
        threshold = float(data["occupancy_threshold"])
    if not (len(vectors) == len(sets) == len(pieces)):
        raise ValueError("Piece-set reference arrays have different lengths.")
    return References(vectors, sets, pieces, threshold,
                      float(config["cutoffs"]["similarity"]), float(config["cutoffs"]["margin"]))


@dataclass(frozen=True)
class PieceSetReading:
    """Best piece-set candidate for one board, with labels in screen order ('.' = empty)."""
    piece_set: str
    runner_up: str | None
    similarity: float
    margin: float
    accepted: bool
    cells: tuple[str, ...]
    occupied: int

    def summary(self) -> dict:
        return {"piece_set": self.piece_set, "runner_up": self.runner_up,
                "similarity": round(self.similarity, 4), "margin": round(self.margin, 4),
                "accepted": self.accepted, "occupied": self.occupied}


def read_board(board_image: np.ndarray, references: References | None = None) -> PieceSetReading:
    references = references or load_references()
    inputs, occupancy = board_descriptors(board_image)
    occupied = occupancy >= references.occupancy_threshold
    similarities = inputs @ references.vectors.T
    ranked = []
    sets = np.asarray(references.sets)
    for name in sorted(set(references.sets)):
        indices = np.flatnonzero(sets == name)
        best = indices[similarities[:, indices].argmax(axis=1)]
        scores = similarities[np.arange(64), best][occupied]
        # The mean of the twelve best occupied squares scores how well the set fits.
        score = float(np.sort(scores)[-12:].mean()) if scores.size else 0.0
        cells = tuple(references.pieces[index] if occupied[i] else "." for i, index in enumerate(best))
        ranked.append((score, name, cells))
    ranked.sort(key=lambda item: item[0], reverse=True)
    score, name, cells = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = score - (runner_up[0] if runner_up else 0.0)
    accepted = score >= references.similarity_cutoff and margin >= references.margin_cutoff
    return PieceSetReading(name, runner_up[1] if runner_up else None, score, margin, accepted,
                           cells, int(occupied.sum()))
