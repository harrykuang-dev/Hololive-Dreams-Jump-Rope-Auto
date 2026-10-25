"""Train a new model from the published human annotations; never controls a game."""
import argparse,json
from pathlib import Path
from prepare_dataset import prepare

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--task',choices=('detect','segment'),default='detect')
    p.add_argument('--variant',choices=('n','l'),default='n')
    p.add_argument('--annotations',type=Path,default=Path(__file__).resolve().parents[1]/'annotations')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--device',default='0')
    p.add_argument('--epochs',type=int,default=100)
    p.add_argument('--check-only',action='store_true')
    a=p.parse_args();data=prepare(a.annotations,a.output/'data',a.task)
    if a.check_only:print(data);return
    from ultralytics import YOLO
    recipe=json.loads((Path(__file__).parent/'recipe.json').read_text(encoding='utf-8'))
    recipe.update(data=str(data),device=a.device,epochs=a.epochs,batch=8 if a.variant=='n' else 2,
                  project=str(a.output),name='model',exist_ok=False)
    if a.task=='segment':recipe.update(mask_ratio=1,overlap_mask=False)
    model=YOLO(f'yolo26{a.variant}{"-seg" if a.task=="segment" else ""}.pt')
    model.train(**recipe)

if __name__=='__main__':main()
