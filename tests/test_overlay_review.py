import cv2
import numpy as np
import torch

from image2pgn import cnn
from image2pgn.fen import expand_placement
from image2pgn.board import BoardDetectionResult, colored_overlay_review, background_empty_squares, split_squares


def gray_board():
    result = np.full((640, 640, 3), 210, dtype=np.uint8)
    for r in range(8):
        for c in range(8):
            if (r+c) % 2:
                result[r*80:(r+1)*80,c*80:(c+1)*80] = 110
    return result


def test_arrow_evidence_does_not_erase_piece_or_mutate_source():
    board = gray_board()
    cv2.arrowedLine(board, (90, 280), (550, 280), (30, 120, 255), 14)
    cv2.circle(board, (360, 280), 16, (10, 10, 10), -1)
    original = board.copy()
    cleaned, coverage = colored_overlay_review(board)
    assert np.array_equal(board, original)
    assert coverage[3][2] > 0 and coverage[3][4] > 0
    empty = background_empty_squares(split_squares(cleaned))
    assert empty[3][2]
    assert not empty[3][4]
    assert not any(coverage[0])


def test_no_marks_and_isolated_color_piece_are_not_preprocessed():
    board = gray_board()
    assert colored_overlay_review(board)[0] is board
    cv2.circle(board, (280, 280), 20, (30, 120, 255), -1)
    cleaned, coverage = colored_overlay_review(board)
    assert cleaned is board and not any(map(any, coverage))


def test_colored_board_theme_is_excluded_even_with_arrow():
    board = gray_board()
    for r in range(8):
        for c in range(8):
            if (r+c) % 2:
                board[r*80:(r+1)*80,c*80:(c+1)*80] = (70, 140, 60)
    cv2.arrowedLine(board, (90, 280), (550, 280), (30, 120, 255), 14)
    cleaned, coverage = colored_overlay_review(board)
    assert cleaned is board and not any(map(any, coverage))


def test_high_confidence_arrow_prediction_is_removed_but_still_reviewed(monkeypatch, tmp_path):
    board = gray_board()
    cv2.arrowedLine(board, (90, 280), (550, 280), (30, 120, 255), 14)
    cv2.circle(board, (360, 280), 16, (10, 10, 10), -1)

    class ConfidentModel(torch.nn.Module):
        def forward(self, tensor):
            # Deliberately overconfident model: mark or actual piece -> rook.
            occupied = tensor.max() - tensor.min() > .3
            return torch.tensor([[0., 20.]] if occupied else [[20., 0.]])

    monkeypatch.setattr(torch, 'load', lambda *a, **k: dict(class_names=['empty', 'white_rook'], model_state={}))
    monkeypatch.setattr(cnn, 'PieceCnn', lambda **k: ConfidentModel())
    monkeypatch.setattr(cnn, 'load_image', lambda *a: board)
    monkeypatch.setattr(cnn, 'warp_board_result', lambda *a, **k: BoardDetectionResult(board, dict(requires_review=False)))
    result = cnn.recognize_fen_cnn_result(tmp_path/'x.png', tmp_path/'model.pt', device='cpu', threshold=.5, low_confidence_policy='review', retain_board_image=True)
    cells = expand_placement(result.placement)
    assert cells[3][2] == '.' and cells[3][4] == 'R'
    hint = next(h for h in result.review_squares if (h['screen_row'], h['screen_col']) == (3, 2))
    assert hint['score'] > .99 and hint['auto_corrected'] and hint['reason'] == 'colored_overlay'
    assert result.board_image is board
