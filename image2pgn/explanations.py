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
        names = {1: '폰', 2: '나이트', 3: '비숍', 4: '룩', 5: '퀸', 6: '왕'}
        mover = names[board.piece_at(move.from_square).piece_type]
        text = f"{side} {mover}이 {chess.square_name(move.to_square)}로 이동합니다." if mover in ('폰', '룩', '왕', '퀸', '비숍') else f"{side} {mover}가 {chess.square_name(move.to_square)}로 이동합니다."
        if board.is_castling(move):
            text = f"{side}이 {'킹사이드' if board.is_kingside_castling(move) else '퀸사이드'} 캐슬링을 합니다."
        if captured:
            name = names[captured.piece_type]
            subject = '이' if mover in ('폰', '룩', '왕', '퀸', '비숍') else '가'
            particle = '을' if name in ('폰', '룩', '퀸', '왕', '비숍') else '를'
            text = f"{side} {mover}{subject} {name}{particle} 잡습니다."
            if board.is_en_passant(move):
                text += " 앙파상입니다."
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
            name = names[move.promotion]
            text += f" 폰을 {name}{'로' if name == '나이트' else '으로'} 승격합니다."
        if board.is_stalemate():
            text += " 둘 수 있는 수가 없어 무승부입니다(스테일메이트)."
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
                                     score_fen=score_board.fen(), score_stage_ko='선택한 수를 둔 뒤의 평가' if prefix else '분석을 시작한 판의 평가',
                                     steps=replay_steps(root, pv, viewpoint, branch_id)))
            best = analyse(root)
            branch(best, [], "엔진 추천 수", "best")
            if target:
                selected = analyse(root, [target])
                branch(selected, [], "선택한 수에 대한 최선의 대응", "target")
                after = root.copy()
                after.push(target)
                captures = [m for m in after.legal_moves if after.is_capture(m) and m.to_square == target.to_square]
                if captures:
                    capture = analyse(after, captures)
                    forced = after.legal_moves.count() == 1
                    branch(capture, [target], "상대가 기물을 잡으면" + (" (유일한 대응)" if forced else " (가정)"), "capture", not forced)
        finally:
            engine.quit()
    checkpoint()
    shown = next((b for b in branches if b["kind"] == "target"), branches[0] if branches else None)
    mate = shown["mate"] if shown else None
    if mate is not None:
        winner = ('백' if viewpoint else '흑') if mate > 0 else ('흑' if viewpoint else '백')
        ko = f"처음 판에서는 상대가 최선으로 대응해도 {winner}이 {abs(mate)}수 안에 체크메이트할 수 있습니다."
        en = f"{'White' if winner == '백' else 'Black'} can force checkmate in {abs(mate)} {'move' if abs(mate) == 1 else 'moves'}. Follow the line on the board, sir."
    elif shown:
        score = shown['score_cp']
        leader = ('백' if viewpoint else '흑') if score > 0 else ('흑' if viewpoint else '백')
        ko = f"엔진은 {leader}이 유리하다고 평가합니다. 상대의 대응을 한 수씩 살펴보세요." if score else "엔진은 양쪽이 균형을 이룬다고 평가합니다. 이어지는 수를 살펴보세요."
        en = f"The confirmed position is analysed. The board shows the best defence and any capture variation, sir."
    else:
        ko = "이미 끝난 게임입니다. 이어서 재생할 수가 없습니다."
        en = "The confirmed position is already over. There are no further moves to replay, sir."
    capture_branch = next((b for b in branches if b['kind'] == 'capture'), None)
    if capture_branch and capture_branch['steps']:
        steps = capture_branch['steps']
        end = chess.Board(steps[-1]['after_fen'])
        if end.is_checkmate() and end.turn != viewpoint:
            if capture_branch['conditional']:
                ko += " 상대가 기물을 잡는 경우에도 체크메이트로 이어집니다."
    return dict(schema_version=1, fen=fen, root_fen=root.fen(), provenance="user_confirmed_game_state",
                assumptions=["차례와 캐슬링·앙파상 가능 여부는 직접 확인한 정보를 기준으로 합니다."],
                engine=dict(name=engine_name, threads=1, hash_mib=64, per_branch_ms=movetime_ms,
                            max_calls=3, viewpoint="white" if viewpoint else "black"),
                branches=branches, brief_ko=ko, brief_en=en,
                caveats=["좋은 수인 이유를 분석하며, Chess.com의 ‘탁월한 수’ 판정을 확인하는 기능은 아닙니다.", "엔진이 제한된 시간에 찾은 수순입니다. ‘가정’으로 표시한 수순은 상대가 그렇게 대응할 때만 이어집니다."] +
                        ([] if before_fen else ["사진 한 장으로는 직전 수나 이미 잡힌 기물을 알 수 없습니다. 보이는 판에서 이어질 수를 분석합니다."]))
