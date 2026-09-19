import cv2
import numpy as np
import pytest
from image2pgn.board import warp_board_result
from image2pgn.board_selection import grid_evidence, select_board
from image2pgn.board_candidates import BoardCandidate
from image2pgn.cli import build_parser


def board(cell=20):
    r,c=np.indices((cell*8,cell*8));g=np.where((r//cell+c//cell)%2,80,210).astype(np.uint8)
    return np.repeat(g[:,:,None],3,axis=2)


def test_main_board_selected_over_clean_mini():
    image=np.full((420,800,3),30,np.uint8)
    image[40:360,30:350]=board(40)
    cv2.circle(image,(90,100),16,(5,5,5),-1)
    image[120:280,570:730]=board()
    bounds,details=select_board(image)
    assert bounds[2]>300
    assert not details['requires_review']


def test_equal_boards_require_review():
    image=np.full((320,600,3),30,np.uint8)
    image[50:210,30:190]=board()
    image[100:260,350:510]=board()
    bounds,details=select_board(image)
    assert bounds is not None and details['requires_review']


@pytest.mark.parametrize('kind',['blank','panel','stripes','seven_rows'])
def test_incomplete_or_non_grid_evidence_rejected(kind):
    image=board()
    if kind=='blank':image[:]=100
    elif kind=='panel':image[:]=30;image[10:150,10:150]=220
    elif kind=='stripes':image=np.repeat(image[:1],160,axis=0)
    elif kind=='seven_rows':image=cv2.resize(image[:140],(160,160))
    assert not grid_evidence(image,(0,0,160,160))['valid']


def test_fallback_is_explicit_and_default_stays_legacy():
    result=warp_board_result(np.full((160,200,3),100,np.uint8),detector='grid-v2')
    assert result.details['requires_review']
    assert result.details['fallback_reason']=='no_valid_full_grid'
    assert result.image.shape==(640,640,3)
    args=build_parser().parse_args(['fen-cnn','--image','x.png','--model','x.pt','--board-detector','grid-v2'])
    assert args.board_detector=='grid-v2'
    assert build_parser().parse_args(['fen-cnn','--image','x.png','--model','x.pt']).board_detector=='legacy'

def test_occluded_edge_preserves_strong_grid_with_review(monkeypatch):
    image=board(32)
    image[:32]=145
    monkeypatch.setattr('image2pgn.board.find_screenshot_board',lambda image:(0,0,256,256))
    bounds,details=select_board(image)
    assert bounds==(0,0,256,256)
    assert details['requires_review']
    assert details['selection_reason']=='existing_grid_occluded_edge'


@pytest.mark.parametrize('contrast,expected_resolutions',[(80,[320,320]),(34,[320,640])])
def test_refinement_is_staged_and_640_is_reserved_for_weak_color(monkeypatch,contrast,expected_resolutions):
    image=board(32)
    candidate=BoardCandidate((0,0,256,256),.8)
    calls=[]
    monkeypatch.setattr('image2pgn.board.find_screenshot_board',lambda image:None)
    monkeypatch.setattr('image2pgn.board_selection.find_board_candidates',lambda *args,**kwargs:[candidate])
    monkeypatch.setattr('image2pgn.board_selection.grid_evidence',lambda *args,**kwargs:{'parity':1.,'outer':1.,'lines':1.,'contrast':contrast,'valid':True})
    def refine(gray,candidate,**kwargs):
        calls.append(kwargs['resolution'])
        return candidate
    monkeypatch.setattr('image2pgn.board_selection._refine',refine)
    bounds,_=select_board(image)
    assert bounds==candidate.bounds
    assert calls==expected_resolutions
