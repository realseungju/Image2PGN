"""Verified historical PGNs and a bounded, masters-only position lookup."""
from __future__ import annotations

from collections import OrderedDict
import io
import json
from pathlib import Path
import re
import threading
import time

import chess
import chess.pgn
import httpx

from .explanations import checked_board, replay_steps
from .lichess_credentials import TokenStore, valid_token

MASTERS_URL = 'https://explorer.lichess.org/masters'
MIN_RATING = 2400
MAX_BYTES = 128 * 1024
MAX_PLIES = 600
MAX_REMOTE_GAMES = 3
POLICY = '유명 경기 목록 + 양쪽 선수 모두 레이팅 2400 이상인 마스터 경기만 검색합니다.'


def position_key(board):
    # Counters do not identify a position. A non-capturable EP target is irrelevant.
    return ' '.join(board.fen(en_passant='legal').split()[:4])


def rating(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value))
        return number if 100 <= number <= 4000 else None
    except (ValueError, TypeError):
        return None


def eligible(candidate):
    if not isinstance(candidate, dict):
        return False
    return all(isinstance(candidate.get(side), dict) and
               (rating(candidate[side].get('rating')) or 0) >= MIN_RATING
               for side in ('white', 'black'))


def parse_game(pgn, game_id, *, curated=None, candidate=None):
    if len(pgn.encode('utf-8')) > MAX_BYTES:
        raise ValueError('기보가 너무 큽니다.')
    stream = io.StringIO(pgn)
    game = chess.pgn.read_game(stream)
    if not game or game.errors or chess.pgn.read_game(stream) is not None:
        raise ValueError('하나의 온전한 기보가 필요합니다.')
    if game.headers.get('Variant', 'Standard') not in ('Standard', 'Chess'):
        raise ValueError('표준 체스 기보만 지원합니다.')
    root = game.board()
    if not root.is_valid() or root.fen() != chess.STARTING_FEN:
        raise ValueError('처음부터 기록된 표준 체스 기보가 필요합니다.')
    moves = list(game.mainline_moves())
    if not moves or len(moves) > MAX_PLIES:
        raise ValueError('기보 수순 길이가 지원 범위를 벗어났습니다.')
    result = game.headers.get('Result')
    if result not in ('1-0', '0-1', '1/2-1/2'):
        raise ValueError('결과가 기록된 기보가 필요합니다.')
    # Check the entire main line, including the part before the matched position.
    steps = replay_steps(root, moves, chess.WHITE, game_id, max_plies=MAX_PLIES)
    keys = [position_key(root)] + [position_key(chess.Board(step['after_fen'])) for step in steps]
    end = chess.Board(steps[-1]['after_fen'])
    if end.is_checkmate() and result != ('0-1' if end.turn else '1-0'):
        raise ValueError('체크메이트와 기보 결과가 다릅니다.')
    players = {}
    for side in ('white', 'black'):
        name = game.headers.get(side.title(), '?')
        value = rating(game.headers.get(side.title() + 'Elo'))
        if candidate:
            # The explorer's recorded rating is the filter basis; never invent Elo.
            value = rating(candidate[side].get('rating'))
        players[side] = dict(name=name, rating=value)
    return dict(id=game_id, title_ko=(curated or {}).get('title_ko', ''),
                category='famous' if curated else 'master', **players,
                event=game.headers.get('Event', '?'), date=game.headers.get('Date', '?'),
                result=result, note_ko=(curated or {}).get('note_ko', ''),
                sources=(curated or {}).get('sources', [dict(label='Lichess Masters 원기보', url=f'{MASTERS_URL}/pgn/{game_id}')]),
                root_fen=root.fen(), steps=steps, position_keys=keys)


def match_game(game, key):
    plies = [i for i, value in enumerate(game['position_keys']) if value == key]
    if not plies:
        return None
    return {**{k: v for k, v in game.items() if k != 'position_keys'}, 'match_plies': plies}


