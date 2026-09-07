import sys
from pathlib import Path
import pytest
torch=pytest.importorskip('torch')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'infra'))
from compare_heads import HeadComparison,partial_loss


@pytest.mark.parametrize('arch',['joint','factorized'])
def test_distribution_and_empty_loss(arch):
    torch.manual_seed(1)
    model=HeadComparison(arch).eval()
    p=model(torch.randn(3,3,96,96))
    assert p.shape==(3,13)
    assert torch.allclose(p.exp().sum(1),torch.ones(3),atol=1e-6)
    loss=partial_loss(p,torch.zeros(3,dtype=torch.long),torch.ones(3,dtype=torch.bool))
    loss.backward()
    assert torch.isfinite(loss)


@pytest.mark.parametrize('arch',['joint','factorized'])
def test_unknown_side_label_flip_invariance(arch):
    model=HeadComparison(arch).eval()
    p=model(torch.randn(4,3,96,96))
    known=torch.zeros(4,dtype=torch.bool)
    y=torch.tensor([1,2,3,6])
    assert torch.allclose(partial_loss(p,y,known),partial_loss(p,y+6,known),atol=1e-6)


def test_unknown_side_does_not_train_side_head():
    model=HeadComparison('factorized').eval()
    loss=partial_loss(model(torch.randn(3,3,96,96)),torch.tensor([1,7,3]),torch.zeros(3,dtype=torch.bool))
    loss.backward()
    assert model.side.weight.grad.abs().max()<1e-6
    assert model.kind.weight.grad.abs().max()>1e-6


def test_invalid_unknown_empty_rejected():
    p=torch.zeros(1,13).log_softmax(1)
    with pytest.raises(ValueError):partial_loss(p,torch.tensor([0]),torch.tensor([False]))
