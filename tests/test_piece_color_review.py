import cv2
import numpy as np
import torch

from image2pgn import cnn
from image2pgn.board import BoardDetectionResult
from image2pgn.fen import expand_placement


def square(background, body, badge=False):
    image = np.full((80, 80, 3), background, dtype=np.uint8)
    cv2.rectangle(image, (23, 19), (57, 66), (30, 30, 30), -1)
    cv2.rectangle(image, (26, 22), (54, 63), (body, body, body), -1)
    if badge:
        cv2.circle(image, (73, 9), 8, (255, 255, 255), -1)
    return image


def test_white_body_is_not_its_black_outline():
    evidence = cnn.piece_color_evidence(square(218, 249))
    assert evidence['color'] == 'white'
    assert evidence['body_brightness'] > 240


def test_black_body_on_green_highlight_ignores_corner_badge():
    image = square((100, 160, 140), 87, badge=True)
    assert cnn.infer_piece_color_from_square(image) == 'black'
    assert cnn.class_name_with_inferred_color(image, 'white_rook') == 'black_rook'


def test_relative_brightness_alone_cannot_turn_black_on_dark_tile_white():
    image = square(30, 90)
    assert cnn.infer_piece_color_from_square(image) is None
    assert cnn.class_name_with_inferred_color(image, 'black_pawn') == 'black_pawn'


def test_empty_and_saturated_bodies_abstain():
    image = np.full((80, 80, 3), 218, dtype=np.uint8)
    assert cnn.infer_piece_color_from_square(image) is None
    assert cnn.class_name_with_inferred_color(image, 'empty') == 'empty'
    cv2.rectangle(image, (23, 19), (57, 66), (0, 0, 255), -1)
    assert cnn.infer_piece_color_from_square(image) is None
    assert cnn.class_name_with_inferred_color(image, 'white_queen') == 'white_queen'


def test_confident_wrong_color_is_reviewed_without_changing_kind_or_occupancy(monkeypatch, tmp_path):
    board = np.full((640, 640, 3), 218, dtype=np.uint8)
    board[0:80, 0:80] = square(218, 87)

    class Model(torch.nn.Module):
        def forward(self, tensor):
            occupied = tensor.max() - tensor.min() > .3
            return torch.tensor([[0., 20.]] if occupied else [[20., 0.]])

    monkeypatch.setattr(torch, 'load', lambda *a, **k: dict(class_names=['empty', 'white_rook'], model_state={}))
    monkeypatch.setattr(cnn, 'PieceCnn', lambda **k: Model())
    monkeypatch.setattr(cnn, 'load_image', lambda *a: board)
    monkeypatch.setattr(cnn, 'warp_board_result', lambda *a, **k: BoardDetectionResult(board, dict(requires_review=False)))
    result = cnn.recognize_fen_cnn_result(tmp_path/'x.png', tmp_path/'model.pt', device='cpu', threshold=.5, low_confidence_policy='review', infer_color_from_image=True, retain_board_image=True)
    cells = expand_placement(result.placement)
    assert cells[0][0] == 'r'
    assert sum(p != '.' for row in cells for p in row) == 1
    hint, = result.review_squares
    assert hint['score'] > .99
    assert hint['class_name'] == 'white_rook'
    assert hint['proposed_class_name'] == 'black_rook'
    assert hint['reason'] == 'color_contrast' and hint['color_corrected']
    assert result.board_image is board
