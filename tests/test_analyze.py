from image2pgn.analyze import (
    MoveAnalysis,
    PositionAnalysis,
    _format_mate_delta,
    _move_themes,
    _hanging_piece_threats,
    format_analysis,
    resolve_engine_path,
)


def test_format_analysis_includes_candidate_moves():
    analysis = PositionAnalysis(
        fen="8/8/8/8/8/8/8/4K2k w - - 0 1",
        legal=True,
        turn="white",
        side_to_move="White",
        evaluation="+0.10",
        evaluation_cp=10,
        mate=None,
        summary="The engine prefers Ke2.",
        threats=["Hanging piece: Q on d4 is attacked and undefended."],
        warnings=["example warning"],
        moves=[
            MoveAnalysis(
                rank=1,
                move_uci="e1e2",
                san="Ke2",
                score="+0.10",
                score_cp=10,
                mate=None,
                delta="best-eval",
                delta_cp=0,
                pv_san=["Ke2", "Kh2"],
                themes=["improves king safety"],
            )
        ],
    )

    text = format_analysis(analysis)

    assert "Side to move: White" in text
    assert "Current evaluation: +0.10 from White's perspective" in text
    assert "Warnings:" in text
    assert "Current threats:" in text
    assert "Hanging piece" in text
    assert "1. Ke2 (+0.10, best-eval)" in text
    assert "ideas: improves king safety" in text


def test_format_analysis_describes_mated_line_as_danger():
    analysis = PositionAnalysis(
        fen="8/8/8/8/8/8/8/4K2k w - - 0 1",
        legal=True,
        turn="white",
        side_to_move="White",
        evaluation="mated in 2",
        evaluation_cp=-100000,
        mate=-2,
        summary="The side to move is in severe danger. Ke2 is the best defense found, but the engine still sees mate in 2.",
        threats=[],
        warnings=[],
        moves=[
            MoveAnalysis(
                rank=1,
                move_uci="e1e2",
                san="Ke2",
                score="mated in 2",
                score_cp=-100000,
                mate=-2,
                delta="best-eval",
                delta_cp=0,
                pv_san=["Ke2", "Kh2#"],
                themes=[],
            )
        ],
    )

    text = format_analysis(analysis)

    assert "best defense" in text
    assert "mated in 2" in text


def test_resolve_engine_path_accepts_explicit_file(tmp_path):
    engine = tmp_path / "stockfish.exe"
    engine.write_text("", encoding="utf-8")

    assert resolve_engine_path(engine) == engine


def test_format_mate_delta_describes_sooner_mate():
    assert _format_mate_delta(-1, -2) == "mated 1 ply sooner than best"


def test_hanging_piece_threats_reports_undefended_piece():
    import chess

    board = chess.Board("4k3/8/8/8/3q4/8/3B4/K7 w - - 0 1")

    threats = _hanging_piece_threats(chess, board)

    assert any("on d2" in threat for threat in threats)


def test_move_themes_detects_fork():
    import chess

    board = chess.Board("r3k3/8/1N6/8/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("b6c7")

    themes = _move_themes(chess, board, move)

    assert "creates a fork threat" in themes


def test_move_themes_detects_pin():
    import chess

    board = chess.Board("4k3/8/8/8/8/8/4r3/R3K3 w - - 0 1")
    move = chess.Move.from_uci("a1e1")

    themes = _move_themes(chess, board, move)

    assert "creates or increases a pin" in themes


def test_move_themes_detects_mate_threat():
    import chess

    board = chess.Board("6k1/8/8/8/8/8/6Q1/R3K3 w - - 0 1")
    move = chess.Move.from_uci("a1a7")

    themes = _move_themes(chess, board, move)

    assert "threatens checkmate next move" in themes
