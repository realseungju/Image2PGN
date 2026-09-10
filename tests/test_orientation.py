import pytest
from image2pgn.orientation import coordinate_decision, resolve_orientation
from image2pgn.fen import compress_board, expand_placement, orient_board

def reverse(placement):
    return compress_board(orient_board(expand_placement(placement), 'black'))

@pytest.mark.parametrize('axis,sequence,direction', [('file','abcdefgh','white'),('rank','87654321','white'),('file','hgfedcba','black'),('rank','12345678','black')])
def test_consistent_coordinates(axis,sequence,direction):
    observations=[{'axis':axis,'index':i,'text':sequence[i]} for i in (1,3,6)]
    assert coordinate_decision(observations)[0]==direction

def test_duplicates_do_not_count_as_multiple_coordinates():
    assert coordinate_decision([{'axis':'rank','index':0,'text':'8'}]*4)[0] is None

def test_coordinate_conflict_requires_fallback():
    observations=[{'axis':'file','index':i,'text':'abcdefgh'[i]} for i in range(3)]
    observations.append({'axis':'rank','index':0,'text':'1'})
    assert coordinate_decision(observations)==(None,'conflicting_coordinates')

def test_pawnless_position_is_uncertain():
    p='7k/8/8/8/8/8/8/K7'
    assert resolve_orientation(p,reverse(p),observations=[])['status']=='uncertain'

def test_starting_position_and_rotated_position():
    p='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
    assert resolve_orientation(p,reverse(p),observations=[])['orientation']=='white'
    assert resolve_orientation(reverse(p),p,observations=[])['orientation']=='black'

def test_screenshot_five_position_only_regression():
    p='K1R1nr2/P7/1Pq5/3P4/2Np4/p7/kpQ5/8'
    result=resolve_orientation(p,reverse(p),observations=[])
    assert result['orientation']=='black'
    assert result['source']=='position'

def test_coordinates_override_position_prior():
    p='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR'
    observations=[{'axis':'rank','index':i,'text':str(i+1)} for i in range(3)]
    result=resolve_orientation(p,reverse(p),observations=observations)
    assert result['orientation']=='black'
    assert result['status']=='coordinate_supported'

def test_ocr_unavailable_falls_back(monkeypatch):
    monkeypatch.setattr('image2pgn.orientation.read_coordinates',lambda image:([], 'unavailable'))
    p='7k/8/8/8/8/8/8/K7'
    result=resolve_orientation(p,reverse(p),board_image=object())
    assert result['source']=='position'
    assert result['ocr_error']=='unavailable'
