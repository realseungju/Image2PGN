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


def move_words(board, move):
    names = {1: '폰', 2: '나이트', 3: '비숍', 4: '룩', 5: '퀸', 6: '왕'}
    side = '백' if board.turn else '흑'
    mover = names[board.piece_at(move.from_square).piece_type]
    origin, dest = chess.square_name(move.from_square), chess.square_name(move.to_square)
    subject = '가' if mover == '나이트' else '이'
    victim_square = move.to_square + (-8 if board.turn else 8) if board.is_en_passant(move) else move.to_square
    victim = board.piece_at(victim_square) if board.is_capture(move) else None
    if board.is_castling(move):
        return f"{side}이 {'킹사이드' if board.is_kingside_castling(move) else '퀸사이드'} 캐슬링", '캐슬링'
    if victim:
        name = names[victim.piece_type]
        action = f"{side} {origin} {mover}{subject} {dest}의 {name}{'를' if name == '나이트' else '을'} 잡기"
        short = f"{mover}{'로' if mover == '나이트' else '으로'} {name} 잡기"
        if board.is_en_passant(move):
            action = f"{side} {origin} 폰이 {dest}로 이동해 상대 폰을 앙파상으로 잡기"
    elif mover == '폰':
        action, short = f'{side}이 {origin} 폰을 {dest}로 밀기', f'{dest} 폰 전진'
    else:
        action, short = f'{side}이 {origin} {mover}을 {dest}로 이동' if mover != '나이트' else f'{side}이 {origin} 나이트를 {dest}로 이동', f'{dest} {mover} 이동'
    if move.promotion:
        promoted = names[move.promotion]
        action += f" 후 {promoted}{'로' if promoted == '나이트' else '으로'} 승격"
        short += f' · {promoted} 승격'
    return action, short


def readable_action(action):
    action = action.replace('밀기 후 ', '밀어 ').replace('잡기 후 ', '잡고 ')
    endings = {'잡기': '잡습니다', '밀기': '밉니다', '이동': '이동합니다', '승격': '승격합니다', '캐슬링': '캐슬링합니다'}
    for ending, replacement in endings.items():
        if action.endswith(ending):
            return action[:-len(ending)] + replacement + '.'
    return action + '.'


def replay_steps(root, moves, viewpoint, branch_id):
    board = root.copy()
    steps = []
    material = lambda b: sum((1 if p.color == viewpoint else -1) * {1: 1, 2: 3, 3: 3, 4: 5, 5: 9, 6: 0}[p.piece_type] for p in b.piece_map().values())
    baseline = material(board)
    for i, move in enumerate(moves[:12]):
        if move not in board.legal_moves:
            raise ValueError("엔진 수순에 합법적이지 않은 수가 있습니다.")
        san = board.san(move)
        action, short = move_words(board, move)
        captured_square = (move.to_square + (-8 if board.turn else 8)) if board.is_en_passant(move) else move.to_square
        captured = board.piece_at(captured_square) if board.is_capture(move) else None
        facts = [dict(id=f"{branch_id}:{i}:move", kind="legal_move", uci=move.uci(), san=san)]
        if captured:
            facts.append(dict(id=f"{branch_id}:{i}:capture", kind="capture", piece=captured.symbol(), square=chess.square_name(captured_square)))
        before = board.fen()
        animation_moves = [dict(from_square=chess.square_name(move.from_square), to_square=chess.square_name(move.to_square))]
        if board.is_castling(move):
            rank = '1' if board.turn else '8'
            kingside = board.is_kingside_castling(move)
            animation_moves.append(dict(from_square=('h' if kingside else 'a')+rank, to_square=('f' if kingside else 'd')+rank))
        board.push(move)
        if board.is_checkmate():
            facts.append(dict(id=f"{branch_id}:{i}:mate", kind="checkmate"))
        steps.append(dict(id=f"{branch_id}:{i}", before_fen=before, after_fen=board.fen(), uci=move.uci(), san=san,
                          from_square=chess.square_name(move.from_square), to_square=chess.square_name(move.to_square),
                          animation_moves=animation_moves,
                          text_ko=readable_action(action) + (" 체크메이트입니다." if board.is_checkmate() else " 체크입니다." if board.is_check() else " 둘 수 있는 수가 없어 무승부입니다." if board.is_stalemate() else ""), short_ko=short, facts=facts, material_delta=material(board)-baseline))
    return steps


