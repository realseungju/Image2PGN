import hashlib
import io
import json
from pathlib import Path

import chess
import chess.pgn

from image2pgn.master_games import MasterGames, position_key

DATA=Path(__file__).parents[1]/'image2pgn/data/famous_games.json'


def test_expanded_catalog_scores_sources_and_provenance():
    raw=json.loads(DATA.read_text(encoding='utf-8'))
    finder=MasterGames()
    assert len(raw)==len(finder.catalog)==12
    assert len({g['id'] for g in finder.catalog})==12
    lines=set()
    for item,game in zip(raw,finder.catalog):
        score=tuple(step['uci'] for step in game['steps'])
        assert score not in lines;lines.add(score)
        provenance=item['provenance']
        for key in ('archive_sha256','pgn_sha256'):
            assert len(provenance[key])==64 and all(c in '0123456789abcdef' for c in provenance[key])
        assert provenance['retrieved']=='2026-10-20' and game['sources']
        assert all(source['url'].startswith('https://') for source in game['sources'])
        board=chess.Board()
        for step in game['steps']:
            assert board.fen()==step['before_fen']
            assert chess.Move.from_uci(step['uci']) in board.legal_moves
            board.push_uci(step['uci']);assert board.fen()==step['after_fen']
        if game['date']<'1970':
            assert game['white']['rating'] is None and game['black']['rating'] is None
        halfway=len(game['steps'])//2
        fen=game['steps'][halfway-1]['after_fen']
        found=next(g for g in finder.lookup(fen)['games'] if g['id']==game['id'])
        assert halfway in found['match_plies']
        assert len(found['steps'])==len(score)
        # The final recorded board remains findable even when no continuation exists.
        final=next(g for g in finder.lookup(board.fen())['games'] if g['id']==game['id'])
        assert len(score) in final['match_plies']


def test_named_scores_stop_at_the_recorded_end():
    games={g['id']:g for g in MasterGames().catalog}
    assert games['morphy-opera-1858']['steps'][-1]['san']=='Rd8#'
    assert games['rotlewi-rubinstein-1907']['steps'][-1]['san']=='Rh3'
    assert len(games['rotlewi-rubinstein-1907']['steps'])==50
    assert not chess.Board(games['rotlewi-rubinstein-1907']['steps'][-1]['after_fen']).is_checkmate()
    assert games['fischer-spassky-1972-g6']['steps'][-1]['san']=='Qf4'
    assert games['kasparov-topalov-1999']['white']['rating']==2812
    assert '전승 차이' in games['anderssen-kieseritzky-1851']['note_ko']


def test_catalog_has_no_copied_annotations_or_variations():
    for item in json.loads(DATA.read_text(encoding='utf-8')):
        game=chess.pgn.read_game(io.StringIO(item['pgn']))
        assert not game.comment and not game.errors
        assert all(not node.comment and len(node.variations)<=1 for node in game.mainline())
