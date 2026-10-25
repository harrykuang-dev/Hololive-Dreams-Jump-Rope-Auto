"""Export YOLO26 Detect weights using the tested Ultralytics raw-output API."""
import argparse
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('weights',type=Path)
    a=p.parse_args()
    from ultralytics import YOLO
    model=YOLO(a.weights)
    if model.task!='detect':raise ValueError('The game runtime requires a Detect model')
    model.export(format='onnx',imgsz=640,batch=1,dynamic=False,simplify=False,nms=False,opset=17)
    # DirectML conversion is separate; tools/prepare_directml_model.py validates
    # the exact shipped graph. A newly trained graph needs a new reviewed contract.

if __name__=='__main__':main()
