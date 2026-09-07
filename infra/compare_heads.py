"""Controlled shared-backbone experiment: joint vs factorized chess outputs."""
import argparse
import json
from pathlib import Path
import random
import sys
import time
import hashlib

import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from train_color import load_model,load_npz,evaluate,sha
from evaluate_color import screens
from image2pgn.cnn import PieceCnn
from image2pgn.pieces import CLASS_NAMES


class HeadComparison(nn.Module):
    def __init__(self,architecture):
        super().__init__()
        if architecture not in ('joint','factorized'): raise ValueError(architecture)
        self.architecture=architecture
        self.features=nn.Sequential(*list(PieceCnn(13,nn).children())[:-1])
        if architecture=='joint': self.joint=nn.Linear(192,13)
        else:
            self.occupied=nn.Linear(192,1)
            self.kind=nn.Linear(192,6)
            self.side=nn.Linear(192,2)

    def forward(self,x):
        x=self.features(x)
        if self.architecture=='joint': return self.joint(x).log_softmax(1)
        o=self.occupied(x)
        kind=self.kind(x).log_softmax(1)
        side=self.side(x).log_softmax(1)
        occupied=F.logsigmoid(o)
        return torch.cat((F.logsigmoid(-o),occupied+kind+side[:,0:1],occupied+kind+side[:,1:2]),1)


def partial_loss(logp,y,side_known,color_weight=.25):
    if ((~side_known)&(y==0)).any(): raise ValueError('Unknown-side samples must be occupied')
    terms=-logp.gather(1,y[:,None]).squeeze(1)
    unknown=~side_known
    if unknown.any():
        k=(y[unknown]-1)%6+1
        p=logp[unknown]
        terms[unknown]=-torch.logsumexp(torch.stack((p.gather(1,k[:,None]).squeeze(1),p.gather(1,(k+6)[:,None]).squeeze(1)),1),1)
    known_piece=side_known&(y>0)
    loss=terms.mean()
    if known_piece.any():
        p=logp[known_piece]
        sides=torch.stack((torch.logsumexp(p[:,1:7],1),torch.logsumexp(p[:,7:13],1)),1)
        loss+=color_weight*F.cross_entropy(sides,(y[known_piece]>6).long())
    return loss


def is_kaggle(path):
    return Path(path).name.startswith(('pawn_','knight_','bishop_','rook_','queen_','king_'))


