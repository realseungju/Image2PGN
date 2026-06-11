from __future__ import annotations

from pathlib import Path
import textwrap

import cv2
import numpy as np

from .analyze import PositionAnalysis
from .board import load_image, warp_board


ARROW_COLORS = [
    (37, 180, 75),
    (0, 165, 255),
    (60, 90, 230),
]


def save_analysis_overlay(
    image_path: Path,
    analysis: PositionAnalysis,
    orientation: str,
    output_path: Path,
) -> None:
    board = warp_board(load_image(image_path))
    board = _draw_candidate_moves(board, analysis, orientation)
    board = _draw_grid(board)
    panel = _render_panel(analysis, board.shape[0])
    canvas = np.concatenate([board, panel], axis=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)


def _draw_candidate_moves(board: np.ndarray, analysis: PositionAnalysis, orientation: str) -> np.ndarray:
    output = board.copy()
    square_size = board.shape[0] / 8
    for index, move in enumerate(analysis.moves[:3]):
        color = ARROW_COLORS[index % len(ARROW_COLORS)]
        from_square = move.move_uci[:2]
        to_square = move.move_uci[2:4]
        start = _square_center(from_square, orientation, square_size)
        end = _square_center(to_square, orientation, square_size)
        thickness = 7 if index == 0 else 5
        cv2.arrowedLine(output, start, end, color, thickness, cv2.LINE_AA, tipLength=0.22)
        _draw_square_outline(output, to_square, orientation, square_size, color, thickness=3)
        cv2.circle(output, start, 9, color, -1, cv2.LINE_AA)
    return output


def _draw_grid(board: np.ndarray) -> np.ndarray:
    output = board.copy()
    size = board.shape[0]
    step = size // 8
    for i in range(9):
        color = (35, 35, 35)
        cv2.line(output, (0, i * step), (size, i * step), color, 1, cv2.LINE_AA)
        cv2.line(output, (i * step, 0), (i * step, size), color, 1, cv2.LINE_AA)
    return output


def _draw_square_outline(
    image: np.ndarray,
    square: str,
    orientation: str,
    square_size: float,
    color: tuple[int, int, int],
    thickness: int,
) -> None:
    center = _square_center(square, orientation, square_size)
    half = int(square_size // 2)
    top_left = (center[0] - half + 3, center[1] - half + 3)
    bottom_right = (center[0] + half - 3, center[1] + half - 3)
    cv2.rectangle(image, top_left, bottom_right, color, thickness, cv2.LINE_AA)


def _square_center(square: str, orientation: str, square_size: float) -> tuple[int, int]:
    file_index = ord(square[0]) - ord("a")
    rank = int(square[1])
    if orientation == "black":
        row = rank - 1
        col = 7 - file_index
    else:
        row = 8 - rank
        col = file_index
    return (
        int((col + 0.5) * square_size),
        int((row + 0.5) * square_size),
    )


def _render_panel(analysis: PositionAnalysis, height: int) -> np.ndarray:
    width = 560
    panel = np.full((height, width, 3), (248, 248, 246), dtype=np.uint8)
    y = 30
    y = _put_text(panel, "ChessLens Analysis", 24, y, scale=0.82, thickness=2)
    y = _put_text(panel, f"Side: {analysis.side_to_move}", 24, y + 10)
    y = _put_text(panel, f"Eval: {analysis.evaluation}", 24, y)
    y = _put_wrapped(panel, analysis.summary, 24, y + 12, width_chars=58)

    if analysis.threats:
        y = _put_text(panel, "Threats", 24, y + 14, scale=0.62, thickness=2)
        for threat in analysis.threats[:4]:
            y = _put_wrapped(panel, f"- {threat}", 24, y, width_chars=64, scale=0.44)

    if analysis.moves:
        y = _put_text(panel, "Candidate Moves", 24, y + 14, scale=0.62, thickness=2)
        for move in analysis.moves[:3]:
            line = f"{move.rank}. {move.san}  {move.score}  {move.delta}"
            y = _put_text(panel, line, 24, y, scale=0.48, thickness=1)
            pv = " ".join(move.pv_san[:5])
            y = _put_wrapped(panel, f"PV: {pv}", 40, y, width_chars=58, scale=0.42)
            ideas = ", ".join(move.themes) if move.themes else "general improvement"
            y = _put_wrapped(panel, f"Ideas: {ideas}", 40, y, width_chars=58, scale=0.42)

    return panel


def _put_wrapped(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    width_chars: int,
    scale: float = 0.46,
    thickness: int = 1,
) -> int:
    for line in textwrap.wrap(text, width=width_chars):
        y = _put_text(image, line, x, y, scale=scale, thickness=thickness)
    return y


def _put_text(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    scale: float = 0.48,
    thickness: int = 1,
) -> int:
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (30, 30, 30), thickness, cv2.LINE_AA)
    return y + int(28 * scale) + 8

