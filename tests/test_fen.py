from image2pgn.fen import (
    choose_orientation_by_score,
    compress_board,
    expand_placement,
    normalize_piece_placement,
    orient_board,
    score_piece_placement,
)


def test_expand_and_compress_piece_placement():
    fen = "rn1qkbnr/pppbpppp/8/3p4/8/2N5/PPPPPPPP/R1BQKBNR"
    board = expand_placement(fen)

    assert board[0] == ["r", "n", ".", "q", "k", "b", "n", "r"]
    assert compress_board(board) == fen


def test_normalize_accepts_full_fen():
    assert normalize_piece_placement("8/8/8/8/8/8/8/8 w - - 0 1") == "8/8/8/8/8/8/8/8"


def test_black_orientation_rotates_board():
    board = expand_placement("k7/8/8/8/8/8/8/7K")

    assert compress_board(orient_board(board, "black")) == "K7/8/8/8/8/8/8/7k"


def test_score_piece_placement_penalizes_pawns_on_back_rank():
    normal = "8/8/8/8/8/8/PPPPPPPP/RNBQKBNR"
    bad = "PPPPPPPP/8/8/8/8/8/8/RNBQKBNR"

    assert score_piece_placement(normal) > score_piece_placement(bad)


def test_choose_orientation_by_score_prefers_more_plausible_board():
    white = "PPPPPPPP/8/8/8/8/8/8/RNBQKBNR"
    black = "rnbqkbnr/8/8/8/8/8/PPPPPPPP/RNBQKBNR"

    chosen, scores = choose_orientation_by_score(white, black)

    assert chosen == "black"
    assert scores["black"] > scores["white"]