class RemoteFailure(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class MasterGames:
    def __init__(self, *, fetch=None, clock=time.monotonic, catalog_path=None, credentials=None):
        path = catalog_path or Path(__file__).with_name('data') / 'famous_games.json'
        catalog = json.loads(path.read_text(encoding='utf-8'))
        self.catalog = [parse_game(item['pgn'], item['id'], curated=item) for item in catalog]
        self.fetch = fetch or self._fetch
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.blocked_until = 0
        self.blocked_status = 'unavailable'
        self.blocked_message = ''
        self.credentials = credentials or TokenStore()
        self.connection_verified = False

    def resolve_game(self, fen, game_id):
        """Only allow games associated with the job's confirmed position."""
        key = position_key(checked_board(fen))
        for game in self.catalog:
            if game['id'] == game_id and match_game(game, key):
                return game
        if not self.lock.acquire(blocking=False):
            raise ValueError('경기 검색 중입니다. 잠시 뒤 다시 비교하세요.')
        try:
            cached = self.cache.get(key)
            for game in cached[1]['games'] if cached else []:
                if game['id'] == game_id:
                    return game
        finally:
            self.lock.release()
        raise ValueError('이 판에서 확인한 경기만 비교할 수 있습니다. 경기 목록을 다시 검색하세요.')

    def connection_status(self):
        return {**self.credentials.status(), 'verified': self.connection_verified}

    def configure(self, action, token='', remember=False):
        if not self.lock.acquire(blocking=False):
            raise RemoteFailure('busy', '검색이 진행 중입니다. 잠시 뒤 다시 연결하세요.')
        try:
            if action == 'disconnect':
                self.credentials.clear()
                self.connection_verified = False
                self.cache.clear()
                return self.connection_status()
            if self.blocked_status == 'rate_limited' and self.clock() < self.blocked_until:
                raise RemoteFailure('rate_limited', '마스터 DB 요청 제한입니다. 1분 뒤 다시 연결하세요.')
            candidate = token if action == 'connect' else self.credentials.token()
            if not valid_token(candidate):
                raise ValueError('Lichess에서 발급한 토큰을 입력하세요. 권한은 선택하지 않아도 됩니다.')
            try:
                data = json.loads(self._fetch(MASTERS_URL + '?play=e2e4&topGames=1&moves=0', token=candidate))
                if not isinstance(data, dict) or not isinstance(data.get('topGames'), list):
                    raise ValueError('마스터 DB 응답을 확인하지 못했습니다.')
            except RemoteFailure as exc:
                if exc.status == 'rate_limited':
                    self.blocked_status = exc.status
                    self.blocked_until = self.clock() + 60
                    self.blocked_message = exc.message
                raise
            if action == 'connect':
                self.credentials.set(candidate, remember=remember)
            self.connection_verified = True
            self.cache.clear()
            self.blocked_until = 0
            return self.connection_status()
        finally:
            self.lock.release()

    def _fetch(self, url, token=None):
        headers = {'Accept': 'application/json, application/x-chess-pgn', 'User-Agent': 'ChessLens/1.0'}
        token = self.credentials.token() if token is None else token
        if not token:
            raise RemoteFailure('auth_required', '외부 마스터 DB 연결이 필요합니다. 위의 마스터 DB 연결에서 Lichess 토큰을 등록하세요.')
        headers['Authorization'] = 'Bearer ' + token
        try:
            # Fixed origin, no redirects: credentials never follow a remote Location.
            with httpx.Client(timeout=5, follow_redirects=False) as client:
                with client.stream('GET', url, headers=headers) as response:
                    if response.status_code == 429:
                        raise RemoteFailure('rate_limited', '마스터 DB 요청 제한입니다. 1분 뒤 다시 검색하세요.')
                    if response.status_code in (401, 403):
                        raise RemoteFailure('auth_required', 'Lichess 토큰이 없거나 만료·폐기됐습니다. 마스터 DB 연결에서 새 토큰으로 연결하세요.')
                    if response.status_code != 200:
                        raise RemoteFailure('unavailable', f'마스터 DB 요청 실패 (HTTP {response.status_code}). 잠시 뒤 다시 검색하세요.')
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise RemoteFailure('unavailable', '마스터 DB 응답이 지원 크기를 초과했습니다.')
                    return data.decode('utf-8-sig')
        except (httpx.HTTPError, UnicodeError):
            raise RemoteFailure('unavailable', '마스터 DB 연결이 지연되거나 응답을 읽지 못했습니다.') from None

    def _remote(self, board):
        from urllib.parse import urlencode
        url = MASTERS_URL + '?' + urlencode(dict(fen=position_key(board) + ' 0 1', topGames=15, moves=0))
        data = json.loads(self.fetch(url))
        if not isinstance(data, dict) or not isinstance(data.get('topGames'), list):
            raise ValueError('Invalid explorer response')
        candidates = sorted([c for c in data['topGames'][:15] if eligible(c)],
                            key=lambda c: min(rating(c['white']['rating']), rating(c['black']['rating'])), reverse=True)
        games, seen = [], set()
        rejected = 0
        for candidate in candidates:
            game_id = candidate.get('id', '')
            if not isinstance(game_id, str) or not re.fullmatch(r'[a-zA-Z0-9]{8}', game_id) or game_id in seen:
                continue
            if len(seen) >= MAX_REMOTE_GAMES:
                break
            seen.add(game_id)
            try:
                game = parse_game(self.fetch(MASTERS_URL + '/pgn/' + game_id), game_id, candidate=candidate)
                match = match_game(game, position_key(board))
                if match:
                    games.append(match)
                else:
                    rejected += 1
            except (ValueError, TypeError, KeyError, IndexError):
                rejected += 1
        return dict(games=games, remote_status='partial' if rejected else 'available',
                    message_ko='일부 후보의 원기보·국면을 확인하지 못했습니다.' if rejected else '')

    def lookup(self, fen, remote=False):
        board = checked_board(fen)
        key = position_key(board)
        local = [match for game in self.catalog if (match := match_game(game, key))]
        base = dict(policy_ko=POLICY, min_rating=MIN_RATING, catalog_size=len(self.catalog),
                    query_fen=board.fen(), games=local, remote_status='not_requested', message_ko='',
                    caveat_ko='같은 국면의 경기 후보입니다. 원본 화면의 경기라고 확정하지 않습니다. 외부 검색은 상위 15개 후보 중 최대 3개 원기보를 확인합니다.')
        if not remote:
            return base
        # Serialize outbound traffic without making other requests wait on this lock.
        if not self.lock.acquire(blocking=False):
            return {**base, 'remote_status': 'busy', 'message_ko': '다른 마스터 검색이 진행 중입니다. 잠시 뒤 다시 검색하세요.'}
        try:
            now = self.clock()
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                remote_result = cached[1]
                self.cache.move_to_end(key)
            elif now < self.blocked_until:
                remote_result = dict(games=[], remote_status=self.blocked_status, message_ko=self.blocked_message)
            else:
                try:
                    remote_result = self._remote(board)
                    self.connection_verified = True
                except RemoteFailure as exc:
                    if exc.status == 'auth_required':
                        self.connection_verified = False
                    self.blocked_until = self.clock() + 60
                    self.blocked_status, self.blocked_message = exc.status, exc.message
                    remote_result = dict(games=[], remote_status=exc.status, message_ko=exc.message)
                except (ValueError, TypeError, KeyError, IndexError):
                    remote_result = dict(games=[], remote_status='unavailable', message_ko='마스터 DB 응답 형식을 확인하지 못했습니다.')
                self.cache[key] = (self.clock() + (300 if remote_result['remote_status'] in ('available', 'partial') else 60), remote_result)
                self.cache.move_to_end(key)
                while len(self.cache) > 32:
                    self.cache.popitem(last=False)
            # Avoid showing a catalog game a second time under its remote ID.
            fingerprints = {tuple(s['uci'] for s in g['steps']) for g in local}
            extra = [g for g in remote_result['games'] if tuple(s['uci'] for s in g['steps']) not in fingerprints]
            return {**base, **remote_result, 'games': local + extra}
        finally:
            self.lock.release()
