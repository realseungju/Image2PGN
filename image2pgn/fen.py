from __future__ import annotations

PIECES = set("prnbqkPRNBQK")


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

