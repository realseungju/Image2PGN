import threading
import time
from pathlib import Path
from types import SimpleNamespace

import chess
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from image2pgn.explanations import checked_board, prepare_position, replay_steps, explain
from image2pgn.explanation_api import install_explanation_api
from fastapi import FastAPI

FEN = '5r1k/6pp/7N/8/8/1Q6/8/K7 w - - 0 1'


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
