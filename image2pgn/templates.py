from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


TEMPLATE_SIZE = 64
PIECE_CHARS = "prnbqkPRNBQK"


@dataclass(frozen=True)
class Match:
    piece: str
    score: float


def square_to_template(square: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(square, cv2.COLOR_BGR2GRAY)
    gray = _crop_center(gray, margin_ratio=0.08)
    normalized = cv2.resize(gray, (TEMPLATE_SIZE, TEMPLATE_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(normalized)


def save_piece_template(template_dir: Path, piece: str, square: np.ndarray, index: int) -> Path:
    if piece not in PIECE_CHARS:
        raise ValueError(f"Invalid piece: {piece!r}")
    piece_dir = template_dir / _piece_dir_name(piece)
    piece_dir.mkdir(parents=True, exist_ok=True)
    path = piece_dir / f"{index:03d}.png"
    cv2.imwrite(str(path), square_to_template(square))
    return path


def load_templates(template_dir: Path) -> dict[str, list[np.ndarray]]:
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory does not exist: {template_dir}")

    templates: dict[str, list[np.ndarray]] = {}
    for piece in PIECE_CHARS:
        piece_dir = template_dir / _piece_dir_name(piece)
        if not piece_dir.exists():
            continue
        images: list[np.ndarray] = []
        for path in sorted(piece_dir.glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is not None:
                images.append(cv2.resize(image, (TEMPLATE_SIZE, TEMPLATE_SIZE)))
        if images:
            templates[piece] = images

    if not templates:
        raise ValueError(f"No templates found in {template_dir}")
    return templates


def best_template_match(square: np.ndarray, templates: dict[str, list[np.ndarray]]) -> Match:
    candidate = square_to_template(square)
    best = Match(piece=".", score=-1.0)

    for piece, piece_templates in templates.items():
        for template in piece_templates:
            score = _correlation(candidate, template)
            if score > best.score:
                best = Match(piece=piece, score=score)

    return best


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a32 = a.astype(np.float32)
    b32 = b.astype(np.float32)
    a32 -= float(a32.mean())
    b32 -= float(b32.mean())
    denom = float(np.linalg.norm(a32) * np.linalg.norm(b32))
    if denom == 0:
        return 0.0
    return float(np.sum(a32 * b32) / denom)


def _crop_center(image: np.ndarray, margin_ratio: float) -> np.ndarray:
    h, w = image.shape[:2]
    y = int(h * margin_ratio)
    x = int(w * margin_ratio)
    return image[y : h - y, x : w - x]


def _piece_dir_name(piece: str) -> str:
    color = "white" if piece.isupper() else "black"
    return f"{color}_{piece.lower()}"

