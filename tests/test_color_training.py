import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
torch=pytest.importorskip('torch')

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'infra'))
from train_color import loss_fn,metrics,color_logits,load_model
from robust_synthetic import SPLITS,render_tile


def test_empty_batch_has_finite_loss_and_gradient():
    logits=torch.randn(5,13,requires_grad=True)
    loss=loss_fn(logits,torch.zeros(5,dtype=torch.long))
    loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(logits.grad).all()


def test_color_loss_penalizes_side_without_penalizing_same_side_type():
    correct=torch.zeros(1,13);correct[0,1]=6
    same_side=correct.clone();same_side[0,1]=0;same_side[0,6]=6
    opposite=correct.clone();opposite[0,1]=0;opposite[0,7]=6
    assert torch.allclose(color_logits(correct),color_logits(same_side))
    target=torch.tensor([1])
    extra=lambda x: loss_fn(x,target)-loss_fn(x,target,0)
    assert extra(opposite)>extra(correct)


def test_error_metrics_do_not_hide_missed_pieces_in_color_denominator():
    result=metrics([1,1,1,0],[7,0,2,8])
    assert result['occupied']==3
    assert result['color_errors']==1
    assert result['type_errors']==1
    assert result['missed_pieces']==1
    assert result['false_pieces']==1


def test_design_splits_are_disjoint():
    sets=[set(s) for s in SPLITS.values()]
    assert all(not a&b for i,a in enumerate(sets) for b in sets[i+1:])


def test_render_is_deterministic_and_does_not_mutate_sprite():
    sprite=np.zeros((96,96,4),np.uint8);sprite[20:80,30:60]=[240,240,240,255]
    copy=sprite.copy()
    a=render_tile(sprite,np.random.default_rng(10))
    b=render_tile(sprite,np.random.default_rng(10))
    assert np.array_equal(a,b) and np.array_equal(sprite,copy)
    assert a.shape==(96,96,3) and a.dtype==np.uint8


def test_checkpoint_class_order_rejected(tmp_path):
    path=tmp_path/'wrong.pt'
    torch.save({'class_names':['wrong']},path)
    with pytest.raises(ValueError,match='class ordering'):
        load_model(path,'cpu')
