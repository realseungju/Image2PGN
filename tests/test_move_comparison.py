from pathlib import Path
from types import SimpleNamespace
import threading

import chess
import chess.engine
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from image2pgn.explanations import AnalysisCancelled, replay_steps
from image2pgn.master_games import MasterGames, position_key
from image2pgn.move_comparison import compare_move
from image2pgn.explanation_api import install_explanation_api


def game(fen=chess.STARTING_FEN, actual='e2e4'):
    return dict(id='sample', steps=replay_steps(chess.Board(fen), [chess.Move.from_uci(actual)], chess.WHITE, 'record'))


def info(uci, cp=20, mate=None):
    score = chess.engine.Mate(mate) if mate is not None else chess.engine.Cp(cp)
    return dict(pv=[chess.Move.from_uci(uci)], score=chess.engine.PovScore(score, chess.WHITE), depth=18)


def fake_engine(monkeypatch, results):
    import image2pgn.move_comparison as module
    class Engine:
        calls=[]
        closed=False
        def configure(self, config): self.config=config
        def analyse(self, board, limit, **kwargs):
            self.calls.append((board.fen(), limit.time, kwargs))
            return results[len(self.calls)-1]
        def quit(self): self.closed=True
    engine=Engine()
    monkeypatch.setattr(module, 'resolve_engine_path', lambda _: 'fake')
    monkeypatch.setattr(module.chess.engine.SimpleEngine, 'popen_uci', lambda *a, **kw: engine)
    return engine


def test_same_move_reuses_one_search_and_closes_engine(monkeypatch):
    engine=fake_engine(monkeypatch,[info('e2e4')])
    result=compare_move(game(),0)
    assert result['same_move'] and result['actual']['uci']==result['recommended']['uci']
    assert result['actual']['score_cp']==result['recommended']['score_cp']
    assert len(engine.calls)==1 and engine.closed
    assert engine.config=={'Threads':1,'Hash':64}
    assert result['engine']['viewpoint']=='white'


def test_different_move_uses_identical_root_and_restricts_actual(monkeypatch):
    engine=fake_engine(monkeypatch,[info('d2d4',60),info('e2e4',15)])
    result=compare_move(game(),0)
    assert not result['same_move'] and result['delta_cp']==45
    assert engine.calls[0][0]==engine.calls[1][0]==result['root_fen']
    assert engine.calls[0][1]==engine.calls[1][1]==0.7
    assert engine.calls[1][2]['root_moves']==[chess.Move.from_uci('e2e4')]
    assert result['recommended']['steps'][0]['uci']=='d2d4'
    assert result['actual']['steps'][0]['uci']=='e2e4'


def test_black_score_gap_uses_mover_but_display_stays_white(monkeypatch):
    board=chess.Board();board.push_uci('e2e4')
    fake_engine(monkeypatch,[info('c7c5',-80),info('e7e5',-10)])
    result=compare_move(game(board.fen(),'e7e5'),0)
    assert result['mover']=='black' and result['delta_cp']==70
    assert result['recommended']['score_cp']==-80 and result['actual']['score_cp']==-10


@pytest.mark.parametrize('best,actual',[(info('d2d4',mate=3),info('e2e4',40)),(info('d2d4',10),info('e2e4',30))],ids=['mate','search-disagreement'])
def test_mate_and_inconsistent_search_never_become_fake_loss(monkeypatch,best,actual):
    fake_engine(monkeypatch,[best,actual])
    result=compare_move(game(),0)
    assert result['delta_cp'] is None
    assert '계산하지' in result['difference_ko'] or '보류' in result['difference_ko']


@pytest.mark.parametrize('fen,uci',[
    ('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1','e1g1'),
    ('4k3/P7/8/8/8/8/8/4K3 w - - 0 1','a7a8q'),
    ('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1','e5d6'),
],ids=['castle','promotion','en-passant'])
def test_special_move_replay_keeps_valid_animation_and_facts(monkeypatch,fen,uci):
    fake_engine(monkeypatch,[info(uci)])
    result=compare_move(game(fen,uci),0)
    assert result['actual']['steps'][0]['after_fen']==game(fen,uci)['steps'][0]['after_fen']
    assert chess.Board(result['actual']['steps'][0]['after_fen']).is_valid()
    if uci=='e1g1': assert len(result['actual']['steps'][0]['animation_moves'])==2


