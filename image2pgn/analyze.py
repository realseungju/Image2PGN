from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True)
class MoveAnalysis:
    rank: int
    move_uci: str
    san: str
    score: str
    score_cp: int | None
    mate: int | None
    delta: str
    delta_cp: int | None
    pv_san: list[str]
    themes: list[str]


@dataclass(frozen=True)
class PositionAnalysis:
    fen: str
    legal: bool
    turn: str
    side_to_move: str
    evaluation: str
    evaluation_cp: int | None
    mate: int | None
    summary: str
    moves: list[MoveAnalysis]
    threats: list[str]
    warnings: list[str]


def analyze_fen(
    fen: str,
    engine_path: Path | None,
    depth: int = 14,
    top: int = 5,
    movetime_ms: int | None = None,
) -> PositionAnalysis:
    chess = _require_chess()
    resolved_engine_path = resolve_engine_path(engine_path)
    board = chess.Board(fen)
    warnings = _position_warnings(board)
    if board.is_game_over(claim_draw=True):
        return PositionAnalysis(
            fen=board.fen(),
            legal=board.is_valid(),
            turn="white" if board.turn == chess.WHITE else "black",
            side_to_move="White" if board.turn == chess.WHITE else "Black",
            evaluation="game over",
            evaluation_cp=None,
            mate=None,
            summary=_game_over_summary(board),
            moves=[],
            threats=[],
            warnings=warnings,
        )

    engine = chess.engine.SimpleEngine.popen_uci(str(resolved_engine_path))
    try:
        limit = chess.engine.Limit(depth=depth) if movetime_ms is None else chess.engine.Limit(time=movetime_ms / 1000)
        infos = engine.analyse(board, limit, multipv=max(1, top))
        if isinstance(infos, dict):
            infos = [infos]
        baseline_cp, baseline_mate = _score_values(chess, board, infos[0])
        moves = [
            _move_analysis(chess, board, info, index + 1, baseline_cp, baseline_mate)
            for index, info in enumerate(infos[:top])
        ]
        threats = _detect_threats(chess, engine, board, limit, baseline_cp)
    finally:
        engine.quit()

    return PositionAnalysis(
        fen=board.fen(),
        legal=board.is_valid(),
        turn="white" if board.turn == chess.WHITE else "black",
        side_to_move="White" if board.turn == chess.WHITE else "Black",
        evaluation=_format_score(baseline_cp, baseline_mate),
        evaluation_cp=baseline_cp,
        mate=baseline_mate,
        summary=_summary_from_moves(board, moves),
        moves=moves,
        threats=threats,
        warnings=warnings,
    )


def format_analysis(analysis: PositionAnalysis) -> str:
    lines = [
        f"FEN: {analysis.fen}",
        f"Side to move: {analysis.side_to_move}",
        f"Valid position: {'yes' if analysis.legal else 'no'}",
        f"Current evaluation: {analysis.evaluation} from {analysis.side_to_move}'s perspective",
    ]
    if analysis.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in analysis.warnings)
    lines.append(f"Summary: {analysis.summary}")
    if analysis.threats:
        lines.append("Current threats:")
        lines.extend(f"- {threat}" for threat in analysis.threats)
    if not analysis.moves:
        return "\n".join(lines)

    lines.append("Candidate moves:")
    for move in analysis.moves:
        pv = " ".join(move.pv_san[:6])
        themes = ", ".join(move.themes) if move.themes else "general improvement"
        lines.append(
            f"{move.rank}. {move.san} ({move.score}, {move.delta})"
            f"\n   line: {pv}"
            f"\n   ideas: {themes}"
        )
    return "\n".join(lines)


def resolve_engine_path(engine_path: Path | None) -> Path:
    if engine_path is not None:
        if not engine_path.exists():
            raise FileNotFoundError(f"Engine executable not found: {engine_path}")
        return engine_path

    path_from_command = shutil.which("stockfish")
    if path_from_command:
        return Path(path_from_command)

    candidates = [
        Path.home() / "Documents" / "stockfish",
        Path.cwd() / "stockfish",
    ]
    for folder in candidates:
        if folder.exists():
            matches = sorted(folder.glob("stockfish*.exe"))
            if matches:
                return matches[0]

    raise FileNotFoundError(
        "Stockfish executable was not found. Pass it explicitly with --engine."
    )


def _move_analysis(chess, board, info, rank: int, baseline_cp: int | None, baseline_mate: int | None) -> MoveAnalysis:
    pv = info.get("pv", [])
    if not pv:
        raise ValueError("Engine did not return a principal variation.")
    move = pv[0]
    score_cp, mate = _score_values(chess, board, info)
    san = board.san(move)
    pv_san = _pv_to_san(board, pv)
    themes = _move_themes(chess, board, move)
    return MoveAnalysis(
        rank=rank,
        move_uci=move.uci(),
        san=san,
        score=_format_score(score_cp, mate),
        score_cp=score_cp,
        mate=mate,
        delta=_format_delta(score_cp, mate, baseline_cp, baseline_mate),
        delta_cp=_delta_cp(score_cp, mate, baseline_cp, baseline_mate),
        pv_san=pv_san,
        themes=themes,
    )


