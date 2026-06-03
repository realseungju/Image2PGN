from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .board import load_image, save_debug_board, split_squares, warp_board
from .fen import compress_board, expand_placement, orient_board
from .templates import best_template_match, load_templates, save_piece_template


def learn_templates(
    image_path: Path,
    fen: str,
    template_dir: Path,
    orientation: str = "white",
    debug_dir: Path | None = None,
) -> int:
    image = load_image(image_path)
    board_image = warp_board(image)
    squares = split_squares(board_image)
    fen_board = orient_board(expand_placement(fen), orientation)

    if debug_dir is not None:
        save_debug_board(debug_dir, board_image, squares)

    counts: dict[str, int] = defaultdict(int)
    saved = 0
    for r, row in enumerate(fen_board):
        for c, piece in enumerate(row):
            if piece == ".":
                continue
            counts[piece] += 1
            save_piece_template(template_dir, piece, squares[r][c], counts[piece])
            saved += 1
    return saved


def recognize_fen(
    image_path: Path,
    template_dir: Path,
    orientation: str = "white",
    threshold: float = 0.58,
    debug_dir: Path | None = None,
) -> str:
    image = load_image(image_path)
    board_image = warp_board(image)
    squares = split_squares(board_image)
    templates = load_templates(template_dir)

    if debug_dir is not None:
        save_debug_board(debug_dir, board_image, squares)

    board: list[list[str]] = []
    for row in squares:
        fen_row: list[str] = []
        for square in row:
            match = best_template_match(square, templates)
            fen_row.append(match.piece if match.score >= threshold else ".")
        board.append(fen_row)

    board = orient_board(board, orientation)
    return compress_board(board)

