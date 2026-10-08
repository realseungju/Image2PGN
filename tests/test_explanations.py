import threading
import time
from pathlib import Path
from types import SimpleNamespace

import chess
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from image2pgn.explanations import capture_options, checked_board, prepare_position, replay_steps, explain
from image2pgn.explanation_api import install_explanation_api
from fastapi import FastAPI

FEN = '5r1k/6pp/7N/8/8/1Q6/8/K7 w - - 0 1'
AFTER_RF6 = 'r3qr1k/pp3pbp/2pn1R2/7Q/3pP3/2NB3P/PPP3P1/R5K1 b - - 1 19'


def wait_job(client, jid, status):
    for _ in range(100):
        job = client.get('/api/explanations/'+jid).json()
        if job['status'] == status:
            return job
        time.sleep(.01)
    raise AssertionError(job)


def client_for(analyser=None, recognition=None):
    app = FastAPI()
    app.state.config = SimpleNamespace(engine_path=None)
    def recognize(_):
        if isinstance(recognition, Exception):
            raise recognition
        return recognition or dict(placement=FEN.split()[0], review_squares=['h6'])
    options = {'analyser': analyser} if analyser else {'analyser': lambda *a, **kw: {'brief_en': 'Verified, sir.'}}
    install_explanation_api(app, recognize, Path(__file__).parents[1]/'image2pgn/web', **options)
    client = TestClient(app)
    client.headers['x-chesslens-token'] = client.get('/api/explanations/session').json()['token']
    return client


def png():
    return cv2.imencode('.png', np.zeros((20, 20, 3), dtype=np.uint8))[1].tobytes()


def test_verified_capture_and_mate_facts():
    board = checked_board(FEN)
    moves = [chess.Move.from_uci(x) for x in ['b3g8', 'f8g8', 'h6f7']]
    steps = replay_steps(board, moves, chess.WHITE, 'test')
    assert steps[1]['facts'][1]['piece'] == 'Q'
    assert steps[1]['material_delta'] == -9
    assert steps[-1]['facts'][-1]['kind'] == 'checkmate'
    assert chess.Board(steps[-1]['after_fen']).is_checkmate()
    with pytest.raises(ValueError):
        replay_steps(board, [chess.Move.from_uci('h6h8')], chess.WHITE, 'bad')


def test_en_passant_and_promotion_capture_facts():
    ep = checked_board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
    steps = replay_steps(ep, [chess.Move.from_uci('e5d6')], chess.WHITE, 'ep')
    assert steps[0]['facts'][1]['square'] == 'd5'
    assert chess.Board(steps[0]['after_fen']).piece_at(chess.D5) is None
    promotion = checked_board('4k3/P7/8/8/8/8/8/4K3 w - - 0 1')
    promoted = replay_steps(promotion, [chess.Move.from_uci('a7a8q')], chess.WHITE, 'p')
    assert chess.Board(promoted[0]['after_fen']).piece_at(chess.A8).piece_type == chess.QUEEN


def test_before_position_must_match_and_invalid_boards_rejected():
    after = checked_board(FEN)
    after.push_uci('b3g8')
    assert prepare_position(after.fen(), FEN, 'b3g8')[1].uci() == 'b3g8'
    with pytest.raises(ValueError):
        prepare_position(FEN, FEN, 'b3g8')
    with pytest.raises(ValueError):
        checked_board('8/8/8/8/8/8/8/8 w - - 0 1')


def test_castling_moves_both_king_and_rook():
    board = checked_board('4k3/8/8/8/8/8/8/4K2R w K - 0 1')
    step = replay_steps(board, [chess.Move.from_uci('e1g1')], chess.WHITE, 'castle')[0]
    assert step['animation_moves'][1] == dict(from_square='h1', to_square='f1')
    after = chess.Board(step['after_fen'])
    assert after.piece_at(chess.G1).piece_type == chess.KING
    assert after.piece_at(chess.F1).piece_type == chess.ROOK


def test_auth_origin_and_remote_host_rejected():
    with client_for() as client:
        assert client.get('/api/explanations/missing', headers={'x-chesslens-token': ''}).status_code == 401
        assert client.get('/api/explanations/session', headers={'origin': 'https://evil.example'}).status_code == 403
        assert client.get('/api/explanations/session', headers={'host': 'evil.example'}).status_code == 403
        assert client.get('/api/explanations/session', headers={'sec-fetch-site': 'same-site'}).status_code == 403


