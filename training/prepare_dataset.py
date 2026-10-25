"""Materialize a grouped YOLO train/val dataset from the public annotations."""
import hashlib,json,shutil
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(source,output,task):
    source=Path(source).resolve();output=Path(output).resolve()
    if task not in ('detect','segment'):raise ValueError('Unknown task')
    if output.exists():raise FileExistsError('Choose a new output directory; existing data is preserved')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    selected=[r for r in manifest['records'] if r['training_ready']]
    groups={};images={}
    for r in selected:
        if r['split'] not in ('train','val'):raise ValueError('Invalid split')
        if groups.setdefault(r['group'],r['split'])!=r['split']:raise ValueError('Recording group leakage')
        if images.setdefault(r['image_sha256'],r['split'])!=r['split']:raise ValueError('Image leakage')
        for key in ('image','rope_mask','marker_mask'):
            expected=r['image_sha256' if key=='image' else 'rope_sha256' if key=='rope_mask' else 'marker_sha256']
            if sha(source/r[key])!=expected:raise ValueError('Changed image or mask')
        label=source/'labels'/task/(r['id']+'.txt')
        if sha(label)!=r[task+'_sha256']:raise ValueError('Changed label')
    output.mkdir(parents=True)
    for r in selected:
        for src,dst in ((source/r['image'],output/'images'/r['split']/(r['id']+'.jpg')),
                        (source/'labels'/task/(r['id']+'.txt'),output/'labels'/r['split']/(r['id']+'.txt'))):
            dst.parent.mkdir(parents=True,exist_ok=True)
            # A training workspace is editable; do not hard-link original labels.
            shutil.copyfile(src,dst)
    yaml=output/'dataset.yaml'
    yaml.write_text(f'path: {output.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: visible_rope\n  1: player_marker\n',encoding='utf-8')
    return yaml
