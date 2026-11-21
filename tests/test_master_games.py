import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import chess
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from image2pgn.master_games import MasterGames, RemoteFailure, eligible, parse_game, position_key, match_game, MAX_BYTES
from image2pgn.explanation_api import install_explanation_api

AFTER_RF6 = 'r3qr1k/pp3pbp/2pn1R2/7Q/3pP3/2NB3P/PPP3P1/R5K1 b - - 1 19'


def service(fetch=None, **kwargs):
    return MasterGames(fetch=fetch or (lambda _: (_ for _ in ()).throw(AssertionError('Unexpected network'))), **kwargs)


def test_catalog_actual_game_and_full_replay_not_engine_continuation():
    result = service().lookup(AFTER_RF6)
    game = result['games'][0]
    assert result['remote_status'] == 'not_requested'
    assert game['category'] == 'famous' and game['white']['rating'] is None
    assert game['match_plies'] == [37] and len(game['steps']) == 41
    assert [step['uci'] for step in game['steps'][37:]] == ['h8g8', 'e4e5', 'h7h6', 'c3e2']
    assert game['result'] == '1-0' and not chess.Board(game['steps'][-1]['after_fen']).is_checkmate()
    assert game['sources'][0]['url'].startswith('https://')


def test_century_full_82_plies_and_final_mate():
    game = service().catalog[1]
    assert len(game['steps']) == 82
    assert chess.Board(game['steps'][-1]['after_fen']).is_checkmate()
    board = chess.Board(game['steps'][33]['after_fen'])
    assert service().lookup(board.fen())['games'][0]['match_plies'] == [34]


def test_repeated_position_keeps_all_occurrences():
    game=parse_game('[Result "1/2-1/2"]\n\n1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2','repeat')
    assert match_game(game,position_key(chess.Board()))['match_plies'] == [0,4,8]


def test_match_ignores_counters_but_preserves_turn_and_rights():
    finder = service()
    assert finder.lookup(AFTER_RF6.replace('1 19', '0 1'))['games']
    # Use a legal opposite-turn board for the no-match test.
    opening = finder.catalog[0]['steps'][1]['after_fen']
    assert finder.lookup(opening)['games']
    board = chess.Board(opening)
    board.turn = not board.turn
    assert not finder.lookup(board.fen())['games']
    board = chess.Board(opening)
    board.castling_rights = 0
    assert not finder.lookup(board.fen())['games']


def test_en_passant_uses_legal_capture_not_phantom_target():
    a = chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
    b = chess.Board(a.fen().replace(' d6 ', ' - '))
    assert position_key(a) != position_key(b)
    assert position_key(chess.Board('4k3/8/8/3p4/8/8/8/4K3 w - d6 0 1')) == position_key(chess.Board('4k3/8/8/3p4/8/8/8/4K3 w - - 0 1'))


@pytest.mark.parametrize('white,black,expected', [(2400,2400,True),(2800,2399,False),(None,2800,False),('?',2800,False),(True,2800,False),(2500,2500.5,False)])
def test_both_ratings_required(white,black,expected):
    assert eligible(dict(white={'rating':white},black={'rating':black})) == expected


def candidate(game_id,white=2500,black=2600):
    return dict(id=game_id,white=dict(name='White',rating=white),black=dict(name='Black',rating=black))


def test_remote_masters_only_filters_before_pgn_and_caches():
    finder = service()
    pgn_path = Path(__file__).parents[1]/'image2pgn/data/famous_games.json'
    pgn = json.loads(pgn_path.read_text(encoding='utf-8'))[0]['pgn']
    calls = []
    def fetch(url):
        calls.append(url)
        if '/pgn/' in url:
            assert url.endswith('Abcd1234')
            return pgn
        return json.dumps(dict(topGames=[candidate('Abcd1234'),candidate('LowR1234',2300),candidate('NoRa1234',None)]))
    finder.fetch = fetch
    result = finder.lookup(AFTER_RF6,remote=True)
    assert result['remote_status'] == 'available' and len(result['games']) == 1  # deduplicated against catalog
    assert len(calls) == 2 and all(u.startswith('https://explorer.lichess.org/masters') for u in calls)
    assert 'since=' not in calls[0]  # Use the API's valid default range, not invalid year zero.
    assert finder.lookup(AFTER_RF6,remote=True)['games'] == result['games'] and len(calls) == 2


