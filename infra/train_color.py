"""Fine-tune PieceCnn without changing its inference architecture.

Selection uses validation only. Test and screenshot evaluation are separate commands.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time

import cv2
import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from image2pgn.cnn import PieceCnn
from image2pgn.pieces import CLASS_NAMES


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def color_logits(logits):
    """Marginalize the existing logits; no extra inference parameters."""
    return torch.stack((torch.logsumexp(logits[:,1:7],1),torch.logsumexp(logits[:,7:13],1)),1)


def loss_fn(logits, labels, color_weight=.25):
    loss = torch.nn.functional.cross_entropy(logits,labels)
    occupied = labels > 0
    if occupied.any():
        loss = loss + color_weight * torch.nn.functional.cross_entropy(color_logits(logits[occupied]),(labels[occupied]>6).long())
    return loss


def metrics(labels,predictions):
    labels,predictions = np.asarray(labels),np.asarray(predictions)
    occupied = labels>0
    detected = occupied & (predictions>0)
    confusion = np.zeros((13,13),dtype=int)
    np.add.at(confusion,(labels,predictions),1)
    return {'n':len(labels),'correct':int((labels==predictions).sum()),'accuracy':float((labels==predictions).mean()),
            'occupied':int(occupied.sum()),
            'color_errors':int((detected & ((labels>6)!=(predictions>6))).sum()),
            'type_errors':int((detected & ((labels-1)%6 != (predictions-1)%6)).sum()),
            'missed_pieces':int((occupied & (predictions==0)).sum()),
            'false_pieces':int(((labels==0) & (predictions>0)).sum()),'confusion':confusion.tolist()}


def load_npz(path):
    with np.load(path) as data:
        return data['images'],data['labels']


def replay(root,limit,seed):
    rng = random.Random(seed)
    images,labels,manifest = [],[],[]
    for label,name in enumerate(CLASS_NAMES):
        paths = sorted(p for p in (root/name).glob('*') if p.suffix.lower() in ('.jpg','.png','.jpeg'))
        if limit and len(paths)>limit:
            paths = rng.sample(paths,limit)
        for path in paths:
            im = cv2.imread(str(path))
            if im is None:
                raise ValueError(str(path))
            images.append(cv2.cvtColor(cv2.resize(im,(96,96),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB))
            labels.append(label)
            manifest.append({'path':str(path),'sha256':sha(path),'label':label})
    if not images:
        raise ValueError(f'No replay images: {root}')
    return np.array(images),np.array(labels),manifest


def tensors(images,labels):
    return torch.utils.data.TensorDataset(torch.from_numpy(images).permute(0,3,1,2),torch.from_numpy(labels).long())


@torch.no_grad()
def evaluate(model,images,labels,device):
    model.eval()
    predictions,losses = [],[]
    for x,y in torch.utils.data.DataLoader(tensors(images,labels),batch_size=128):
        x,y=x.to(device).float()/255,y.to(device)
        logits=model(x)
        losses.append(float(torch.nn.functional.cross_entropy(logits,y,reduction='sum')))
        predictions.extend(logits.argmax(1).cpu().tolist())
    result=metrics(labels,predictions)
    result['cross_entropy']=sum(losses)/len(labels)
    return result,predictions


def load_model(path,device):
    checkpoint=torch.load(path,map_location='cpu',weights_only=True)
    if checkpoint['class_names'] != CLASS_NAMES:
        raise ValueError('Checkpoint class ordering does not match CLASS_NAMES')
    model=PieceCnn(num_classes=13,nn=torch.nn).to(device)
    model.load_state_dict(checkpoint['model_state'])
    return model


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--init',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=8)
    p.add_argument('--seed',type=int,default=20260907)
    p.add_argument('--device',default='cuda')
    p.add_argument('--color-weight',type=float,default=.25)
    p.add_argument('--replay-limit',type=int,default=300)
    p.add_argument('--extra-replay',type=Path)
    args=p.parse_args()
    if args.epochs<1 or args.out.exists():
        p.error('Need positive epochs and a new output directory')
    args.out.mkdir(parents=True)
    torch.set_num_threads(6)
    torch.manual_seed(args.seed);np.random.seed(args.seed);random.seed(args.seed)
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True
    model=load_model(args.init,args.device)
    train_x,train_y=load_npz(args.data/'train.npz')
    old_x,old_y,train_manifest=replay(args.replay/'train',args.replay_limit,args.seed)
    if args.extra_replay:
        extra_x,extra_y,extra_manifest=replay(args.extra_replay/'train',300,args.seed)
        old_x=np.concatenate((old_x,extra_x));old_y=np.concatenate((old_y,extra_y))
        train_manifest.extend(extra_manifest)
    val_x,val_y=load_npz(args.data/'val.npz')
    old_val_x,old_val_y,val_manifest=replay(args.replay/'val',0,args.seed)
    # Remove exact overlap BEFORE training; historical checkpoint exposure is unknown.
    validation_hashes={r['sha256'] for r in val_manifest}
    keep=np.array([r['sha256'] not in validation_hashes for r in train_manifest])
    excluded=int((~keep).sum())
    old_x,old_y=old_x[keep],old_y[keep]
    train_manifest=[r for r,k in zip(train_manifest,keep) if k]
    train_x=np.concatenate((train_x,old_x)); train_y=np.concatenate((train_y,old_y))
    print(f'Excluded {excluded} exact replay train/validation duplicates; train={len(train_y)}',flush=True)
    metadata={'config':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
              'torch':torch.__version__,'numpy':np.__version__,'opencv':cv2.__version__,
              'device':torch.cuda.get_device_name() if args.device=='cuda' else args.device,
              'parameters':sum(p.numel() for p in model.parameters()),'initial_sha256':sha(args.init),
              'dataset_sha256':sha(args.data/'dataset.json'),'script_sha256':sha(__file__),
              'selection':'minimum mean of synthetic and replay validation cross entropy; baseline is epoch 0',
              'train_count':len(train_y),'replay_train':train_manifest,'replay_val':val_manifest,
              'excluded_replay_duplicates':excluded,'historical_checkpoint_validation_exposure':'unknown',
              'learning_rate':.0001,'batch_size':128,'weight_decay':.0001,
              'test_used_for_selection':False}
    (args.out/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0001,weight_decay=.0001)
    loader=torch.utils.data.DataLoader(tensors(train_x,train_y),batch_size=128,shuffle=True)
    best=float('inf');history=[];start=time.time()
    for epoch in range(args.epochs+1):
        if epoch:
            model.train()
            for batch,(x,y) in enumerate(loader):
                x,y=x.to(args.device).float()/255,y.to(args.device)
                optimizer.zero_grad(set_to_none=True)
                loss=loss_fn(model(x),y,args.color_weight)
                loss.backward();optimizer.step()
                if (batch+1)%40==0:
                    print(f'epoch={epoch} batch={batch+1}/{len(loader)} loss={loss.item():.4f}',flush=True)
        synth,_=evaluate(model,val_x,val_y,args.device)
        old,_=evaluate(model,old_val_x,old_val_y,args.device)
        score=(synth['cross_entropy']+old['cross_entropy'])/2
        row={'epoch':epoch,'selection_score':score,'synthetic_val':synth,'replay_val':old,'seconds':time.time()-start}
        history.append(row)
        if score<best:
            best=score
            torch.save({'model_state':model.cpu().state_dict(),'class_names':CLASS_NAMES,'image_size':96,'epoch':epoch},args.out/'best.pt')
            model.to(args.device)
        (args.out/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in row.items() if k not in ('synthetic_val','replay_val')}),
              f'synth_acc={synth["accuracy"]:.4f} color={synth["color_errors"]} replay_acc={old["accuracy"]:.4f}',flush=True)
    print(f'Finished. Best checkpoint: {args.out / "best.pt"}',flush=True)


if __name__=='__main__':
    main()
