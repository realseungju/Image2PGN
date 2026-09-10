"""Fixed eight-epoch ablation excluding audited automatic-side replay images."""
import argparse,json,random,time,sys
from pathlib import Path
import cv2,numpy as np,torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from infra.train_color import sha,load_model,load_npz,tensors,loss_fn,evaluate
from infra.evaluate_color import screens
from image2pgn.pieces import CLASS_NAMES

def read_rows(rows,base):
    images=[];labels=[]
    for r in rows:
        p=Path(r['path']);p=p if p.is_absolute() else base/p
        if sha(p)!=r['sha256']:raise ValueError('Replay hash mismatch: '+str(p))
        im=cv2.imread(str(p))
        if im is None:raise ValueError(str(p))
        images.append(cv2.cvtColor(cv2.resize(im,(96,96),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB));labels.append(r['label'])
    return np.array(images),np.array(labels)

def main():
    ap=argparse.ArgumentParser()
    for name in ('manifest','audit','base','data','init','reference','labels','images','out'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args()
    if a.out.exists():raise ValueError('Output must be new')
    m=json.loads(a.manifest.read_text(encoding='utf-8'));audit=json.loads(a.audit.read_text(encoding='utf-8'))
    excluded_a=[r for r in audit['items'] if r['used_in_final_replay']]
    keys={(Path(r['path']).name,r['sha256']) for r in excluded_a}
    if len(keys)!=50:raise ValueError('Need 50 unique audited replay images')
    removed=[r for r in m['replay_train'] if (Path(r['path']).name,r['sha256']) in keys]
    kept=[r for r in m['replay_train'] if (Path(r['path']).name,r['sha256']) not in keys]
    if len(removed)!=50:raise ValueError('Exact 50 exclusions required')
    if sha(a.init)!=m['initial_sha256'] or sha(a.data/'dataset.json')!=m['dataset_sha256']:raise ValueError('Initial model or dataset mismatch')
    # Validate excluded files too, preserving the source provenance check.
    read_rows(removed,a.base)
    x,y=load_npz(a.data/'train.npz');rx,ry=read_rows(kept,a.base);x=np.concatenate((x,rx));y=np.concatenate((y,ry))
    assert len(y)==28548
    vx,vy=load_npz(a.data/'val.npz')
    val=[r for r in m['replay_val'] if Path(r['path']).name.startswith('s1m0n38_')]
    assert len(val)==595
    hx,hy=read_rows(val,a.base)
    torch.set_num_threads(6);torch.manual_seed(20260907);np.random.seed(20260907);random.seed(20260907)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    device='cuda';model=load_model(a.init,device)
    a.out.mkdir(parents=True)
    metadata={'config':{k:str(v) for k,v in vars(a).items()},'seed':20260907,'epochs':8,'selection':'fixed epoch 8 before run','train_count':len(y),'excluded':removed,'replay_train':kept,'replay_val':val,'initial_sha256':sha(a.init),'reference_sha256':sha(a.reference),'script_sha256':sha(__file__),'manifest_sha256':sha(a.manifest),'audit_sha256':sha(a.audit),'npz_sha256':{n:sha(a.data/(n+'.npz')) for n in ('train','val','test')},'torch':torch.__version__,'numpy':np.__version__,'opencv':cv2.__version__,'gpu':torch.cuda.get_device_name(),'batch_size':128,'learning_rate':.0001,'weight_decay':.0001,'color_weight':.25,'limitations':['single seed exploratory','removal changes batch composition; both runs have 224 steps per epoch','historical initialization exposure not removed','15 screenshots and rhosgfx previously used for development']}
    (a.out/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0001,weight_decay=.0001)
    loader=torch.utils.data.DataLoader(tensors(x,y),batch_size=128,shuffle=True)
    history=[];start=time.time()
    for epoch in range(9):
        total=0.;seen=0
        if epoch:
            model.train()
            for bx,by in loader:
                bx,by=bx.to(device).float()/255,by.to(device)
                optimizer.zero_grad(set_to_none=True);loss=loss_fn(model(bx),by,.25);loss.backward();optimizer.step()
                total+=float(loss.detach())*len(by);seen+=len(by)
        synthetic,_=evaluate(model,vx,vy,device);hf,_=evaluate(model,hx,hy,device)
        row={'epoch':epoch,'train_loss_mean':total/seen if seen else None,'synthetic_val':synthetic,'chessvision_val':hf,'seconds':time.time()-start}
        history.append(row);(a.out/'history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
        print(json.dumps({'epoch':epoch,'train_loss_mean':row['train_loss_mean'],'synth_correct':synthetic['correct'],'hf_correct':hf['correct'],'seconds':row['seconds']}),flush=True)
    checkpoint=a.out/'epoch8.pt'
    torch.save({'model_state':model.cpu().state_dict(),'class_names':CLASS_NAMES,'image_size':96,'epoch':8},checkpoint)
    tx,ty=load_npz(a.data/'test.npz');results={}
    for name,path in [('reference_v3',a.reference),('exclude50',checkpoint)]:
        loaded=load_model(path,device)
        hf,hpred=evaluate(loaded,hx,hy,device);test,tpred=evaluate(loaded,tx,ty,device);screen=screens(loaded,a.labels,a.images,device)
        results[name]={'sha256':sha(path),'chessvision':hf,'chessvision_predictions':hpred,'rhosgfx':test,'rhosgfx_predictions':tpred,'screenshots':screen}
        print(name,'HF',hf['correct'],'rhosgfx',test['correct'],'screens',screen['aggregate']['correct'],'exact',screen['auto_exact'],flush=True)
    (a.out/'comparison.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('Completed; candidate SHA256 '+sha(checkpoint),flush=True)

if __name__=='__main__':main()