def _score_values(chess, board, info) -> tuple[int | None, int | None]:
    score_obj = info["score"].pov(board.turn)
    mate = score_obj.mate()
    score_cp = score_obj.score(mate_score=100000)
    return score_cp, mate


def _pv_to_san(board, pv) -> list[str]:
    temp = board.copy()
    san_moves: list[str] = []
    for move in pv:
        if move not in temp.legal_moves:
            break
        san_moves.append(temp.san(move))
        temp.push(move)
    return san_moves


def _format_score(score_cp: int | None, mate: int | None) -> str:
    if mate is not None:
        return f"mate in {mate}" if mate > 0 else f"mated in {-mate}"
    if score_cp is None:
        return "n/a"
    return f"{score_cp / 100:+.2f}"


def _format_delta(score_cp: int | None, mate: int | None, baseline_cp: int | None, baseline_mate: int | None) -> str:
    if mate is not None or baseline_mate is not None:
        return _format_mate_delta(mate, baseline_mate)
    delta = _delta_cp(score_cp, mate, baseline_cp, baseline_mate)
    if delta is None:
        return "change n/a"
    if delta == 0:
        return "best-eval"
    return f"{delta / 100:+.2f} vs best"


def _delta_cp(score_cp: int | None, mate: int | None, baseline_cp: int | None, baseline_mate: int | None) -> int | None:
    if score_cp is None or baseline_cp is None:
        return None
    return score_cp - baseline_cp


def _format_mate_delta(mate: int | None, baseline_mate: int | None) -> str:
    if mate == baseline_mate:
        return "best-eval"
    if mate is None or baseline_mate is None:
        return "mate-score change"
    if mate < 0 and baseline_mate < 0:
        difference = abs(mate) - abs(baseline_mate)
        if difference < 0:
            return f"mated {-difference} ply sooner than best"
        return f"delays mate by {difference} ply"
    if mate > 0 and baseline_mate > 0:
        difference = mate - baseline_mate
        if difference < 0:
            return f"mates {-difference} ply faster than best"
        return f"mates {difference} ply slower than best"
    return "mate-score swing"


def _move_themes(chess, board, move) -> list[str]:
    themes: list[str] = []
    piece = board.piece_at(move.from_square)
    if board.is_capture(move):
        themes.append("wins or trades material")
    if board.gives_check(move):
        themes.append("forces check")
    if board.is_castling(move):
        themes.append("improves king safety")
    if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) in (0, 7):
        themes.append("develops a minor piece")
    if piece and piece.piece_type == chess.PAWN:
        if abs(chess.square_file(move.to_square) - 3.5) <= 1.5:
            themes.append("fights for the center")
        if board.piece_at(move.to_square) is None and chess.square_file(move.from_square) != chess.square_file(move.to_square):
            themes.append("opens lines with a pawn break")
    if piece and piece.piece_type in (chess.ROOK, chess.QUEEN):
        themes.append("increases heavy-piece activity")
    if _attacks_enemy_king_zone(chess, board, move):
        themes.append("adds pressure near the enemy king")
    if _creates_fork(chess, board, move):
        themes.append("creates a fork threat")
    if _creates_pin(chess, board, move):
        themes.append("creates or increases a pin")
    if _creates_mate_threat(board, move):
        themes.append("threatens checkmate next move")
    return themes


def _attacks_enemy_king_zone(chess, board, move) -> bool:
    temp = board.copy()
    temp.push(move)
    enemy_king = temp.king(not board.turn)
    if enemy_king is None:
        return False
    zone = {enemy_king, *temp.attacks(enemy_king)}
    return bool(temp.attacks(move.to_square) & zone)


def _creates_fork(chess, board, move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return False
    temp = board.copy()
    temp.push(move)
    attacker_square = move.to_square
    attacked_high_value = 0
    for target in temp.attacks(attacker_square):
        target_piece = temp.piece_at(target)
        if target_piece is None or target_piece.color == piece.color:
            continue
        if target_piece.piece_type in (chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
            attacked_high_value += 1
    return attacked_high_value >= 2


def _creates_pin(chess, board, move) -> bool:
    temp = board.copy()
    temp.push(move)
    enemy = not board.turn
    for square, piece in temp.piece_map().items():
        if piece.color == enemy and piece.piece_type != chess.KING and temp.is_pinned(enemy, square):
            return True
    return False


def _creates_mate_threat(board, move) -> bool:
    temp = board.copy()
    temp.push(move)
    if temp.is_checkmate() or temp.is_game_over(claim_draw=True):
        return False
    temp.turn = board.turn
    for reply in temp.legal_moves:
        candidate = temp.copy()
        candidate.push(reply)
        if candidate.is_checkmate():
            return True
    return False


def _detect_threats(chess, engine, board, limit, baseline_cp: int | None) -> list[str]:
    threats: list[str] = []
    threats.extend(_hanging_piece_threats(chess, board))
    threats.extend(_forcing_reply_threats(chess, board))
    threats.extend(_engine_reply_threats(chess, engine, board, limit, baseline_cp))
    return threats[:12]


def _hanging_piece_threats(chess, board) -> list[str]:
    threats: list[str] = []
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 0,
    }
    for square, piece in board.piece_map().items():
        if piece.color != board.turn or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not board.turn, square)
        defenders = board.attackers(board.turn, square)
        if attackers and not defenders and values[piece.piece_type] >= 300:
            threats.append(
                f"Hanging piece: {piece.symbol().upper()} on {chess.square_name(square)} "
                f"is attacked and undefended."
            )
    return threats