def capture_options(fen, before_fen="", target_uci="", capture_uci="", focus_square=""):
    """Only legal captures; this does not infer a previous move or call an engine."""
    root, target = prepare_position(fen, before_fen, target_uci)
    board = root.copy()
    if target:
        board.push(target)
    names = {1: '폰', 2: '나이트', 3: '비숍', 4: '룩', 5: '퀸', 6: '왕'}
    def victim_square(move):
        return move.to_square + (-8 if board.turn else 8) if board.is_en_passant(move) else move.to_square
    targets = [dict(square=chess.square_name(s), piece=p.symbol(),
                    label_ko=f"{'백' if p.color else '흑'} {names[p.piece_type]}({chess.square_name(s)})")
               for s, p in sorted(board.piece_map().items()) if p.color != board.turn and p.piece_type != chess.KING]
    focus = None
    moves = list(board.generate_legal_captures())
    if focus_square:
        square = chess.parse_square(focus_square)
        piece = board.piece_at(square)
        if not piece or piece.color == board.turn or piece.piece_type == chess.KING:
            raise ValueError('잡히는 대상은 상대 기물이어야 합니다. 대상 칸과 차례를 확인하세요.')
        focus = next(t for t in targets if t['square'] == focus_square)
        moves = [m for m in moves if victim_square(m) == square]
    if capture_uci:
        chosen = chess.Move.from_uci(capture_uci)
        if chosen not in moves:
            raise ValueError("선택한 잡기는 이 차례에 둘 수 없습니다. 차례와 말을 다시 확인하세요.")
    choices = []
    for move in moves:
        square = move.to_square + (-8 if board.turn else 8) if board.is_en_passant(move) else move.to_square
        victim = board.piece_at(square)
        choices.append(dict(uci=move.uci(), san=board.san(move), from_square=chess.square_name(move.from_square),
                            to_square=chess.square_name(move.to_square), captured_piece=victim.symbol(),
                            label_ko=move_words(board, move)[0]))
    return dict(turn='white' if board.turn else 'black', stage='after_target' if target else 'current', captures=choices,
                targets=targets, focus=focus,
                reason_ko=f"{focus['label_ko']}을 잡는 합법적인 수가 없습니다." if focus and not moves else '')


