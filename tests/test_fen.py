from image2pgn.fen import compress_board, expand_placement, normalize_piece_placement, orient_board


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

