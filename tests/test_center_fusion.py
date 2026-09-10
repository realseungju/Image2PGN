import torch
from torch import nn
from image2pgn.cnn import PieceCnn
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"infra"))
from center_fusion import Fusion,brightness

def test_initial_predictions_preserved():
    base=PieceCnn(13,nn).eval();x=torch.rand(2,3,96,96)
    expected=base(x).detach();model=Fusion(base,True).eval()
    torch.testing.assert_close(model(x),expected)

def test_center_and_border_are_separate():
    x=torch.zeros(2,3,96,96);x[0,:,29:67,29:67]=1;x[1]=1
    torch.testing.assert_close(brightness(x),torch.tensor([[1.,1.,0.,1.,1.],[1.,1.,1.,0.,0.]]))

def test_extra_weights_receive_gradient():
    model=Fusion(PieceCnn(13,nn),True);x=torch.rand(2,3,96,96)
    nn.functional.cross_entropy(model(x),torch.tensor([1,7])).backward()
    assert model.head.weight.grad[:,192:].abs().sum()>0

