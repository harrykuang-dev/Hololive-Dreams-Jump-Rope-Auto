"""Make a separate internally FP16 model, retaining FP32 inputs and outputs."""
import argparse
from pathlib import Path

def convert(source,destination):
    import onnx
    from onnxruntime.transformers import float16
    from onnxruntime.transformers.onnx_model import OnnxModel
    if destination.exists():raise FileExistsError(destination)
    model=float16.convert_float_to_float16(onnx.load(str(source)),keep_io_types=True)
    OnnxModel(model).topological_sort(is_deterministic=True)
    onnx.checker.check_model(model)
    destination.write_bytes(model.SerializeToString())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();convert(a.source,a.destination)
