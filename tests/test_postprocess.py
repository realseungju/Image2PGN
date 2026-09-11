from image2pgn.cnn import class_name_from_prediction
from image2pgn.orientation import resolve_orientation, coordinate_decision
from image2pgn.fen import expand_placement, compress_board, orient_board


def test_type_uncertainty_does_not_imply_empty():
    assert class_name_from_prediction(['empty','white_pawn','white_bishop'],1,.48,.5,empty_score=.02)=='white_pawn'


def test_occupancy_threshold_still_applies():
    assert class_name_from_prediction(['empty','white_pawn'],1,.48,.8,empty_score=.52)=='empty'


def test_top_empty_remains_empty():
    assert class_name_from_prediction(['empty','white_pawn'],0,.51,.5,empty_score=.51)=='empty'


def test_partial_coordinates_can_guide_uncertain_position():
    white='2b4k/5P2/r7/5N2/8/8/8/K1B5'
    black=compress_board(orient_board(expand_placement(white),'black'))
    observations=[{'axis':'rank','index':1,'text':'7'},{'axis':'rank','index':3,'text':'5'}]
    result=resolve_orientation(white,black,observations=observations)
    assert result['orientation']=='white'
    assert result['source']=='partial_coordinates'
    assert result['status']=='estimated'
    fallback=resolve_orientation(white,black,observations=[])
    assert fallback['orientation']=='white'
    assert fallback['status']=='uncertain'


def test_partial_conflict_and_duplicates_never_override():
    observations=[{'axis':'rank','index':1,'text':'7'},{'axis':'rank','index':3,'text':'5'},{'axis':'file','index':0,'text':'h'}]
    assert coordinate_decision(observations,minimum=2)[0] is None
    assert coordinate_decision(observations[:1]*2,minimum=2)[0] is None
