"""Prepare reviewable release assets locally; never upload or alter Git refs."""
import argparse,hashlib,json,zipfile,shutil,subprocess
from pathlib import Path

LIMIT=1500*1024**2
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def zip_files(path,files,base,prefix=''):
    if path.exists():raise FileExistsError(path)
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as out:
        for file in files:out.write(file,prefix+file.relative_to(base).as_posix())
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP CRC validation failed')
    return dict(file=path.name,bytes=path.stat().st_size,sha256=digest(path),files=len(files))

def main():
    p=argparse.ArgumentParser();p.add_argument('--core',type=Path);p.add_argument('--accelerator',type=Path)
    p.add_argument('--single-accelerator',action='store_true')
    p.add_argument('--full-7z',action='store_true')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    records=[]
    if a.core:
        if not a.full_7z:
            files=[f for f in a.core.rglob('*') if f.is_file() and 'accelerators' not in f.relative_to(a.core).parts]
            records.append(zip_files(a.output/'HololiveDreamsJumpRopeAuto-1.3.3-windows-x64.zip',files,a.core,a.core.name+'/'))
        if a.full_7z:
            executable=shutil.which('7z') or 'C:/Program Files/7-Zip/7z.exe'
            target=(a.output/'HololiveDreamsJumpRopeAuto-1.3.3-windows-x64-full.7z').resolve()
            if target.exists():raise FileExistsError(target)
            subprocess.run([executable,'a','-t7z','-mx=5','-mmt=4','-bd','-bso0',str(target),a.core.name],cwd=a.core.resolve().parent,check=True)
            subprocess.run([executable,'t','-bd','-bso0',str(target)],check=True)
            record=dict(file=target.name,bytes=target.stat().st_size,sha256=digest(target),
                        files=sum(1 for p in a.core.rglob('*') if p.is_file()))
            (a.output/'full-assets.json').write_text(json.dumps([record],indent=2)+'\n',encoding='utf-8')
            records.append(record)
    if a.accelerator:
        files=[f for f in a.accelerator.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc']
        if a.single_accelerator:
            record=zip_files(a.output/'HololiveDreamsJumpRopeAuto-1.3.3-tensorrt.zip',files,a.accelerator,'accelerators/tensorrt/')
            if record['bytes']>=2_000_000_000:raise RuntimeError('Single accelerator ZIP exceeds the release asset limit')
            records.append(record)
            (a.output/'accelerator-assets.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(records,indent=2));return
        buckets=[];sizes=[]
        for file in sorted(files,key=lambda f:f.stat().st_size,reverse=True):
            size=file.stat().st_size
            if size>LIMIT:raise RuntimeError('A single component file exceeds the part budget')
            index=next((i for i,s in enumerate(sizes) if s+size<=LIMIT),None)
            if index is None:buckets.append([]);sizes.append(0);index=len(buckets)-1
            buckets[index].append(file);sizes[index]+=size
        for index,bucket in enumerate(buckets,1):
            records.append(zip_files(a.output/f'HololiveDreamsJumpRopeAuto-1.3.3-tensorrt-part{index}.zip',bucket,a.accelerator,'accelerators/tensorrt/'))
            print('Packed accelerator part',index,'of',len(buckets),flush=True)
    manifest=a.output/('accelerator-assets.json' if a.accelerator else 'core-assets.json')
    manifest.write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records,indent=2))

if __name__=='__main__':main()
