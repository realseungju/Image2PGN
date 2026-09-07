"""Reproducible, design-disjoint tile data for the existing 13-class CNN."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

REVISION = 'e053316a1a1816edbc83d220d8439ccad60b5636'
SPLITS = {'train': ['chessnut', 'fantasy', 'celtic'], 'val': ['spatial'], 'test': ['rhosgfx']}
LICENSES = {'chessnut': 'Apache-2.0 / Alexis Luengas', 'fantasy': 'MIT / Maurizio Monge',
            'celtic': 'MIT / Maurizio Monge', 'spatial': 'MIT / Maurizio Monge', 'rhosgfx': 'CC0-1.0 / RhosGFX'}
CLASSES = ['empty'] + [f'{c}_{p}' for c in ('white', 'black') for p in ('pawn', 'knight', 'bishop', 'rook', 'queen', 'king')]
SYMBOLS = [''] + [c+p for c in 'wb' for p in 'PNBRQK']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch_assets(root):
    root.mkdir(parents=True, exist_ok=True)
    base = f'https://raw.githubusercontent.com/lichess-org/lila/{REVISION}'
    jobs = [(style, symbol) for styles in SPLITS.values() for style in styles for symbol in SYMBOLS[1:]]

    def fetch(job):
        style, symbol = job
        path = root / style / f'{symbol}.svg'
        path.parent.mkdir(exist_ok=True)
        url = f'{base}/public/piece/{style}/{symbol}.svg'
        if not path.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                path.write_bytes(response.read())
        return {'path': str(path.relative_to(root)), 'url': url, 'sha256': digest(path), 'license': LICENSES[style]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        manifest = list(pool.map(fetch, jobs))
    with urllib.request.urlopen(f'{base}/COPYING.md', timeout=30) as response:
        (root / 'COPYING.md').write_bytes(response.read())
    (root / 'manifest.json').write_text(json.dumps({'revision': REVISION, 'files': manifest}, indent=2), encoding='utf-8')


def render_tile(sprite, rng):
    # Background is independent of side and piece type, including red check tiles.
    palette = [(210,238,238), (86,150,118), (181,217,240), (99,136,181),
               (230,227,222), (173,162,140), (180,180,180), (75,75,75), (90,90,225), (105,246,246)]
    bg = np.array(palette[int(rng.integers(len(palette)))], dtype=np.float32)
    image = np.broadcast_to(bg, (96,96,3)).copy()
    if rng.random() < .25:
        grain = np.sin(np.arange(96)[:,None] * rng.uniform(.2,1.5)) * rng.uniform(2,9)
        image += grain[:,:,None]
    if sprite is not None:
        side = int(rng.integers(76,97))
        resized = cv2.resize(sprite, (side,side), interpolation=cv2.INTER_AREA).astype(np.float32)
        # Warm/cool coloration preserves lightness ordering; never invert side labels.
        tint = np.array([rng.uniform(.70,1.08), rng.uniform(.82,1.06), rng.uniform(.90,1.10)])
        resized[:,:,:3] *= tint
        x = (96-side)//2 + int(rng.integers(-3,4))
        y = (96-side)//2 + int(rng.integers(-3,4))
        matrix = np.float32([[1,0,x],[0,1,y]])
        layer = cv2.warpAffine(resized, matrix, (96,96))
        alpha = layer[:,:,3:4]/255
        image = image*(1-alpha)+layer[:,:,:3]*alpha
    image = np.clip(image,0,255).astype(np.uint8)
    if rng.random() < .25:
        cv2.putText(image, str(rng.integers(1,9)), (2,12), cv2.FONT_HERSHEY_SIMPLEX,.35,(50,60,60),1,cv2.LINE_AA)
    if rng.random() < .20:
        overlay = image.copy()
        cv2.arrowedLine(overlay, (0,int(rng.integers(15,80))), (95,int(rng.integers(15,80))), (45,165,230),int(rng.integers(2,5)),tipLength=.15)
        image = cv2.addWeighted(overlay,.4,image,.6,0)
    if rng.random() < .15:
        # Small peripheral UI covers at most 10% of the tile, not a fully hidden piece.
        cv2.rectangle(image,(0,88),(95,95),(235,235,235),-1)
    image = np.clip(image.astype(np.float32)*rng.uniform(.88,1.10)+rng.uniform(-8,8),0,255).astype(np.uint8)
    if rng.random() < .4:
        n = int(rng.integers(36,85))
        image = cv2.resize(cv2.resize(image,(n,n)),(96,96))
    if rng.random() < .4:
        ok, encoded = cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,int(rng.integers(45,96))])
        if not ok:
            raise RuntimeError('JPEG encoding failed')
        image = cv2.imdecode(encoded,cv2.IMREAD_COLOR)
    return image


def generate(root, per_class=300, seed=20260907):
    import resvg_py
    assets = root / 'assets'
    rows = []
    preview = []
    for split_index,(split,styles) in enumerate(SPLITS.items()):
        rng = np.random.default_rng(seed+split_index)
        images, labels = [], []
        count = per_class if split == 'train' else max(50,per_class//3)
        for style in styles:
            rendered = [None]
            for symbol in SYMBOLS[1:]:
                raw = resvg_py.svg_to_bytes(svg_path=str(assets/style/f'{symbol}.svg'),width=96,height=96,dpi=96)
                sprite = cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_UNCHANGED)
                if sprite.shape != (96,96,4) or not np.any(sprite[:,:,3]):
                    raise ValueError(f'Invalid transparent sprite: {style}/{symbol}')
                rendered.append(sprite)
            for label,sprite in enumerate(rendered):
                for index in range(count):
                    tile = render_tile(sprite,rng)
                    images.append(cv2.cvtColor(tile,cv2.COLOR_BGR2RGB))
                    labels.append(label)
                    rows.append({'split':split,'index':len(labels)-1,'style':style,'class':CLASSES[label]})
                    if index == 0:
                        preview.append(tile)
        np.savez_compressed(root/f'{split}.npz',images=np.array(images),labels=np.array(labels,dtype=np.int64))
        print(f'{split}: {len(labels)} tiles / {styles}',flush=True)
    cv2.imwrite(str(root/'preview.jpg'),np.concatenate([np.concatenate(preview[i:i+13],axis=1) for i in range(0,len(preview),13)],axis=0))
    manifest = {'seed':seed,'splits':SPLITS,'per_class_per_train_style':per_class,'classes':CLASSES,
                'assets_sha256':digest(assets/'manifest.json'),'rows':rows,
                'sha256':{s:digest(root/f'{s}.npz') for s in SPLITS}}
    (root/'dataset.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--per-class',type=int,default=300)
    args = parser.parse_args()
    if args.per_class < 1:
        parser.error('--per-class must be positive')
    args.out.mkdir(parents=True,exist_ok=True)
    if args.fetch:
        fetch_assets(args.out/'assets')
    generate(args.out,args.per_class)
