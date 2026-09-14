from pathlib import Path
from types import SimpleNamespace
import numpy as np
import cv2
import pytest
from image2pgn import visualize


def analysis(moves=()):
    return SimpleNamespace(moves=moves,side_to_move='White',evaluation='test',summary='Alignment test',threats=[])


def test_shared_board_never_reloads_source_and_is_not_mutated(tmp_path,monkeypatch):
    board=np.random.default_rng(4).integers(0,256,(640,640,3),dtype=np.uint8);before=board.copy()
    def forbidden(*a,**kw):raise AssertionError('Source must not be loaded or detected again')
    monkeypatch.setattr(visualize,'load_image',forbidden);monkeypatch.setattr(visualize,'warp_board',forbidden)
    out=tmp_path/'overlay.png';visualize.save_analysis_overlay(Path('missing.png'),analysis(),'white',out,board_image=board)
    assert np.array_equal(cv2.imread(str(out))[:,:640],visualize._draw_grid(before))
    assert np.array_equal(board,before)


@pytest.mark.parametrize('orientation,start,end',[('white',(360,520),(360,360)),('black',(280,120),(280,280))])
def test_arrows_use_recognition_orientation(monkeypatch,orientation,start,end):
    captured=[]
    monkeypatch.setattr(cv2,'arrowedLine',lambda image,a,b,*args,**kwargs:captured.append((a,b)))
    visualize._draw_candidate_moves(np.zeros((640,640,3),np.uint8),analysis([SimpleNamespace(move_uci='e2e4')]),orientation)
    assert captured==[(start,end)]


def test_cli_passes_retained_board(tmp_path,monkeypatch):
    from image2pgn import cli
    import sys
    board=np.zeros((640,640,3),np.uint8);received={}
    def recognize(**kwargs):
        assert kwargs['retain_board_image'] is True
        assert kwargs['board_corners']==Path('corners.json')
        return SimpleNamespace(placement='8/8/8/8/8/8/8/8',orientation='black',board_image=board)
    monkeypatch.setattr(cli,'recognize_fen_cnn_result',recognize)
    monkeypatch.setattr(cli,'analyze_fen',lambda **kwargs:analysis())
    monkeypatch.setattr(cli,'format_analysis',lambda result:'test')
    monkeypatch.setattr(cli,'save_analysis_overlay',lambda **kwargs:received.update(kwargs))
    monkeypatch.setattr(sys,'argv',['image2pgn','analyze-image','--image','source.png','--model','m.pt','--board-corners','corners.json','--visual-out',str(tmp_path/'x.png')])
    cli.main();assert received['board_image'] is board;assert received['orientation']=='black'