def test_upload_review_revision_and_duplicate_contract():
    with client_for() as client:
        body = dict(request_id='image-1', question='왜 좋은 수인가요?')
        first = client.post('/api/explanations', data=body, files={'image': ('x.png', png(), 'image/png')})
        assert first.status_code == 200
        jid = first.json()['job_id']
        review = wait_job(client, jid, 'needs_input')
        assert review['needs_review'] and review['result'] is None
        duplicate = client.post('/api/explanations', data=body, files={'image': ('x.png', png(), 'image/png')}).json()
        assert duplicate['job_id'] == jid
        assert client.post('/api/explanations', data={**body, 'question': '다른 질문'}, files={'image': ('x.png', png(), 'image/png')}).status_code == 409
        answer = dict(revision=review['revision'], question_id='confirm-position', fen=FEN, confirmed_history=True)
        assert client.post(f'/api/explanations/{jid}/answers', json={**answer, 'revision': 0}).status_code == 409
        assert client.post(f'/api/explanations/{jid}/answers', json={**answer, 'confirmed_history': False}).status_code == 400
        assert client.post(f'/api/explanations/{jid}/answers', json=answer).status_code == 200
        assert wait_job(client, jid, 'ready')['result']['brief_en'] == 'Verified, sir.'
        cancelled = client.post(f'/api/explanations/{jid}/cancel').json()
        assert cancelled['result'] and cancelled['recognition'] is None
        assert client.post(f'/api/explanations/{jid}/cancel').json()['revision'] == cancelled['revision']


def test_cancel_drops_late_analysis_and_cleans_crop():
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return {'brief_en': 'Must not publish'}
    with client_for(slow) as client:
        jid = client.post('/api/explanations', data=dict(request_id='slow', fen=FEN, confirmed_history='true')).json()['job_id']
        assert entered.wait(2)
        job = client.post(f'/api/explanations/{jid}/cancel').json()
        release.set()
        time.sleep(.04)
        late = client.get(f'/api/explanations/{jid}').json()
        assert late['status'] == 'cancelled' and late['result'] is None and late['revision'] == job['revision']


def test_bad_recognition_can_be_reviewed_manually():
    with client_for(recognition=ValueError('no board')) as client:
        jid = client.post('/api/explanations', data={'request_id': 'blur'}, files={'image': ('x.png', png(), 'image/png')}).json()['job_id']
        job = wait_job(client, jid, 'needs_input')
        assert 'no board' in job['recognition_error'] and job['result'] is None
        assert client.post('/api/explanations', data={'request_id': 'broken'}, files={'image': ('x.png', b'garbage', 'image/png')}).status_code == 422
        assert client.post('/api/explanations', data={'request_id': 'txt'}, files={'image': ('x.txt', b'garbage', 'text/plain')}).status_code == 415


def test_real_stockfish_mate_and_fixed_viewpoint():
    engine = Path.home()/'Documents/stockfish/stockfish-windows-x86-64-avx2.exe'
    if not engine.exists():
        pytest.skip('Local Stockfish integration fixture')
    result = explain(FEN, engine, target_uci='b3g8', movetime_ms=200)
    assert result['engine']['viewpoint'] == 'white'
    assert result['branches'][1]['mate'] == 2
    capture = result['branches'][2]
    assert not capture['conditional']
    assert [s['uci'] for s in capture['steps']] == ['b3g8', 'f8g8', 'h6f7']
    assert len(result['brief_en'].split()) <= 35


def test_current_capture_options_respect_turn_and_pins():
    options = capture_options(AFTER_RF6)
    assert options['turn'] == 'black' and options['stage'] == 'current'
    assert {m['uci'] for m in options['captures']} == {'g7f6', 'd4c3', 'd6e4', 'e8e4'}
    white = capture_options(AFTER_RF6.replace(' b ', ' w '))
    assert 'g7f6' not in {m['uci'] for m in white['captures']}
    pinned = capture_options('4k3/4b3/8/8/7Q/8/8/4R1K1 b - - 0 1')
    assert 'e7h4' not in {m['uci'] for m in pinned['captures']}
    with pytest.raises(ValueError):
        capture_options(AFTER_RF6, capture_uci='g7h8')


