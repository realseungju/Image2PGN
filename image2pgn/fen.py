from __future__ import annotations

PIECES = set("prnbqkPRNBQK")
FILES = "abcdefgh"


def normalize_piece_placement(fen: str) -> str:
    placement = fen.strip().split()[0]
    ranks = placement.split("/")
    if len(ranks) != 8:
        raise ValueError("FEN piece placement must contain 8 ranks.")

    for rank in ranks:
        width = 0
        for char in rank:
            if char.isdigit():
                width += int(char)
            elif char in PIECES:
                width += 1
            else:
                raise ValueError(f"Invalid FEN character: {char!r}")
        if width != 8:
            raise ValueError(f"FEN rank {rank!r} expands to {width} files, expected 8.")

    return placement


def expand_placement(fen: str) -> list[list[str]]:
    placement = normalize_piece_placement(fen)
    board: list[list[str]] = []

    for rank in placement.split("/"):
        row: list[str] = []
        for char in rank:
            if char.isdigit():
                row.extend(["."] * int(char))
            else:
                row.append(char)
        board.append(row)

    return board


def compress_board(board: list[list[str]]) -> str:
    if len(board) != 8 or any(len(row) != 8 for row in board):
        raise ValueError("Board must be an 8x8 matrix.")

    ranks: list[str] = []
    for row in board:
        empty = 0
        rank = ""
        for piece in row:
            if piece == ".":
                empty += 1
                continue
            if empty:
                rank += str(empty)
                empty = 0
            rank += piece
        if empty:
            rank += str(empty)
        ranks.append(rank)

    return "/".join(ranks)


def orient_board(board: list[list[str]], orientation: str) -> list[list[str]]:
    if orientation == "white":
        return board
    if orientation == "black":
        return [list(reversed(row)) for row in reversed(board)]
    raise ValueError("orientation must be 'white' or 'black'.")


def score_piece_placement(placement: str) -> int:
    board = expand_placement(placement)
    score = 0
    pieces = [piece for row in board for piece in row if piece != "."]

    if pieces.count("K") == 1:
        score += 30
    else:
        score -= 80 * abs(pieces.count("K") - 1)
    if pieces.count("k") == 1:
        score += 30
    else:
        score -= 80 * abs(pieces.count("k") - 1)

    white_pieces = sum(1 for piece in pieces if piece.isupper())
    black_pieces = sum(1 for piece in pieces if piece.islower())
    score += max(0, 16 - abs(white_pieces - black_pieces))

    score -= 8 * sum(1 for piece in board[0] + board[7] if piece in "Pp")
    score -= 4 * max(0, pieces.count("P") - 8)
    score -= 4 * max(0, pieces.count("p") - 8)
    score -= 3 * max(0, pieces.count("Q") - 1)
    score -= 3 * max(0, pieces.count("q") - 1)
    score -= 2 * max(0, pieces.count("R") - 2)
    score -= 2 * max(0, pieces.count("r") - 2)
    score -= 2 * max(0, pieces.count("B") - 2)
    score -= 2 * max(0, pieces.count("b") - 2)
    score -= 2 * max(0, pieces.count("N") - 2)
    score -= 2 * max(0, pieces.count("n") - 2)

    white_back_bonus = sum(1 for piece in board[7] if piece in "RNBQK")
    black_back_bonus = sum(1 for piece in board[0] if piece in "rnbqk")
    score += white_back_bonus + black_back_bonus

    return score


def choose_orientation_by_score(white_placement: str, black_placement: str) -> tuple[str, dict[str, int]]:
    scores = {
        "white": score_piece_placement(white_placement),
        "black": score_piece_placement(black_placement),
    }
    return ("black" if scores["black"] > scores["white"] else "white"), scores
