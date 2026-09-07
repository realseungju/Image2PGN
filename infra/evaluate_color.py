"""Paired evaluation of locked candidates; never used by the trainer."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
import torch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from train_color import evaluate,load_model,load_npz,metrics,sha
from image2pgn.board import load_image,warp_board,split_squares,background_empty_squares
from image2pgn.fen import compress_board,orient_board,choose_orientation_by_score
from image2pgn.pieces import PIECE_TO_CLASS,CLASS_TO_PIECE,CLASS_NAMES


def screens(model,labels_path,images_dir,device):
    manifest=json.loads(labels_path.read_text(encoding='utf-8'))
    rows=[];all_truth=[];all_pred=[]
    for item in manifest['items']:
        path=images_dir/(item.get('file') or f'{item["id"]}.jpg')
        if not path.resolve().is_relative_to(images_dir.resolve()):
            raise ValueError('Image path must remain inside images directory')
        board=warp_board(load_image(path),detector='grid')
        tiles=split_squares(board)
        images=np.array([cv2.cvtColor(cv2.resize(tile,(96,96),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB) for row in tiles for tile in row])
        truth=np.array([CLASS_NAMES.index(PIECE_TO_CLASS[p]) for row in item['rows'] for p in row])
        raw,pred=evaluate(model,images,truth,device)
        with torch.no_grad():
            probabilities=model(torch.from_numpy(images).permute(0,3,1,2).to(device).float()/255).softmax(1).cpu().numpy()
        confidence=probabilities.max(1)
        filtered=np.array(pred)
        filtered[(confidence<.5)|np.array(background_empty_squares(tiles)).flatten()]=0
        chars=np.array([CLASS_TO_PIECE[CLASS_NAMES[p]] for p in filtered]).reshape(8,8).tolist()
        white=compress_board(orient_board(chars,'white'));black=compress_board(orient_board(chars,'black'))
        chosen,scores=choose_orientation_by_score(white,black)
        expected=compress_board(orient_board([list(r) for r in item['rows']],item['orientation']))
        auto=black if chosen=='black' else white
        row={'file':path.name,'sha256':sha(path),'raw':raw,'filtered':metrics(truth,filtered),
             'fixed_orientation_exact':bool(np.all(truth==filtered)),
             'auto_exact':auto==expected,'orientation':chosen,'expected_orientation':item['orientation'],
             'expected':expected,'placement':auto,'truth':truth.tolist(),'predictions':filtered.tolist(),
             'confidence':confidence.tolist()}
        rows.append(row);all_truth.extend(truth.tolist());all_pred.extend(filtered.tolist())
    return {'label_sha256':sha(labels_path),'purpose':'development regression; provisional visual labels',
            'aggregate':metrics(all_truth,all_pred),'auto_exact':sum(r['auto_exact'] for r in rows),
            'fixed_orientation_exact':sum(r['fixed_orientation_exact'] for r in rows),'boards':rows}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    torch.set_num_threads(6)
    test_x,test_y=load_npz(args.data/'test.npz')
    results={'test_sha256':sha(args.data/'test.npz'),'limitations':['single seed','synthetic test is one piece design',
             'historical checkpoint training design overlap unknown','15 screenshots used previously for development',
             'synthetic test was inspected after v1; later runs are exploratory, not an untouched confirmation'],
             'models':{}}
    for name,path in [('baseline',args.baseline),('candidate',args.candidate)]:
        model=load_model(path,'cuda')
        test,pred=evaluate(model,test_x,test_y,'cuda')
        screenshot=screens(model,args.labels,args.images,'cuda')
        results['models'][name]={'sha256':sha(path),'synthetic_test':test,'test_predictions':pred,
                                 'screenshots':screenshot}
        print(name,'synthetic',test['accuracy'],'color',test['color_errors'],
              'screen',screenshot['aggregate']['correct'],'auto_exact',screenshot['auto_exact'],flush=True)
    args.out.write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