def test_high_rated_remote_game_is_returned_only_after_pgn_position_check():
    pgn = '[White "Master A"]\n[Black "Master B"]\n[Result "1/2-1/2"]\n\n1. e4 e5 2. Nf3 Nc6 1/2-1/2'
    query = chess.Board();query.push_san('e4')
    finder = service(lambda url: pgn if '/pgn/' in url else json.dumps(dict(topGames=[candidate('Abcd1234')])))
    result = finder.lookup(query.fen(),remote=True)
    game = next(g for g in result['games'] if g['category'] == 'master')
    assert game['white']['rating'] == 2500 and game['match_plies'] == [1]
    assert game['steps'][-1]['uci'] == 'b8c6'
    unrelated = finder.lookup(AFTER_RF6,remote=True)
    assert all(g['category'] == 'famous' for g in unrelated['games'])
    assert unrelated['remote_status'] == 'partial'


@pytest.mark.parametrize('status', ['unavailable','rate_limited'])
def test_failure_is_not_empty_success_and_global_cooldown_keeps_local(status):
    now = [0]
    calls = []
    def fetch(url):
        calls.append(url)
        raise RemoteFailure(status,'접근 실패')
    finder = service(fetch,clock=lambda:now[0])
    result = finder.lookup(AFTER_RF6,remote=True)
    assert result['games'] and result['remote_status'] == status
    finder.lookup(chess.STARTING_FEN,remote=True)
    assert len(calls) == 1
    now[0] = 61
    finder.lookup(AFTER_RF6,remote=True)
    assert len(calls) == 2


def test_busy_search_returns_local_without_blocking():
    finder = service()
    finder.lock.acquire()
    try:
        result = finder.lookup(AFTER_RF6,remote=True)
        assert result['games'] and result['remote_status'] == 'busy'
    finally:
        finder.lock.release()


@pytest.mark.parametrize('pgn', [
    '[Result "1-0"]\n\n1. e4 e5 2. Qh8 1-0',
    '[Result "*"]\n\n1. e4 *',
    '[Result "1-0"]\n\n1. e4 1-0\n\n[Result "0-1"]\n\n1. d4 0-1',
    'x'*(MAX_BYTES+1),
    '[Result "1-0"]\n[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/4K3 w - - 0 1"]\n\n1. Kd2 1-0'
], ids=['illegal-move','unfinished','multiple-games','oversized','partial-start'])
def test_bad_pgn_is_rejected(pgn):
    with pytest.raises(ValueError):
        parse_game(pgn,'test')


def test_api_requires_auth_ready_and_confirmed_job_position():
    app = FastAPI();app.state.config=SimpleNamespace(engine_path=None)
    store=install_explanation_api(app,lambda _:None,Path(__file__).parents[1]/'image2pgn/web')
    app.state.master_games=service()
    with TestClient(app) as client:
        download = '/api/explanations/test/master-games/fischer-benko-1963/pgn'
        assert client.get(download).status_code == 401
        assert client.get('/api/explanations/no/master-games').status_code == 401
        client.headers['x-chesslens-token']=store.token
        assert client.get('/api/explanations/no/master-games').status_code == 404
        store.jobs['test'] = dict(job_id='test',status='needs_input',result=None,_cancel=threading.Event())
        assert client.get('/api/explanations/test/master-games').status_code == 409
        assert client.get(download).status_code == 409
        store.jobs['test'].update(status='ready',result=dict(fen=AFTER_RF6))
        for query, count in [('', 41), ('?through_ply=37', 37)]:
            reply = client.get(download + query)
            assert reply.status_code == 200
            assert reply.headers['content-type'].startswith('application/x-chess-pgn')
            assert reply.headers['content-disposition'].endswith('.pgn"')
            assert len(list(chess.pgn.read_game(io.StringIO(reply.text)).mainline_moves())) == count
        assert client.get(download, params={'through_ply': 36}).status_code == 422
        assert client.get(download.replace('fischer-benko-1963', 'other')).status_code == 422
        result=client.get('/api/explanations/test/master-games')
        assert result.status_code == 200 and result.json()['games'][0]['match_plies'] == [37]
        assert result.headers['cache-control'] == 'no-store'
        store.jobs['test']['status']='cancelled'
        assert client.get(download).status_code == 409
        assert client.get('/api/explanations/test/master-games').status_code == 409


