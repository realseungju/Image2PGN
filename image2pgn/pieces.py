from __future__ import annotations

PIECE_TO_CLASS = {
    ".": "empty",
    "P": "white_pawn",
    "N": "white_knight",
    "B": "white_bishop",
    "R": "white_rook",
    "Q": "white_queen",
    "K": "white_king",
    "p": "black_pawn",
    "n": "black_knight",
    "b": "black_bishop",
    "r": "black_rook",
    "q": "black_queen",
    "k": "black_king",
}

CLASS_TO_PIECE = {value: key for key, value in PIECE_TO_CLASS.items()}

CLASS_NAMES = [
    "empty",
    "white_pawn",
    "white_knight",
    "white_bishop",
    "white_rook",
    "white_queen",
    "white_king",
    "black_pawn",
    "black_knight",
    "black_bishop",
    "black_rook",
    "black_queen",
    "black_king",
]


def class_name_for_piece(piece: str) -> str:
    try:
        return PIECE_TO_CLASS[piece]
    except KeyError as exc:
        raise ValueError(f"Invalid piece character: {piece!r}") from exc


def piece_for_class_name(class_name: str) -> str:
    try:
        return CLASS_TO_PIECE[class_name]
    except KeyError as exc:
        raise ValueError(f"Invalid class name: {class_name!r}") from exc

