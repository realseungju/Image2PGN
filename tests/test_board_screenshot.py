import cv2
import numpy as np
import pytest

from image2pgn.board import background_empty_squares, find_screenshot_board, split_squares, warp_board


def draw_board(cell=50, texture=False):
    board = np.zeros((cell * 8, cell * 8, 3), dtype=np.uint8)
    rng = np.random.default_rng(27)
    for r in range(8):
        for c in range(8):
            color = 205 if (r + c) % 2 == 0 else 110
            square = np.full((cell, cell, 3), color, dtype=np.float32)
            if texture:
                square += rng.normal(0, 4, (cell, cell, 1))
            board[r*cell:(r+1)*cell, c*cell:(c+1)*cell] = np.clip(square, 0, 255)
    return board


@pytest.mark.parametrize("offset", [(20, 90), (70, 440)])
def test_find_grid_above_or_below_large_ui_panel(offset):
    image = np.full((960, 500, 3), 25, dtype=np.uint8)
    # Big high-contrast rectangle should not win simply because it is larger.
    cv2.rectangle(image, (5, 5), (490, 55), (240, 240, 240), -1)
    x, y = offset
    image[y:y+400, x:x+400] = draw_board()
    found = find_screenshot_board(image)
    assert found is not None
    assert max(abs(a-b) for a,b in zip(found, (x,y,400,400))) <= 5


def test_non_board_has_no_grid_candidate():
    image = np.full((600, 400, 3), 100, dtype=np.uint8)
    cv2.rectangle(image, (20, 150), (380, 500), (220,220,220), -1)
    assert find_screenshot_board(image) is None
    assert warp_board(image, detector="grid").shape == (640,640,3)


def test_empty_filter_preserves_small_light_and_dark_pieces():
    board = draw_board(80, texture=True)
    cv2.circle(board, (40, 40), 10, (15,15,15), -1)
    cv2.circle(board, (120, 40), 10, (245,245,245), -1)
    squares = split_squares(board)
    mask = background_empty_squares(squares)
    assert not mask[0][0]
    assert not mask[0][1]
    assert sum(sum(row) for row in mask) == 62


def test_highlighted_empty_square_is_still_empty():
    board = draw_board(80)
    board[160:240,160:240] = (40,190,200)
    assert background_empty_squares(split_squares(board))[2][2]


def test_cli_exposes_independent_comparison_switches():
    from image2pgn.cli import build_parser
    for command in ("fen-cnn", "analyze-image"):
        args = build_parser().parse_args([command,"--image","board.png","--model","model.pt","--board-detector","grid","--background-filter"])
        assert args.board_detector == "grid"
        assert args.background_filter
        defaults = build_parser().parse_args([command,"--image","board.png","--model","model.pt"])
        assert defaults.board_detector == "legacy"
        assert not defaults.background_filter
