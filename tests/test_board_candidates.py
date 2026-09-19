import numpy as np
import pytest

from image2pgn.board_candidates import bounds_iou, find_board_candidates


def add_board(image, x, y, cell, invert=False):
    for r in range(8):
        for c in range(8):
            image[y+r*cell:y+(r+1)*cell, x+c*cell:x+(c+1)*cell] = 210 if ((r+c)%2 == invert) else 80
    return (x, y, cell*8, cell*8)


@pytest.mark.parametrize("invert", [False, True])
def test_small_board_with_large_ui_and_both_polarities(invert):
    image = np.full((400, 800, 3), 35, np.uint8)
    image[10:380, 400:790] = 150
    expected = add_board(image, 43, 71, 16, invert)
    found = find_board_candidates(image)
    assert any(bounds_iou(c.bounds, expected) >= 0.95 for c in found[:5])
    assert len(found) <= 20
    assert all(c.bounds[0] >= 0 and c.bounds[1] >= 0 and c.bounds[0]+c.bounds[2] <= 800 and c.bounds[1]+c.bounds[3] <= 400 for c in found)


def test_multiple_board_locations_survive():
    image = np.full((400, 800, 3), 35, np.uint8)
    expected = [add_board(image, 15, 23, 16), add_board(image, 410, 110, 24)]
    found = find_board_candidates(image)
    assert all(any(bounds_iou(c.bounds, box) >= 0.95 for c in found[:5]) for box in expected)


def test_no_evidence_and_small_input():
    assert find_board_candidates(np.full((200, 300, 3), 100, np.uint8)) == []
    assert find_board_candidates(np.zeros((50, 80, 3), np.uint8)) == []
    with pytest.raises(ValueError):
        find_board_candidates(np.zeros((100, 100, 3), np.uint8), max_candidates=0)
    with pytest.raises(ValueError):
        find_board_candidates(np.zeros((100, 100, 3), np.uint8), search_step=0)


def test_coarse_mode_skips_local_refinement(monkeypatch):
    image=np.full((400,800,3),35,np.uint8)
    expected=add_board(image,43,71,16)
    monkeypatch.setattr('image2pgn.board_candidates._refine',lambda *args,**kwargs:pytest.fail('unexpected refinement'))
    found=find_board_candidates(image,refine=False)
    assert any(bounds_iou(candidate.bounds,expected)>=.90 for candidate in found[:5])