def test_network_auth_timeout_size_and_no_redirects(monkeypatch):
    import image2pgn.master_games as module
    captured={}
    class Response:
        status_code=401
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_bytes(self):yield b'x'*(MAX_BYTES+1)
    class Client:
        def __init__(self,**kwargs):captured.update(kwargs)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,*args,**kwargs):captured.update(kwargs);return Response()
    monkeypatch.setattr(module.httpx,'Client',Client)
    monkeypatch.setenv('CHESSLENS_LICHESS_TOKEN','test_secret')
    with pytest.raises(RemoteFailure) as exc:service()._fetch(module.MASTERS_URL)
    assert exc.value.status == 'auth_required' and 'test_secret' not in str(exc.value)
    assert captured['follow_redirects'] is False and captured['timeout']==5
    assert captured['headers']['Authorization']=='Bearer test_secret'
    Response.status_code=429
    with pytest.raises(RemoteFailure) as exc:service()._fetch(module.MASTERS_URL)
    assert exc.value.status=='rate_limited'
    Response.status_code=200
    with pytest.raises(RemoteFailure):service()._fetch(module.MASTERS_URL)


def test_cache_bound_and_invalid_fen():
    finder=service(lambda _:json.dumps(dict(topGames=[])))
    for i in range(40):
        finder.cache[str(i)]=(9999,{})
    finder.lookup(AFTER_RF6,remote=True)
    assert len(finder.cache)==32
    with pytest.raises(ValueError):finder.lookup('8/8/8/8/8/8/8/8 w - - 0 1')


