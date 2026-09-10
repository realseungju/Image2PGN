"""Matched CNN/control experiment with five deterministic brightness features."""
import argparse,json,sys,time
from pathlib import Path
import numpy as np,torch
from torch import nn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from train_color import sha,load_model,load_npz,tensors,loss_fn,evaluate,metrics
import cv2
from evaluate_color import screens
from image2pgn.cnn import PieceCnn
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

def midmedian(x):
    s=x.flatten(1).sort(1).values;n=s.shape[1]
    return (s[:,(n-1)//2]+s[:,n//2])*.5

def brightness(x):
    if x.shape[1:]!=(3,96,96):raise ValueError('Expected normalized RGB NCHW 96x96')
    g=x[:,0]*.299+x[:,1]*.587+x[:,2]*.114
    a=midmedian(g[:,36:60,36:60]);b=midmedian(g[:,29:67,29:67])
    border=torch.cat((g[:,:10].flatten(1),g[:,-10:].flatten(1),g[:,10:-10,:10].flatten(1),g[:,10:-10,-10:].flatten(1)),1)
    edge=midmedian(border)
    return torch.stack((a,b,edge,a-edge,b-edge),1)

class Fusion(nn.Module):
    def __init__(self,base,enabled):
        super().__init__();self.enabled=enabled
        self.features=nn.Sequential(*list(base.children())[:-1])
        old=list(base.children())[-1];self.head=nn.Linear(192+(5 if enabled else 0),13)
        with torch.no_grad():
            self.head.weight.zero_();self.head.weight[:,:192].copy_(old.weight);self.head.bias.copy_(old.bias)
    def forward(self,x):
        f=self.features(x)
        if self.enabled:f=torch.cat((f,brightness(x)),1)
        return self.head(f)

def restore(path,device='cpu'):
    c=torch.load(path,map_location='cpu',weights_only=True)
    if c['class_names']!=CLASS_NAMES or c['feature_version']!=1:raise ValueError('Unsupported checkpoint')
    model=Fusion(PieceCnn(13,nn),c['enabled']);model.load_state_dict(c['model_state']);return model.to(device).eval()

def main():
    ap=argparse.ArgumentParser()
    for n in ('manifest','base','data','ui','init','labels','images','out'):ap.add_argument('--'+n,type=Path,required=True)
    a=ap.parse_args()
    if a.out.exists():raise ValueError('Use new output path')
    m=json.loads(a.manifest.read_text(encoding='utf-8'))
    assert sha(a.init)==m['initial_sha256']
    for n in ('train','val','test'):assert sha(a.data/(n+'.npz'))==m['npz_sha256'][n]
    for n in ('train.npz','holdout.npz','manifest.json'):assert sha(a.ui/n)==m['hardneg_sha256'][n]
    x,y=load_npz(a.data/'train.npz');rx,ry=read_rows(m['replay_train'],a.base);ux,uy=load_npz(a.ui/'train.npz')
    x=np.concatenate((x,rx,ux));y=np.concatenate((y,ry,uy));assert len(y)==29748
    hx,hy=read_rows(m['replay_val'],a.base);assert len(hy)==595
    vx,vy=load_npz(a.data/'val.npz');a.out.mkdir(parents=True)
    torch.set_num_threads(6);torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    device='cuda';dataset=tensors(x,y);histories={};metadata={'config':{k:str(v) for k,v in vars(a).items()},'source_manifest_sha256':sha(a.manifest),'script_sha256':sha(__file__),'initial_sha256':sha(a.init),'seed':20260907,'epochs':8,'selection':'fixed epoch8','train_count':len(y),'batch_size':128,'lr':1e-4,'weight_decay':1e-4,'color_weight':.25,'torch':torch.__version__,'numpy':np.__version__,'gpu':torch.cuda.get_device_name(),'parameters':{},'limitations':['single seed development comparison','fixed five features at resized96 float grayscale','new control required due explicit per-epoch RNG','no independent screenshots']}
    for name,enabled in [('control',False),('fusion',True)]:
        torch.manual_seed(20260907)
        base=load_model(a.init,'cpu');model=Fusion(base,enabled).to(device)
        metadata['parameters'][name]=sum(p.numel() for p in model.parameters())
        opt=torch.optim.AdamW(model.parameters(),lr=1e-4,weight_decay=1e-4);history=[];start=time.time()
        for epoch in range(9):
            total=0.;seen=0;order_hash=None
            if epoch:
                gen=torch.Generator().manual_seed(20260907+epoch);order=torch.randperm(len(y),generator=gen)
                import hashlib
                order_hash=hashlib.sha256(order.numpy().tobytes()).hexdigest()
                torch.manual_seed(20260907+epoch);model.train()
                for bx,by in torch.utils.data.DataLoader(dataset,batch_size=128,sampler=order.tolist()):
                    bx,by=bx.to(device).float()/255,by.to(device);opt.zero_grad(set_to_none=True)
                    loss=loss_fn(model(bx),by,.25);loss.backward();opt.step();total+=float(loss.detach())*len(by);seen+=len(by)
            sv,_=evaluate(model,vx,vy,device);hf,_=evaluate(model,hx,hy,device)
            row={'epoch':epoch,'train_loss_mean':total/seen if seen else None,'order_sha256':order_hash,'synthetic_val':sv,'chessvision_val':hf,'seconds':time.time()-start};history.append(row)
            (a.out/(name+'-history.json')).write_text(json.dumps(history,indent=2),encoding='utf-8')
            print(name,epoch,'loss',row['train_loss_mean'],'HF',hf['correct'],'synth',sv['correct'],flush=True)
        torch.save({'model_state':model.cpu().state_dict(),'enabled':enabled,'class_names':CLASS_NAMES,'image_size':96,'epoch':8,'feature_version':1},a.out/(name+'.pt'));histories[name]=history
    assert [r['order_sha256'] for r in histories['control']]==[r['order_sha256'] for r in histories['fusion']]
    (a.out/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    tx,ty=load_npz(a.data/'test.npz');qx,qy=load_npz(a.ui/'holdout.npz');results={}
    for name in ('control','fusion'):
        model=restore(a.out/(name+'.pt'),device);hf,hp=evaluate(model,hx,hy,device);test,tp=evaluate(model,tx,ty,device);screen=screens(model,a.labels,a.images,device)
        raw,up=evaluate(model,qx,qy,device)
        with torch.no_grad():confidence=model(torch.from_numpy(qx).permute(0,3,1,2).to(device).float()/255).softmax(1).max(1).values.cpu().numpy()
        filtered=np.array(up);filtered[confidence<.5]=0
        results[name]={'sha256':sha(a.out/(name+'.pt')),'chessvision':hf,'chessvision_predictions':hp,'rhosgfx':test,'rhosgfx_predictions':tp,'screenshots':screen,'ui_holdout':{'raw':raw,'threshold_false_pieces':int((filtered>0).sum())}}
        if name=='fusion':results[name]['extra_weights']=model.head.weight[:,192:].detach().cpu().tolist()
        print(name,'screen',screen['aggregate']['correct'],'exact',screen['auto_exact'],'color',screen['aggregate']['color_errors'],'HF',hf['correct'],'rhosgfx',test['correct'],flush=True)
    (a.out/'comparison.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
if __name__=='__main__':main()


