"""Procedural empty-square UI distractors, with no screenshot or piece inputs."""
import argparse,hashlib,json
from pathlib import Path
import cv2,numpy as np

def generate(n,seed):
    rng=np.random.default_rng(seed);images=[];kinds=[]
    for i in range(n):
        bg=np.array([(238,238,210),(118,150,86),(240,217,181),(181,136,99),(255,255,255),(45,48,54),(130,138,146)][int(rng.integers(7))],np.float32)
        im=np.broadcast_to(bg,(96,96,3)).copy()
        im=np.clip(im+rng.normal(0,rng.uniform(0,4),im.shape),0,255).astype(np.uint8)
        layer=im.copy(); shade=int(rng.integers(20,240));color=(shade,shade,shade)
        x,y=int(rng.integers(10,86)),int(rng.integers(10,86));size=int(rng.integers(6,30));width=int(rng.integers(1,5));kind=i%3
        if kind==0:
            cv2.circle(layer,(x,y),size,color,width,cv2.LINE_AA)
            cv2.line(layer,(x+size*2//3,y+size*2//3),(x+size+10,y+size+10),color,width,cv2.LINE_AA)
        elif kind==1:
            cv2.rectangle(layer,(x-size,y-size//2),(x+size,y+size//2),color,width,cv2.LINE_AA)
            cv2.polylines(layer,[np.array([[x-size//2,y+size//2],[x-size//2,y+size],[x+size//3,y+size//2]])],False,color,width,cv2.LINE_AA)
            if rng.random()<.5:
                for dx in (-size//2,0,size//2):cv2.circle(layer,(x+dx,y),1,color,-1)
        else:
            word=str(rng.choice(['CHESS','LIVE','play','comment','123','WATERMARK','chess.com','?']))
            cv2.putText(layer,word,(x-40,y),cv2.FONT_HERSHEY_SIMPLEX,float(rng.uniform(.25,.9)),color,width,cv2.LINE_AA)
        alpha=float(rng.uniform(.25,1));im=cv2.addWeighted(layer,alpha,im,1-alpha,0)
        if rng.random()<.5:
            s=int(rng.integers(32,85));im=cv2.resize(cv2.resize(im,(s,s)),(96,96))
        images.append(im);kinds.append(('search','comment','text')[kind])
    return np.array(images),kinds

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.out.exists():raise ValueError('Use new output directory')
    a.out.mkdir(parents=True);meta={'source':'procedural drawing, no screenshot inputs','splits':{}}
    hashes=[];preview=[]
    for split,n,seed in [('train',1200,20260910),('holdout',300,20260911)]:
        x,kinds=generate(n,seed);y=np.zeros(n,dtype=np.int64)
        hs=[hashlib.sha256(im.tobytes()).hexdigest() for im in x];hashes.append(set(hs))
        np.savez_compressed(a.out/(split+'.npz'),images=x,labels=y)
        meta['splits'][split]={'n':n,'seed':seed,'kinds':kinds,'pixel_hashes':hs,'npz_sha256':hashlib.sha256((a.out/(split+'.npz')).read_bytes()).hexdigest()}
        if split=='train':preview=x[:36]
    assert not hashes[0]&hashes[1]
    (a.out/'manifest.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    grid=np.concatenate([np.concatenate(preview[i:i+6],axis=1) for i in range(0,36,6)])
    cv2.imwrite(str(a.out/'preview.jpg'),cv2.cvtColor(grid,cv2.COLOR_RGB2BGR))
    print('train=1200 holdout=300; exact cross-split duplicates=0')
if __name__=='__main__':main()