def test_catalog_pgn_round_trip():
    finder = service()
    catalog = Path(__file__).parents[1] / 'image2pgn/data/famous_games.json'
    for item, record in zip(json.loads(catalog.read_text(encoding='utf-8')), finder.catalog, strict=True):
        original = chess.pgn.read_game(io.StringIO(item['pgn']))
        moves = list(original.mainline_moves())
        for ply in (None, 0, 1, len(moves)//2, len(moves)):
            end = len(moves) if ply is None else ply
            board = original.board()
            for move in moves[:end]:
                board.push(move)
            text = finder.export_pgn(board.fen(), record['id'], ply)
            exported = chess.pgn.read_game(io.StringIO(text))
            assert not exported.errors
            assert list(exported.mainline_moves()) == moves[:end]
            assert exported.end().board().fen() == board.fen()
            for key in ('Event', 'Site', 'Round', 'Date', 'White', 'Black'):
                assert exported.headers[key] == original.headers[key]
            expected = original.headers['Result'] if end == len(moves) else '*'
            assert exported.headers['Result'] == expected and text.rstrip().endswith(expected)
            assert exported.headers['Source'] == item['sources'][0]['url']


def test_remote_export_repetition_and_expiry():
    now = [5]
    pgn = '[Result "1/2-1/2"]\n\n1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2'
    def fetch(url):
        return pgn if '/pgn/' in url else json.dumps(dict(topGames=[candidate('Abcd1234')]))
    finder = service(fetch, clock=lambda: now[0])
    finder.lookup(chess.STARTING_FEN, remote=True)
    for ply in (0, 4, 8):
        text = finder.export_pgn(chess.STARTING_FEN, 'Abcd1234', ply)
        exported = chess.pgn.read_game(io.StringIO(text))
        assert len(list(exported.mainline_moves())) == ply
        assert exported.headers['Source'].endswith('/pgn/Abcd1234')
    for invalid in (-1, 3, 9):
        with pytest.raises(ValueError):
            finder.export_pgn(chess.STARTING_FEN, 'Abcd1234', invalid)
    now[0] += 300
    with pytest.raises(ValueError, match='만료'):
        finder.export_pgn(chess.STARTING_FEN, 'Abcd1234')


def test_ordered_positions_with_edits_gaps_and_shared_opening():
    finder = service()
    opera = next(g for g in finder.catalog if g['id'] == 'morphy-opera-1858')
    early = opera['steps'][1]['after_fen']
    later = opera['steps'][18]['after_fen']
    assert len(finder.lookup_sequence([early])['games']) == 4
    match, = finder.lookup_sequence([early, early, later])['games']
    assert (match['id'], match['match_plies']) == (opera['id'], [19])
    for out_of_order in ([later, early], [later, AFTER_RF6]):
        result = finder.lookup_sequence(out_of_order)
        assert result['games'] == [] and result['first_unmatched'] == 2


def test_later_remote_discovery_retains_distinct_games_and_repeated_endpoints():
    now = [0]
    prefix = '1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2'
    def fetch(url):
        if '/pgn/' in url:
            return '[White "' + url[-8:] + '"]\n[Result "1/2-1/2"]\n\n' + prefix
        return json.dumps(dict(topGames=[candidate('Remote01'), candidate('Remote02')]))
    finder = service(fetch, clock=lambda: now[0])
    board = chess.Board()
    board.push_san('Nf3')
    fens = [board.fen(), chess.STARTING_FEN]
    assert not finder.lookup_sequence(fens)['games']
    data = finder.lookup_sequence(fens, remote_frame=1)
    assert data['remote_statuses'] == ['not_requested', 'available']
    assert [(g['id'], g['match_plies']) for g in data['games']] == [
        ('Remote01', [4, 8]), ('Remote02', [4, 8])]
    assert finder.sequence_game(fens, 'Remote02')['white']['name'] == 'Remote02'
    now[0] += 301
    with pytest.raises(ValueError):
        finder.sequence_game(fens, 'Remote02')


def test_sequence_api_checks_scene_order_on_download_and_old_jobs():
    app = FastAPI()
    app.state.config = SimpleNamespace(engine_path=None)
    store = install_explanation_api(app, lambda _: None, Path(__file__).parents[1]/'image2pgn/web')
    finder = app.state.master_games
    game = finder.catalog[0]
    fens = [step['after_fen'] for step in game['steps'][8:20:10]]
    path = '/api/explanations/test/scenes'
    download = path + '/' + game['id'] + '/pgn'
    with TestClient(app) as client:
        assert client.post(path, json={'frames': fens}).status_code == 401
        client.headers['x-chesslens-token'] = store.token
        store.jobs['test'] = dict(status='ready', result=dict(fen=fens[0]), _cancel=threading.Event())
        def submit(url, frames, **extra):
            return client.post(url, json=dict(frames=frames, **extra))
        result = submit(path, fens).json()
        assert result['games'][0]['match_plies'] == [19]
        for ply, expected in [(None, len(game['steps'])), (19, 19)]:
            reply = submit(download, fens, through_ply=ply)
            parsed = chess.pgn.read_game(io.StringIO(reply.text))
            assert reply.status_code == 200 and parsed.end().ply() == expected
        assert submit(download, fens, through_ply=9).status_code == 422
        assert submit(download, fens[::-1]).status_code == 422
        assert submit(path, fens, remote_frame=2).status_code == 422
        assert submit(path, ['invalid']).status_code == 422
        assert submit(path, fens*9).status_code == 422
        store.jobs['test']['status'] = 'cancelled'
        assert submit(download, fens).status_code == 409


def test_unavailable_masters_keeps_local_sequence_and_source_status():
    def limited(_):
        raise RemoteFailure('rate_limited', '잠시 뒤 다시 조회하세요.')
    finder = service(limited)
    game = finder.catalog[0]
    fens = [game['steps'][n]['after_fen'] for n in (15, 36)]
    result = finder.lookup_sequence(fens, remote_frame=1)
    assert result['remote_statuses'] == ['not_requested', 'rate_limited']
    assert result['games'][0]['match_plies'] == [37]