def _forcing_reply_threats(chess, board) -> list[str]:
    threats: list[str] = []
    opponent_board = board.copy()
    opponent_board.turn = not board.turn
    legal_replies = list(opponent_board.legal_moves)

    mate_moves = []
    check_moves = []
    capture_moves = []
    for move in legal_replies:
        temp = opponent_board.copy()
        san = opponent_board.san(move)
        is_capture = opponent_board.is_capture(move)
        gives_check = opponent_board.gives_check(move)
        temp.push(move)
        if temp.is_checkmate():
            mate_moves.append(san)
        elif gives_check:
            check_moves.append(san)
        if is_capture and len(capture_moves) < 8:
            victim = board.piece_at(move.to_square)
            if victim and victim.piece_type != chess.PAWN:
                capture_moves.append(san)

    if mate_moves:
        threats.append(f"Immediate mate threat: opponent can play {', '.join(mate_moves[:4])}.")
    if check_moves:
        threats.append(f"Forcing checks available to opponent: {', '.join(check_moves[:6])}.")
    if capture_moves:
        threats.append(f"Forcing captures available to opponent: {', '.join(capture_moves[:6])}.")
    return threats


def _engine_reply_threats(chess, engine, board, limit, baseline_cp: int | None) -> list[str]:
    if baseline_cp is None:
        return []
    opponent_board = board.copy()
    opponent_board.turn = not board.turn
    if opponent_board.is_game_over(claim_draw=True):
        return []

    try:
        info = engine.analyse(opponent_board, limit)
    except Exception:
        return []

    pv = info.get("pv", [])
    if not pv:
        return []
    opponent_score_obj = info["score"].pov(opponent_board.turn)
    opponent_mate = opponent_score_obj.mate()
    opponent_score = opponent_score_obj.score(mate_score=100000)
    move = pv[0]
    san = opponent_board.san(move)

    if opponent_mate is not None and opponent_mate > 0:
        return [f"Engine threat: opponent has a forcing mate starting with {san}."]
    if opponent_score is None:
        return []

    score_after_opponent = -opponent_score
    swing = score_after_opponent - baseline_cp
    if swing <= -250:
        return [
            f"Engine threat: if ignored, opponent's {san} worsens the evaluation by "
            f"{swing / 100:+.2f} from the side-to-move perspective."
        ]
    if swing <= -100:
        return [
            f"Positional threat: opponent's {san} improves their position by "
            f"{-swing / 100:.2f} if not addressed."
        ]
    return []


def _summary_from_moves(board, moves: list[MoveAnalysis]) -> str:
    if not moves:
        return "No candidate moves returned by the engine."
    best = moves[0]
    if best.mate is not None:
        if best.mate > 0:
            return f"The side to move has a forcing mate; the engine starts with {best.san}."
        return (
            f"The side to move is in severe danger. {best.san} is the best defense found, "
            f"but the engine still sees mate in {-best.mate}."
        )
    if best.score_cp is None:
        return f"The engine prefers {best.san}."
    centipawns = best.score_cp
    if centipawns >= 150:
        status = "a clear advantage"
    elif centipawns >= 50:
        status = "a small advantage"
    elif centipawns > -50:
        status = "a roughly balanced position"
    elif centipawns > -150:
        status = "some pressure against the side to move"
    else:
        status = "serious danger for the side to move"
    return f"The engine prefers {best.san}; from the side-to-move perspective this is {status}."


def _position_warnings(board) -> list[str]:
    warnings: list[str] = []
    if not board.is_valid():
        warnings.append("The FEN is not fully valid according to python-chess.")
    if board.castling_rights:
        warnings.append("Castling rights are present; verify them if the FEN came from a single screenshot.")
    if board.ep_square is not None:
        warnings.append("En-passant square is present; verify it if the FEN came from a single screenshot.")
    return warnings


def _game_over_summary(board) -> str:
    if board.is_checkmate():
        return "The position is checkmate."
    if board.is_stalemate():
        return "The position is stalemate."
    if board.is_insufficient_material():
        return "The position is drawn by insufficient material."
    return "The position is game over or claimable as a draw."


def _require_chess():
    try:
        import chess
        import chess.engine
    except ImportError as exc:
        raise RuntimeError("python-chess is required. Install it with: python -m pip install chess") from exc
    return chess
