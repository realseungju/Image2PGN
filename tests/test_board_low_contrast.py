"""Low-contrast boards with bold pieces (2026-11-26: Lichess grey board + pixel set).

The plain checker correlation stayed under the proposal floor for these screens,
so a fully visible board was sent to boundary review. Tile-corner matching plus
signed grid-line snapping now recovers the board.
"""
import numpy as np
import pytest

from image2pgn.board_candidates import bounds_iou, snap_to_grid_lines
from image2pgn.board_selection import select_board


def grey_screen(seed, cell=99):
    rng = np.random.default_rng(seed)
    image = np.full((911, 1920, 3), 246, np.uint8)
    rows, cols = np.indices((cell * 8, cell * 8))
    board = np.repeat(np.where((rows // cell + cols // cell) % 2, 136, 166).astype(np.uint8)[:, :, None], 3, axis=2)
    for square in rng.choice(64, 30, replace=False):
        y, x = divmod(int(square), 8)
        fill, rim = (25, 235) if rng.random() < .5 else (240, 30)
        y0, y1, x0, x1 = y * cell + 12, y * cell + 89, x * cell + 27, x * cell + 72
        board[y0:y1, x0:x1] = rim
        board[y0 + 6:y1 - 6, x0 + 6:x1 - 6] = fill
    image[28:28 + cell * 8, 7:7 + cell * 8] = board
    return image, (7, 28, cell * 8, cell * 8)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_low_contrast_board_with_bold_pieces_needs_no_boundary_review(seed):
    image, truth = grey_screen(seed)
    bounds, details = select_board(image)
    assert bounds is not None
    assert bounds_iou(bounds, truth) >= .98
    assert not details["requires_review"] and details["boundary_action"] is None
    assert details["selection_reason"] == "corner_weighted_full_grid"


@pytest.mark.parametrize("dx,dy", [(0, -10), (9, 0), (-8, 7)])
def test_grid_line_snap_corrects_a_tenth_of_a_tile(dx, dy):
    # Tile-corner matching was observed 10 px off on a 99 px tile.
    image, truth = grey_screen(0)
    shifted = (truth[0] + dx, truth[1] + dy, truth[2], truth[3])
    assert bounds_iou(snap_to_grid_lines(image[:, :, 0], shifted), truth) >= .98


def test_blank_screen_still_has_no_board():
    bounds, details = select_board(np.full((911, 1920, 3), 246, np.uint8))
    assert bounds is None and details["boundary_action"] == "recapture"