def test_capture_options_special_moves_and_target_stage():
    ep = capture_options('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
    assert ep['captures'][0]['captured_piece'] == 'p'
    promotion = capture_options('1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1')
    assert {m['uci'] for m in promotion['captures']} == {'a7b8q', 'a7b8r', 'a7b8b', 'a7b8n'}
    after_target = capture_options(FEN, target_uci='b3g8')
    assert after_target['stage'] == 'after_target'
    assert after_target['captures'][0]['uci'] == 'f8g8'


def test_capture_preview_auth_and_selected_capture_validation():
    received = {}
    def analyse(*args, **kwargs):
        received.update(kwargs)
        return {'brief_en':'Verified, sir.'}
    with client_for(analyse, recognition=dict(placement=AFTER_RF6.split()[0],review_squares=[])) as client:
        path='/api/explanations/capture-options'
        assert client.post(path,json={'fen':AFTER_RF6},headers={'x-chesslens-token':''}).status_code == 401
        assert client.post(path,json={'fen':AFTER_RF6.replace(' b ', ' ? ')}).status_code == 422
        assert {c['uci'] for c in client.post(path,json={'fen':AFTER_RF6}).json()['captures']} == {'g7f6', 'd4c3', 'd6e4', 'e8e4'}
        jid=client.post('/api/explanations',data={'request_id':'black-review'},files={'image':('board.png',png(),'image/png')}).json()['job_id']
        state=wait_job(client,jid,'needs_input')
        answer=dict(revision=state['revision'],question_id='confirm-position',fen=AFTER_RF6,confirmed_history=True,capture_uci='g7f6')
        assert client.post('/api/explanations/'+jid+'/answers',json={**answer,'capture_uci':'g7h8'}).status_code == 422
        assert client.post('/api/explanations/'+jid+'/answers',json=answer).status_code == 200
        ready=wait_job(client,jid,'ready')
        assert ready['capture_uci']=='g7f6' and ready['proposed_fen']==AFTER_RF6
        assert received['capture_uci']=='g7f6'


def test_capture_choice_participates_in_request_identity():
    with client_for() as client:
        body=dict(request_id='capture-identity',fen=AFTER_RF6,confirmed_history='true',capture_uci='g7f6')
        assert client.post('/api/explanations',data=body).status_code == 200
        assert client.post('/api/explanations',data={**body,'capture_uci':'d4c3'}).status_code == 409


def test_current_black_capture_compares_with_defence_without_target():
    engine=Path.home()/'Documents/stockfish/stockfish-windows-x86-64-avx2.exe'
    if not engine.exists():
        pytest.skip('Local Stockfish integration fixture')
    result=explain(AFTER_RF6,engine,capture_uci='g7f6',movetime_ms=500)
    assert result['engine']['viewpoint']=='black'
    best,capture=result['branches']
    assert best['steps'][0]['san']=='Kg8'
    assert capture['steps'][0]['san']=='Bxf6'
    assert capture['comparison_stage']=='current'
    assert capture['score_fen']==result['root_fen']==AFTER_RF6
    assert capture['mate']==-4 and capture['conditional']
    assert capture['steps'][-1]['facts'][-1]['kind']=='checkmate'
    assert 'White' in result['brief_en'] and len(result['brief_en'].split())<=35


def test_no_capture_reports_reason_instead_of_hiding_option():
    result=explain('4k3/8/8/8/8/8/8/4K3 w - - 0 1',None)
    assert not result['capture_comparison']['available']
    assert result['capture_comparison']['reason_ko']


def test_recommended_move_capture_is_an_explicit_future_variation():
    engine=Path.home()/'Documents/stockfish/stockfish-windows-x86-64-avx2.exe'
    if not engine.exists():
        pytest.skip('Local Stockfish integration fixture')
    assert not capture_options(FEN)['captures']
    result=explain(FEN,engine,movetime_ms=200)
    capture=next(b for b in result['branches'] if b['kind']=='capture')
    assert capture['comparison_stage']=='after_recommendation'
    assert capture['score_fen']!=result['root_fen']
    assert [s['san'] for s in capture['steps']]==['Qg8+','Rxg8','Nf7#']