def read_manifest(rows,base):
    images=[];labels=[];known=[]
    for row in rows:
        path=base/row['path']
        if sha(path)!=row['sha256']: raise ValueError(f'Changed input: {path}')
        image=cv2.imread(str(path))
        images.append(cv2.cvtColor(cv2.resize(image,(96,96),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB))
        labels.append(row['label']);known.append(not is_kaggle(path))
    return np.array(images),np.array(labels),np.array(known)


def restore(path,device):
    checkpoint=torch.load(path,map_location='cpu',weights_only=True)
    model=HeadComparison(checkpoint['architecture'])
    model.load_state_dict(checkpoint['model_state'])
    return model.to(device).eval()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',required=True,type=Path)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--path-base',required=True,type=Path)
    p.add_argument('--init',required=True,type=Path)
    p.add_argument('--labels',required=True,type=Path)
    p.add_argument('--images',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    if a.out.exists():p.error('Output must be new')
    a.out.mkdir(parents=True)
    torch.set_num_threads(6);torch.backends.cudnn.deterministic=True;torch.backends.cudnn.benchmark=False
    source=json.loads(a.manifest.read_text(encoding='utf-8'))
    if sha(a.init)!=source['initial_sha256']:raise ValueError('Initial model mismatch')
    if sha(a.data/'dataset.json')!=source['dataset_sha256']:raise ValueError('Dataset manifest mismatch')
    dataset=json.loads((a.data/'dataset.json').read_text())
    for s in ('train','val','test'):
        if sha(a.data/f'{s}.npz')!=dataset['sha256'][s]:raise ValueError(f'Changed synthetic {s}')
    tx,ty=load_npz(a.data/'train.npz');rx,ry,rknown=read_manifest(source['replay_train'],a.path_base)
    tx=np.concatenate((tx,rx));ty=np.concatenate((ty,ry));known=np.concatenate((np.ones(len(tx)-len(rx),dtype=bool),rknown))
    assert len(tx)==28598 and (~known).sum()==50
    vx,vy=load_npz(a.data/'val.npz');hx,hy,hknown=read_manifest(source['replay_val'],a.path_base)
    initial=load_model(a.init,'cpu');initial_features=nn.Sequential(*list(initial.children())[:-1]).state_dict()
    tensors=torch.utils.data.TensorDataset(torch.from_numpy(tx).permute(0,3,1,2),torch.from_numpy(ty).long(),torch.from_numpy(known))
    metadata={'config':{k:str(v) for k,v in vars(a).items()},'seed':20260907,'epochs':8,'batch_size':128,'lr':1e-4,
              'weight_decay':1e-4,'color_weight':.25,'train':len(tx),'type_only_train':int((~known).sum()),
              'validation_synthetic':len(vy),'validation_chessvision':int(hknown.sum()),'excluded_side_validation':int((~hknown).sum()),
              'manifest_sha256':sha(a.manifest),'initial_sha256':sha(a.init),'script_sha256':sha(__file__),
              'torch':str(torch.__version__),'device':torch.cuda.get_device_name(),
              'selection':'mean of synthetic and ChessVision full-class validation NLL; no Kaggle side labels',
              'limitations':['single seed','historical backbone exposure to pseudo labels','development screenshots and synthetic test previously inspected','no independent superiority claim']}
    (a.out/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    result={}
    for arch in ('joint','factorized'):
        torch.manual_seed(20260907);np.random.seed(20260907);random.seed(20260907)
        model=HeadComparison(arch);model.features.load_state_dict(initial_features);model.to('cuda')
        optimizer=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=1e-4)
        rng=torch.Generator().manual_seed(20260907)
        history=[];best=float('inf');start=time.perf_counter()
        for epoch in range(9):
            train_loss=None;order_hash=None
            if epoch:
                order=torch.randperm(len(tx),generator=rng)
                order_hash=hashlib.sha256(order.numpy().tobytes()).hexdigest()
                loader=torch.utils.data.DataLoader(tensors,batch_size=128,sampler=order.tolist())
                model.train();total=0
                for x,y,k in loader:
                    x,y,k=x.to('cuda').float()/255,y.to('cuda'),k.to('cuda')
                    optimizer.zero_grad(set_to_none=True);loss=partial_loss(model(x),y,k)
                    loss.backward();optimizer.step();total+=float(loss)*len(y)
                train_loss=total/len(tx)
            synth,_=evaluate(model,vx,vy,'cuda');hf,_=evaluate(model,hx[hknown],hy[hknown],'cuda')
            score=(synth['cross_entropy']+hf['cross_entropy'])/2
            row={'epoch':epoch,'train_loss':train_loss,'order_sha256':order_hash,'score':score,'synthetic':synth,'chessvision':hf,'seconds':time.perf_counter()-start}
            history.append(row)
            if score<best:
                best=score
                torch.save({'architecture':arch,'model_state':model.state_dict(),'class_names':CLASS_NAMES,'image_size':96,'epoch':epoch},a.out/f'{arch}.pt')
            (a.out/f'{arch}-history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
            print(f'{arch} epoch={epoch} loss={train_loss} val={score:.5f} synth={synth["correct"]}/1300 hf={hf["correct"]}/595',flush=True)
        result[arch]={'parameters':sum(v.numel() for v in model.parameters()),'selected_epoch':min(history,key=lambda r:r['score'])['epoch'],
                      'sha256':sha(a.out/f'{arch}.pt')}
    # Freeze both checkpoints before opening development evaluations.
    ex,ey=load_npz(a.data/'test.npz')
    for arch in ('joint','factorized'):
        model=restore(a.out/f'{arch}.pt','cuda')
        result[arch]['screenshots']=screens(model,a.labels,a.images,'cuda')
        result[arch]['synthetic_development'],result[arch]['synthetic_predictions']=evaluate(model,ex,ey,'cuda')
        with torch.no_grad():
            x=torch.from_numpy(hx[~hknown]).permute(0,3,1,2).to('cuda').float()/255
            prob=model(x).softmax(1)
            kinds=(prob[:,1:7]+prob[:,7:13]).argmax(1).cpu().numpy()
            result[arch]['kaggle_type_only']={'n':len(kinds),'correct':int((kinds==(hy[~hknown]-1)%6).sum()),'side_scored':False}
        print(arch,'screens',result[arch]['screenshots']['aggregate']['correct'],'exact',result[arch]['screenshots']['auto_exact'],flush=True)
    (a.out/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
