import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from image2pgn.lichess_credentials import TokenStore, protect, valid_token
from image2pgn.master_games import MasterGames, RemoteFailure
from image2pgn.explanation_api import install_explanation_api


def finder(tmp_path,monkeypatch):
    monkeypatch.delenv('CHESSLENS_LICHESS_TOKEN',raising=False)
    return MasterGames(credentials=TokenStore(tmp_path/'test-token.dpapi'))


def test_default_connection_needs_auth_without_network(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch)
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:pytest.fail('Should not request without a token'))
    result=provider.lookup('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',remote=True)
    assert result['remote_status']=='auth_required' and result['games']
    assert not provider.connection_status()['configured']


def test_verified_token_updates_memory_and_invalidates_failure_cache(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch)
    provider.cache['old']=(9999,dict(games=[],remote_status='auth_required'))
    provider.blocked_until=9999
    def fetch(url,token=None):
        assert token=='fake_valid_token' and url.startswith('https://explorer.lichess.org/masters?')
        return json.dumps(dict(topGames=[]))
    monkeypatch.setattr(provider,'_fetch',fetch)
    status=provider.configure('connect','fake_valid_token')
    assert status['verified'] and status['source']=='session'
    assert 'fake_valid_token' not in json.dumps(status)
    assert not provider.cache and provider.blocked_until==0 and not provider.credentials.path.exists()
    assert provider.configure('test')['verified']
    assert not provider.configure('disconnect')['configured']


def test_invalid_new_token_does_not_replace_working_token(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch)
    provider.credentials.set('old_token')
    def denied(*args,**kwargs):raise RemoteFailure('auth_required','발급 토큰을 확인하세요.')
    monkeypatch.setattr(provider,'_fetch',denied)
    with pytest.raises(RemoteFailure):provider.configure('connect','new_token')
    assert provider.credentials.token()=='old_token'


def test_rate_limit_cannot_be_bypassed_by_reconnect_or_disconnect(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch)
    provider.blocked_status='rate_limited';provider.blocked_until=provider.clock()+60
    with pytest.raises(RemoteFailure):provider.configure('connect','fake_token')
    provider.configure('disconnect')
    with pytest.raises(RemoteFailure):provider.configure('connect','fake_token')


def test_busy_does_not_change_credentials(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch);provider.lock.acquire()
    try:
        with pytest.raises(RemoteFailure):provider.configure('connect','fake_token')
        assert not provider.credentials.token()
    finally:provider.lock.release()


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_real_dpapi_persistence_is_encrypted_and_user_readable(tmp_path,monkeypatch):
    monkeypatch.delenv('CHESSLENS_LICHESS_TOKEN',raising=False)
    path=tmp_path/'test-token.dpapi'
    first=TokenStore(path);first.set('only_a_fake_test_token',remember=True)
    assert b'only_a_fake_test_token' not in path.read_bytes()
    second=TokenStore(path)
    assert second.token()=='only_a_fake_test_token' and second.source=='encrypted'
    second.clear()
    assert not path.exists() and not second.token()


def test_corrupted_saved_token_and_invalid_shapes(tmp_path,monkeypatch):
    monkeypatch.delenv('CHESSLENS_LICHESS_TOKEN',raising=False)
    path=tmp_path/'bad.dpapi';path.write_bytes(b'not encrypted')
    store=TokenStore(path)
    assert not store.token() and store.status()['storage_error']
    for token in ('has spaces','line\nbreak',3,'x'*4097):
        assert not valid_token(token)
    assert valid_token('x'*512)


def test_no_secret_in_api_response_or_validation_errors(tmp_path,monkeypatch):
    app=FastAPI();app.state.config=SimpleNamespace(engine_path=None)
    install_explanation_api(app,lambda _:None,Path(__file__).parents[1]/'image2pgn/web')
    provider=finder(tmp_path,monkeypatch);app.state.master_games=provider
    monkeypatch.setattr(provider,'_fetch',lambda *args,**kwargs:json.dumps(dict(topGames=[])))
    with TestClient(app) as client:
        url='/api/explanations/master-connection'
        assert client.get(url).status_code==401
        client.headers['x-chesslens-token']=app.state.explanations.token
        secret='private_fake_token'
        response=client.post(url,json=dict(action='connect',token=secret))
        assert response.status_code==200 and response.json()['verified'] and secret not in response.text
        assert response.headers['cache-control']=='no-store'
        for body in [dict(action='connect',token=[secret]),dict(action='connect',token=secret,remember=secret),dict(action='unknown',token=secret),dict(action=['bad'],token=secret),dict(action='connect',token='x'*9000)]:
            response=client.post(url,json=body)
            assert response.status_code in (400,413) and secret not in response.text
        response=client.post(url,json=dict(action='disconnect'),headers={'origin':'https://evil.example'})
        assert response.status_code==403 and provider.connection_status()['configured']
        assert client.post(url,json=dict(action='disconnect')).json()['configured'] is False


def test_auth_and_timeout_messages_do_not_include_token(tmp_path,monkeypatch):
    provider=finder(tmp_path,monkeypatch)
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,*args,**kwargs):raise httpx.ReadTimeout('private_fake_token')
    monkeypatch.setattr(httpx,'Client',Client)
    with pytest.raises(RemoteFailure) as exc:provider._fetch('https://explorer.lichess.org/masters',token='private_fake_token')
    assert exc.value.status=='unavailable' and 'private_fake_token' not in str(exc.value)
