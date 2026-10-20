"""Compare a verified historical move with Stockfish from the same board."""
from __future__ import annotations

import chess
import chess.engine

from .analyze import resolve_engine_path
from .explanations import AnalysisCancelled, checked_board, replay_steps


def compare_move(game, ply, engine_path=None, *, cancelled=None, movetime_ms=700):
    def checkpoint():
        if cancelled and cancelled():
            raise AnalysisCancelled()

    checkpoint()
    if type(ply) is not int or not 0 <= ply < len(game['steps']):
        raise ValueError('비교할 실제 경기 수가 없습니다.')
    source = game['steps'][ply]
    root = checked_board(source['before_fen'])
    actual = chess.Move.from_uci(source['uci'])
    if actual not in root.legal_moves:
        raise ValueError('기록된 수를 현재 판에서 둘 수 없습니다.')
    engine = chess.engine.SimpleEngine.popen_uci(str(resolve_engine_path(engine_path)), timeout=10)
    try:
        engine.configure({'Threads': 1, 'Hash': 64})
        checkpoint()
        best = engine.analyse(root, chess.engine.Limit(time=movetime_ms / 1000))
        checkpoint()
        if not best.get('pv'):
            raise ValueError('엔진 추천 수순을 얻지 못했습니다.')
        recommended = best['pv'][0]
        # Validate before spending another search on a malformed engine line.
        replay_steps(root, best['pv'], chess.WHITE, 'recommended', max_plies=12)
        same = actual == recommended
        played = best if same else engine.analyse(root, chess.engine.Limit(time=movetime_ms / 1000), root_moves=[actual])
        checkpoint()
        if not played.get('pv') or played['pv'][0] != actual:
            raise ValueError('실제 수의 평가를 확인하지 못했습니다.')

        def line(info, name):
            steps = replay_steps(root, info['pv'], chess.WHITE, name, max_plies=12)
            if not steps:
                raise ValueError('합법적인 비교 수순이 없습니다.')
            score = info['score'].pov(chess.WHITE)
            return dict(uci=steps[0]['uci'], label_ko=steps[0]['short_ko'], steps=steps,
                        score_cp=score.score(), mate=score.mate(), depth=info.get('depth'))

        actual_line, recommended_line = line(played, 'actual'), line(best, 'recommended')
        delta = None
        if same:
            message = '실제 수가 이번 엔진 추천과 같습니다.'
        elif actual_line['mate'] is not None or recommended_line['mate'] is not None:
            message = '메이트 평가가 포함되어 점수 차이를 계산하지 않습니다.'
        else:
            delta = (recommended_line['score_cp'] - actual_line['score_cp']) * (1 if root.turn else -1)
            if delta < 0:
                delta = None
                message = '짧은 탐색에서 평가가 엇갈렸습니다. 점수 차이 판단을 보류합니다.'
            else:
                message = ('백' if root.turn else '흑') + f' 기준 추천 수의 평가가 {delta / 100:.2f}폰 높습니다.'
        return dict(game_id=game['id'], ply=ply, root_fen=root.fen(), mover='white' if root.turn else 'black',
                    same_move=same, actual=actual_line, recommended=recommended_line, delta_cp=delta,
                    difference_ko=message,
                    note_ko='두 평가는 각 수 이후 최선의 대응을 가정합니다. 실제 경기의 후속 기록과 다를 수 있습니다. 짧은 탐색 결과만으로 실수라고 단정하지 않습니다.',
                    engine=dict(name='Stockfish', viewpoint='white', movetime_ms=movetime_ms, threads=1, hash_mb=64, calls=1 if same else 2))
    finally:
        engine.quit()
