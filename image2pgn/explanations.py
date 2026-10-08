"""Legal replay and fact extraction. No move history is inferred from an image."""
from __future__ import annotations

from pathlib import Path
import chess
import chess.engine

from .analyze import resolve_engine_path


class AnalysisCancelled(Exception):
    pass


def checked_board(fen):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("합법적인 국면이 아닙니다. 왕·차례·체크·특수 권리를 확인하세요.")
    return board


def prepare_position(fen, before_fen="", target_uci=""):
    current = checked_board(fen)
    root = checked_board(before_fen) if before_fen else current
    target = None
    if target_uci:
        target = chess.Move.from_uci(target_uci)
        if target not in root.legal_moves:
            raise ValueError("설명 대상 수가 확인한 시작 국면에서 합법적이지 않습니다.")
        if before_fen:
            after = root.copy()
            after.push(target)
            if (after.board_fen(), after.turn, after.castling_rights, after.ep_square) != (
                    current.board_fen(), current.turn, current.castling_rights, current.ep_square):
                raise ValueError("이전 FEN과 대상 수가 현재 FEN의 기물·차례·특수 권리와 일치하지 않습니다.")
    elif before_fen:
        raise ValueError("이전 FEN을 입력했다면 대상 UCI 수도 입력하세요.")
    return root, target


def replay_steps(root, moves, viewpoint, branch_id):
    board = root.copy()
    steps = []
    material = lambda b: sum((1 if p.color == viewpoint else -1) * {1: 1, 2: 3, 3: 3, 4: 5, 5: 9, 6: 0}[p.piece_type] for p in b.piece_map().values())
    baseline = material(board)
    for i, move in enumerate(moves[:12]):
        if move not in board.legal_moves:
            raise ValueError("엔진 수순에 합법적이지 않은 수가 있습니다.")
        san = board.san(move)
        side = "백" if board.turn else "흑"
        captured_square = (move.to_square + (-8 if board.turn else 8)) if board.is_en_passant(move) else move.to_square
        captured = board.piece_at(captured_square) if board.is_capture(move) else None
        facts = [dict(id=f"{branch_id}:{i}:move", kind="legal_move", uci=move.uci(), san=san)]
        text = f"{side}: {san}. {chess.square_name(move.from_square)} → {chess.square_name(move.to_square)}."
        if captured:
            name = {1: '폰', 2: '나이트', 3: '비숍', 4: '룩', 5: '퀸', 6: '왕'}[captured.piece_type]
            text += f" {chess.square_name(captured_square)}의 {name}을 잡습니다."
            facts.append(dict(id=f"{branch_id}:{i}:capture", kind="capture", piece=captured.symbol(), square=chess.square_name(captured_square)))
        before = board.fen()
        animation_moves = [dict(from_square=chess.square_name(move.from_square), to_square=chess.square_name(move.to_square))]
        if board.is_castling(move):
            rank = '1' if board.turn else '8'
            kingside = board.is_kingside_castling(move)
            animation_moves.append(dict(from_square=('h' if kingside else 'a')+rank, to_square=('f' if kingside else 'd')+rank))
        board.push(move)
        if board.is_checkmate():
            text += " 체크메이트입니다."
            facts.append(dict(id=f"{branch_id}:{i}:mate", kind="checkmate"))
        elif board.is_check():
            text += " 체크입니다."
        if move.promotion:
            text += " 승격합니다."
        if board.is_stalemate():
            text += " 스테일메이트입니다."
        steps.append(dict(id=f"{branch_id}:{i}", before_fen=before, after_fen=board.fen(), uci=move.uci(), san=san,
                          from_square=chess.square_name(move.from_square), to_square=chess.square_name(move.to_square),
                          animation_moves=animation_moves,
                          text_ko=text, facts=facts, material_delta=material(board)-baseline))
    return steps


