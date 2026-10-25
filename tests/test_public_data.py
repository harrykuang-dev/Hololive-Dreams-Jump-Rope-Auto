"""Published annotation integrity; no training, model inference or game access."""
import hashlib,json
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def test_public_annotation_counts_origins_hashes_and_split_isolation():
    base=ROOT/'annotations';m=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
    assert m['counts']=={'train':543,'val':129,'review':3}
    assert m['synthetic_images']==m['unreviewed_drafts']==0
    groups={};images={};ids=set()
    for r in m['records']:
        assert r['id'] not in ids;ids.add(r['id'])
        assert r['rope_origin']=='human_annotation' and r['marker_origin']=='source_pixel_automatic'
        for key,sha in (('image','image_sha256'),('rope_mask','rope_sha256'),('marker_mask','marker_sha256')):
            p=base/r[key];assert p.is_relative_to(base)
            assert hashlib.sha256(p.read_bytes()).hexdigest()==r[sha]
        image=cv2.imread(str(base/r['image']));rope=cv2.imread(str(base/r['rope_mask']),0)
        assert image.shape[:2]==rope.shape==(r['height'],r['width'])
        assert (base/r['image']).read_bytes().startswith(b'\xff\xd8')
        if r['training_ready']:
            assert groups.setdefault(r['group'],r['split'])==r['split']
            assert images.setdefault(r['image_sha256'],r['split'])==r['split']
            for task in ('detect','segment'):
                label=base/'labels'/task/(r['id']+'.txt')
                assert hashlib.sha256(label.read_bytes()).hexdigest()==r[task+'_sha256']
                for line in label.read_text().splitlines():
                    values=line.split();assert values[0] in ('0','1')
                    assert all(0<=float(x)<=1 for x in values[1:])
            boxes=[l for l in (base/'labels/detect'/(r['id']+'.txt')).read_text().splitlines() if l.startswith('0 ')]
            assert len(boxes)==1
            assert min(x['iou'] for x in r['segment_mask_iou'])>=.97
        else:
            assert r['split']=='review' and r['rope_state']=='unknown'
            assert not (base/'labels/detect'/(r['id']+'.txt')).exists()
    assert len(ids)==675

def test_current_and_archived_licenses_remain_distinct():
    assert 'GNU AFFERO GENERAL PUBLIC LICENSE' in (ROOT/'LICENSE').read_text()
    assert (ROOT/'archive/v1.2.1/LICENSE').read_text().startswith('MIT License')
    assert 'Attribution 4.0 International' in (ROOT/'annotations/LICENSE').read_text()

def test_six_readmes_have_same_language_order_current_version_and_licenses():
    names=['README.md','README.zh-TW.md','README.ja.md','README.ko.md','README.id.md','README.zh-CN.md']
    previous=None
    for name in names:
        value=(ROOT/name).read_text(encoding='utf-8');links=value.splitlines()[2]
        if previous is not None:assert links==previous
        previous=links
        assert '**1.3.0**' in value and 'AGPL-3.0' in value and 'CC BY 4.0' in value
        assert 'annotations/README.md' in value and 'HololiveDreamsJumpRopeAuto-1.2.1.exe' not in value
        assert 'Local preview' not in value and '本地預覽' not in value

def test_training_workspace_edits_cannot_modify_published_annotations(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('public_prepare',ROOT/'training/prepare_dataset.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source';source.mkdir();(source/'labels/detect').mkdir(parents=True)
    record=dict(id='example',training_ready=True,split='train',group='one')
    for key,filename,hashkey in (('image','example.jpg','image_sha256'),('rope_mask','rope.png','rope_sha256'),('marker_mask','marker.png','marker_sha256')):
        data=key.encode();(source/filename).write_bytes(data);record[key]=filename
        record[hashkey]=hashlib.sha256(data).hexdigest()
    label=source/'labels/detect/example.txt';label.write_text('0 .5 .5 .2 .2\n')
    record['detect_sha256']=hashlib.sha256(label.read_bytes()).hexdigest()
    (source/'manifest.json').write_text(json.dumps(dict(records=[record])))
    output=tmp_path/'work';module.prepare(source,output,'detect')
    (output/'labels/train/example.txt').write_text('changed')
    assert label.read_text()=='0 .5 .5 .2 .2\n'
