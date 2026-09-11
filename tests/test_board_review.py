import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from image2pgn.board_review import validate_corners, corrected_board, load_correction, image_identity, build_review


def test_identity_warp_preserves_pixels():
    image=np.random.default_rng(17).integers(0,256,(80,80,3),dtype=np.uint8)
    assert np.array_equal(corrected_board(image,[[0,0],[79,0],[79,79],[0,79]],80),image)


@pytest.mark.parametrize('points',[
 [[0,0],[79,79],[79,0],[0,79]],
 [[0,0],[79,0],[79,0],[0,79]],
 [[-1,0],[79,0],[79,79],[0,79]],
 [[0,0],[80,0],[79,79],[0,79]],
 [[0,0],[float('nan'),0],[79,79],[0,79]],
 [[79,79],[0,79],[0,0],[79,0]],
 [[0,0],[2,0],[2,2],[0,2]],
])
def test_invalid_corners_rejected(points):
    with pytest.raises(ValueError):validate_corners(points,80,80)


def test_perspective_boundary_maps_to_square():
    source=np.zeros((140,160,3),np.uint8)
    corners=np.array([[20,10],[140,20],[130,120],[10,110]],np.float32)
    cv2.fillConvexPoly(source,corners.astype(np.int32),(180,180,180))
    result=corrected_board(source,corners,80)
    assert result.shape==(80,80,3)
    assert np.mean(result[5:-5,5:-5])==180


def correction_fixture(tmp_path):
    image=np.full((80,80,3),127,np.uint8);path=tmp_path/'source.png';cv2.imwrite(str(path),image)
    document={'schema':'chess-board-corners-v1','image':image_identity(path,image),
              'corners':[[0,0],[79,0],[79,79],[0,79]],'reviewed':True,'incomplete':False}
    return image,path,document


def test_correction_requires_same_source_and_confirmation(tmp_path):
    image,path,document=correction_fixture(tmp_path);saved=tmp_path/'corners.json'
    saved.write_text(json.dumps(document));assert load_correction(saved,path,image).shape==(4,2)
    for field,value in [('reviewed',False),('incomplete',True),('image',{'sha256':'wrong','width':80,'height':80})]:
        changed={**document,field:value};saved.write_text(json.dumps(changed))
        with pytest.raises(ValueError):load_correction(saved,path,image)


def test_review_embeds_image_and_escapes_filename(tmp_path):
    image,path,_=correction_fixture(tmp_path);page=tmp_path/'review.html';build_review(path,page)
    html=page.read_text(encoding='utf-8')
    assert 'data:image/png;base64,' in html
    assert '/*PAYLOAD*/' not in html and '/*GEOMETRY*/' not in html
    assert 'chess-board-corners-v1' in html
    assert 'http://' not in html and 'https://' not in html


def test_cli_manual_option_and_review_command():
    from image2pgn.cli import build_parser
    parser=build_parser();args=parser.parse_args(['board-review','--image','x.png','--out','review.html'])
    assert args.out==Path('review.html')
    for command in ['fen-cnn','analyze-image']:
        args=parser.parse_args([command,'--image','x.png','--model','m.pt','--board-corners','c.json'])
        assert args.board_corners==Path('c.json')