def explain(fen, engine_path: Path | None, before_fen="", target_uci="", cancelled=None, movetime_ms=700, capture_uci="", focus_square=""):
    root, target = prepare_position(fen, before_fen, target_uci)
    options = capture_options(fen, before_fen, target_uci, capture_uci, focus_square)
    viewpoint = root.turn
    def checkpoint():
        if cancelled and cancelled.is_set():
            raise AnalysisCancelled()
    checkpoint()
    branches = []
    comparison = dict(available=False, reason_ko='지금 차례에 잡을 수 있는 말이 없습니다.')
    if root.is_game_over():
        comparison['reason_ko'] = '이미 끝난 게임이므로 잡기 수순을 분석하지 않습니다.'
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
            def branch(info, prefix, name, kind, conditional=False, comparison_stage='current'):
                pv = prefix + info.get("pv", [])
                score = info["score"].pov(viewpoint)
                branch_id = f"branch-{len(branches)}"
                score_board = root.copy()
                for move in prefix:
                    score_board.push(move)
                branches.append(dict(id=branch_id, label_ko=name, kind=kind, conditional=conditional,
                                     comparison_stage=comparison_stage,
                                     score_cp=score.score(), mate=score.mate(), depth=info.get("depth"),
                                     score_fen=score_board.fen(), score_stage_ko='선택한 수를 둔 뒤의 평가' if prefix else '분석을 시작한 판의 평가',
                                     steps=replay_steps(root, pv, viewpoint, branch_id)))
            best = analyse(root)
            branch(best, [], "엔진 추천 수", "best")
            if target:
                selected = analyse(root, [target])
                branch(selected, [], "선택한 수에 대한 최선의 대응", "target")
            capture_board = root.copy()
            prefix = []
            stage = 'current'
            if target:
                capture_board.push(target)
                prefix = [target]
                stage = 'after_target'
                captures = [m for m in capture_board.generate_legal_captures() if m.to_square == target.to_square]
                comparison['reason_ko'] = '선택한 수를 둔 뒤 그 말을 잡는 합법적인 대응이 없습니다.'
            else:
                captures = list(capture_board.generate_legal_captures())
            if focus_square:
                captures = [chess.Move.from_uci(c['uci']) for c in options['captures']]
                comparison['reason_ko'] = options['reason_ko']
            if capture_uci:
                captures = [chess.Move.from_uci(capture_uci)]
            elif not focus_square and not target and not captures and best.get('pv'):
                # Explicit future variation, never a reconstruction of the screenshot's last move.
                recommended = best['pv'][0]
                capture_board.push(recommended)
                prefix = [recommended]
                stage = 'after_recommendation'
                captures = [m for m in capture_board.generate_legal_captures() if m.to_square == recommended.to_square]
                comparison['reason_ko'] = '지금 잡을 수 있는 말이 없고, 추천 수를 둔 뒤에도 그 말을 잡는 합법적인 대응이 없습니다.'
            if captures and not capture_board.is_game_over():
                capture = analyse(capture_board, captures)
                if not capture.get('pv'):
                    raise ValueError('엔진에서 잡기 수순을 받지 못했습니다. 다시 분석해주세요.')
                move = capture.get('pv', [])[0]
                forced = capture_board.legal_moves.count() == 1
                square = move.to_square + (-8 if capture_board.turn else 8) if capture_board.is_en_passant(move) else move.to_square
                victim = capture_board.piece_at(square)
                names = {1:'폰', 2:'나이트', 3:'비숍', 4:'룩', 5:'퀸', 6:'왕'}
                name = names[victim.piece_type]
                who = '백' if capture_board.turn else '흑'
                label = f"{who}이 {name}{'를' if name == '나이트' else '을'} 잡으면"
                branch(capture, prefix, label, 'capture', not forced, stage)
                comparison = dict(available=True, stage=stage, selected_uci=move.uci(), conditional=not forced,
                                  reason_ko='이 잡기만 둘 수 있습니다.' if forced else '이 수로 잡는 경우를 가정한 수순입니다.')
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
    if capture_branch and capture_branch['mate'] not in (None, 0):
        capture_mate = capture_branch['mate']
        winner = ('백' if viewpoint else '흑') if capture_mate > 0 else ('흑' if viewpoint else '백')
        ko += f" 선택한 잡기 수순에서는 {winner}이 {abs(capture_mate)}수 안에 체크메이트할 수 있습니다."
        en = f"In the capture variation, {'White' if winner == '백' else 'Black'} can force checkmate in {abs(capture_mate)} moves. The board compares it with the best defence, sir."
    if options['focus']:
        focus = options['focus']
        if not capture_branch:
            ko = comparison['reason_ko'] + ' 다른 기물을 잡는 수로 바꾸지 않았습니다.'
            en = 'There is no legal capture of the selected piece in this position, sir.'
        else:
            replies = capture_branch['steps'][(1 if not target else 2):]
            response = replies[0]['san'] if replies else ''
            focus_name = ("백" if focus["piece"].isupper() else "흑") + " " + {"p":"폰","n":"나이트","b":"비숍","r":"룩","q":"퀸"}[focus["piece"].lower()]
            ko = f"{focus_name}{'를' if focus['piece'].lower() == 'n' else '을'} 잡은 뒤의 포지션을 분석했습니다."
            if response:
                ko += " 상대의 최선 대응: " + replies[0]["text_ko"]
            losing_mate = capture_branch['mate'] not in (None, 0) and (
                (capture_branch['mate'] > 0) != (capture_board.turn == viewpoint))
            first_reply_mate = replies and any(f['kind'] == 'checkmate' for f in replies[0]['facts'])
            if losing_mate:
                winner = 'White' if not capture_board.turn else 'Black'
                if not first_reply_mate:
                    ko += f" 이 수순에서는 {abs(capture_branch['mate'])}수 안에 체크메이트됩니다."
                en = (f"Capturing the {'queen' if focus['piece'].lower() == 'q' else 'selected piece'} allows "
                      f"{winner} to force checkmate. Follow the reply on the board, sir.")
                if branches[0]['mate'] not in (None, 0) and ((branches[0]['mate'] > 0) != (capture_board.turn == viewpoint)):
                    ko += ' 이 판에서는 최선으로 대응해도 메이트를 피할 수 없습니다.'
            else:
                ko += ' 이 분석만으로 이 기물을 잡으면 안 된다고 단정할 수는 없습니다.'
                en = 'The selected capture is analysed. This line does not establish that capturing is a mistake, sir.'
            comparison['response_san'] = response
    comparison['focus'] = options['focus']
    for line in branches:
        if line['kind'] == 'capture' and options['focus']:
            line['brief_ko'] = ko
        else:
            move_text = line['steps'][0]['text_ko'].rstrip('.') if line['steps'] else ''
            line['brief_ko'] = (('엔진 추천: ' if line['kind'] == 'best' else '선택한 수순: ') + line['steps'][0]['text_ko']) if move_text else '이어질 수가 없습니다.'
            if line['mate'] not in (None, 0) and not any(f['kind'] == 'checkmate' for f in line['steps'][0]['facts']):
                winner = ('백' if viewpoint else '흑') if line['mate'] > 0 else ('흑' if viewpoint else '백')
                line['brief_ko'] += f" 최선으로 대응해도 {winner}이 {abs(line['mate'])}수 안에 체크메이트할 수 있습니다."
            elif line['score_cp'] is not None:
                score = line['score_cp']
                leader = ('백' if viewpoint else '흑') if score > 0 else ('흑' if viewpoint else '백')
                line['brief_ko'] += f' {leader}이 유리합니다.' if score else ' 양쪽이 균형입니다.'
            if line['kind'] == 'capture':
                line['brief_ko'] = '이 기물을 잡은 뒤의 포지션을 분석했습니다. ' + line['brief_ko']
    if not options['focus'] and shown:
        ko = shown['brief_ko']
    return dict(schema_version=1, fen=fen, root_fen=root.fen(), provenance="user_confirmed_game_state",
                assumptions=["차례와 캐슬링·앙파상 가능 여부는 직접 확인한 정보를 기준으로 합니다."],
                engine=dict(name=engine_name, threads=1, hash_mib=64, per_branch_ms=movetime_ms,
                            max_calls=3, viewpoint="white" if viewpoint else "black"),
                branches=branches, capture_comparison=comparison, brief_ko=ko, brief_en=en,
                caveats=["좋은 수인 이유를 분석하며, Chess.com의 ‘탁월한 수’ 판정을 확인하는 기능은 아닙니다.", "엔진이 제한된 시간에 찾은 수순입니다. ‘가정’으로 표시한 수순은 상대가 그렇게 대응할 때만 이어집니다."] +
                        ([] if before_fen else ["사진 한 장으로는 직전 수나 이미 잡힌 기물을 알 수 없습니다. 보이는 판에서 이어질 수를 분석합니다."]))