def explain(fen, engine_path: Path | None, before_fen="", target_uci="", cancelled=None, movetime_ms=700):
    root, target = prepare_position(fen, before_fen, target_uci)
    viewpoint = root.turn
    def checkpoint():
        if cancelled and cancelled.is_set():
            raise AnalysisCancelled()
    checkpoint()
    branches = []
    engine_name = "terminal position"
    if not root.is_game_over():
        engine = chess.engine.SimpleEngine.popen_uci(str(resolve_engine_path(engine_path)), timeout=10)
        try:
            engine.configure({"Threads": 1, "Hash": 64})
            engine_name = engine.id.get("name", "Stockfish")
            def analyse(board, allowed=None):
                checkpoint()
                info = engine.analyse(board, chess.engine.Limit(time=movetime_ms/1000), root_moves=allowed)
                checkpoint()
                return info
            def branch(info, prefix, name, kind, conditional=False):
                pv = prefix + info.get("pv", [])
                score = info["score"].pov(viewpoint)
                branch_id = f"branch-{len(branches)}"
                score_board = root.copy()
                for move in prefix:
                    score_board.push(move)
                branches.append(dict(id=branch_id, label_ko=name, kind=kind, conditional=conditional,
                                     score_cp=score.score(), mate=score.mate(), depth=info.get("depth"),
                                     score_fen=score_board.fen(), score_stage_ko='대상 수 이후' if prefix else '시작 국면',
                                     steps=replay_steps(root, pv, viewpoint, branch_id)))
            best = analyse(root)
            branch(best, [], "현재 국면의 최선 수순", "best")
            if target:
                selected = analyse(root, [target])
                branch(selected, [], "대상 수 · 상대 최선 방어", "target")
                after = root.copy()
                after.push(target)
                captures = [m for m in after.legal_moves if after.is_capture(m) and m.to_square == target.to_square]
                if captures:
                    capture = analyse(after, captures)
                    forced = after.legal_moves.count() == 1
                    branch(capture, [target], "희생물을 잡았을 때" + (" · 유일한 합법 수" if forced else " · 조건부"), "capture", not forced)
        finally:
            engine.quit()
    checkpoint()
    shown = next((b for b in branches if b["kind"] == "target"), branches[0] if branches else None)
    mate = shown["mate"] if shown else None
    first = shown["steps"][0]["san"] if shown and shown["steps"] else ""
    if mate is not None:
        ko = f"{first}: 확인한 국면에서 {abs(mate)}수 {'메이트를 찾았습니다' if mate > 0 else '후 메이트를 당하는 평가입니다'}. 상대 최선 방어 수순을 확인하세요."
        en = f"The engine finds mate in {abs(mate)} {'for' if mate > 0 else 'against'} the moving side in the confirmed position. The board shows the verified line, sir."
    elif shown:
        ko = f"{first}: {'백' if viewpoint else '흑'} 관점 평가 {shown['score_cp']/100:+.2f}. 표시한 수순은 제한 시간 내 엔진 예상입니다."
        en = f"The confirmed position is analysed. The board shows the best defence and any capture variation, sir."
    else:
        ko = "이미 종료된 국면입니다. 추가 합법 수순이 없습니다."
        en = "The confirmed position is already over. There are no further moves to replay, sir."
    capture_branch = next((b for b in branches if b['kind'] == 'capture'), None)
    if capture_branch and capture_branch['steps']:
        steps = capture_branch['steps']
        end = chess.Board(steps[-1]['after_fen'])
        if end.is_checkmate() and end.turn != viewpoint:
            line = ' → '.join(s['san'] for s in steps)
            ko += (' 상대가 기물을 잡는 유일한 합법 응수 뒤 ' if not capture_branch['conditional'] else ' 상대가 기물을 잡는 조건부 가지에서는 ') + line + '로 메이트가 됩니다.'
    return dict(schema_version=1, fen=fen, root_fen=root.fen(), provenance="user_confirmed_game_state",
                assumptions=["사용자가 확인한 차례·캐슬링·앙파상 권리를 사용합니다."],
                engine=dict(name=engine_name, threads=1, hash_mib=64, per_branch_ms=movetime_ms,
                            max_calls=3, viewpoint="white" if viewpoint else "black"),
                branches=branches, brief_ko=ko, brief_en=en,
                caveats=["Chess.com의 Brilliant 판정을 인증하지 않습니다.", "수순은 제한 시간 내 엔진 예상이며 잡기 가지는 조건부일 수 있습니다."] +
                        ([] if before_fen else ["이미지 한 장에서 직전 수·잡힌 기물을 복원하지 않습니다. 현재 국면 또는 입력한 다음 수를 설명합니다."]))