def test_cancel_after_search_and_illegal_pv_always_quit(monkeypatch):
    engine=fake_engine(monkeypatch,[info('e2e4')]);checks=[]
    def cancel(): checks.append(1);return len(checks)==3
    with pytest.raises(AnalysisCancelled):compare_move(game(),0,cancelled=cancel)
    assert engine.closed
    engine=fake_engine(monkeypatch,[info('e2e5')])
    with pytest.raises(ValueError):compare_move(game(),0)
    assert engine.closed


def test_resolver_uses_only_position_matched_catalog_or_cached_remote():
    finder=MasterGames();source=finder.catalog[0];fen=source['steps'][36]['after_fen']
    assert finder.resolve_game(fen,source['id']) is source
    with pytest.raises(ValueError):finder.resolve_game(fen,finder.catalog[1]['id'])
    remote={**source,'id':'abcd1234'}
    finder.cache[position_key(chess.Board(fen))]=(0,dict(games=[remote]))
    assert finder.resolve_game(fen,'abcd1234') is remote
    with pytest.raises(ValueError):finder.resolve_game(chess.Board().fen(),'abcd1234')


def api_service():
    app=FastAPI();app.state.config=SimpleNamespace(engine_path=None)
    store=install_explanation_api(app,lambda _:None,Path(__file__).parents[1]/'image2pgn/web')
    source=app.state.master_games.catalog[0]
    store.jobs['test']=dict(status='ready', result=dict(fen=source['steps'][36]['after_fen']),_cancel=threading.Event())
    return app,store,dict(game_id=source['id'],ply=37)


def test_api_auth_ready_validated_game_and_bounded_cache():
    app,store,selection=api_service();calls=[]
    def compare(*args,**kw): calls.append(args);return dict(ok=True)
    app.state.move_comparer=compare
    with TestClient(app) as client:
        url='/api/explanations/test/compare-move'
        assert client.post(url,json=selection).status_code==401
        client.headers['x-chesslens-token']=store.token
        for bad in [{**selection,'fen':chess.STARTING_FEN},{**selection,'ply':True},{**selection,'ply':999},{**selection,'game_id':'forged'},{**selection,'ply':41}]:
            assert client.post(url,json=bad).status_code==422
        store.comparison_gate.acquire()
        assert client.post(url,json=selection).status_code==429
        store.comparison_gate.release()
        for _ in range(2):
            response=client.post(url,json=selection)
            assert response.status_code==200 and response.json()==dict(ok=True)
            assert response.headers['cache-control']=='no-store'
        assert len(calls)==1
        store.jobs['test']['_cancel'].set()
        assert client.post(url,json=selection).status_code==409


def test_cancelled_inflight_result_is_never_cached_or_returned():
    app,store,selection=api_service()
    def compare(*args,**kw):
        store.jobs['test']['_cancel'].set()
        assert kw['cancelled']()
        return dict(stale=True)
    app.state.move_comparer=compare
    with TestClient(app) as client:
        client.headers['x-chesslens-token']=store.token
        assert client.post('/api/explanations/test/compare-move',json=selection).status_code==409
        assert not store.comparison_cache and not store.comparison_gate.locked()


def test_timeout_abandons_result_but_keeps_gate_until_worker_finishes(monkeypatch):
    app,store,selection=api_service();finish=threading.Event();observed=[];futures=[]
    submit=store.pool.submit
    def compare(*args,**kw):
        assert finish.wait(3)
        observed.append(kw['cancelled']())
        return dict(late=True)
    class ShortDeadline:
        def __init__(self,future):self.future=future
        def add_done_callback(self,callback):self.future.add_done_callback(callback)
        def result(self,timeout):return self.future.result(timeout=.01)
        def cancel(self):return self.future.cancel()
    def limited_submit(*args,**kwargs):
        future=submit(*args,**kwargs);futures.append(future);return ShortDeadline(future)
    monkeypatch.setattr(store.pool,'submit',limited_submit)
    app.state.move_comparer=compare
    with TestClient(app) as client:
        client.headers['x-chesslens-token']=store.token
        url='/api/explanations/test/compare-move'
        try:
            assert client.post(url,json=selection).status_code==504
            assert store.comparison_gate.locked()
            assert client.post(url,json=selection).status_code==429
        finally:
            finish.set()
            if futures:futures[0].result(timeout=2)
        assert observed==[True] and not store.comparison_cache
        assert not store.comparison_gate.locked()
