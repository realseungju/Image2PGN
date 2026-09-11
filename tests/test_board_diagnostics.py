import json
import numpy as np
import pytest
from image2pgn import board


def test_grid_candidate_records_original_coordinates(monkeypatch):
    image=np.arange(100*120*3,dtype=np.uint8).reshape(100,120,3)
    monkeypatch.setattr(board,'find_screenshot_board',lambda image:(10,20,60,64))
    result=board.warp_board_result(image,detector='grid')
    assert result.details['method']=='grid'
    assert result.details['bounds']==[10,20,60,64]
    assert result.details['status']=='candidate'
    assert not result.details['requires_review']
    assert np.array_equal(result.image,board.warp_board(image,detector='grid'))
    json.dumps(result.details)


@pytest.mark.parametrize('detector,reason',[('grid','grid_and_contour_not_found'),('legacy','contour_not_found')])
def test_center_fallback_is_not_silent(monkeypatch,detector,reason):
    image=np.full((100,60,3),127,np.uint8)
    monkeypatch.setattr(board,'find_screenshot_board',lambda image:None)
    monkeypatch.setattr(board,'_find_board_contour',lambda image:None)
    result=board.warp_board_result(image,detector=detector)
    assert result.details['method']=='center'
    assert result.details['bounds']==[0,20,60,60]
    assert result.details['requires_review']
    assert result.details['fallback_reason']==reason
    assert np.all(result.image==127)


def test_contour_fallback_preserves_ordered_corners(monkeypatch):
    image=np.zeros((100,100,3),np.uint8)
    points=np.array([[[10,10]],[[80,10]],[[80,80]],[[10,80]]],np.int32)
    monkeypatch.setattr(board,'find_screenshot_board',lambda image:None)
    monkeypatch.setattr(board,'_find_board_contour',lambda image:points)
    result=board.warp_board_result(image,detector='grid')
    assert result.details['method']=='contour'
    assert result.details['fallback_reason']=='grid_pattern_not_found'
    assert result.details['corners']==points.reshape(4,2).tolist()
    assert result.details['requires_review']


def test_blank_input_reaches_review_required_center():
    result=board.warp_board_result(np.full((240,160,3),100,np.uint8),detector='grid')
    assert result.details['method']=='center'
    assert result.details['requires_review']
