"""Preserve all learned weights; replace the fixed head's integer Mod for DML."""
import hashlib,json
from pathlib import Path
import onnx
from onnx import helper,TensorProto,numpy_helper

SOURCE_SHA256='c8328f3a16153d5c98540f2df7cd635a3b4dabbce8d2b2b9133cf14f26d732ec'


def prepare(root):
    source=root/'models/rope.onnx';target=root/'models/rope.directml.onnx'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Unvalidated model: recheck class-index bounds before conversion')
    model=onnx.load(str(source));original=[x.SerializeToString() for x in model.graph.initializer]
    nodes=[];changes=[];by={o:n for n in model.graph.node for o in n.output}
    for n in model.graph.node:
        if n.op_type!='Mod':nodes.append(n);continue
        divisor=by[n.input[1]]
        assert divisor.op_type=='Constant'
        assert numpy_helper.to_array(divisor.attribute[0].t).item()==2
        # This frozen 640x640 two-class head constructs indices in [0,16799].
        # Every value is exactly representable in FP32. Division by two, floor,
        # multiplication and subtraction are exact throughout that range.
        a,b=n.input;prefix=n.name+'/directml';af=prefix+'/x';bf=prefix+'/y'
        q=prefix+'/q';f=prefix+'/floor';prod=prefix+'/product';rem=prefix+'/remainder'
        nodes.extend([
            helper.make_node('Cast',[a],[af],name=prefix+'/CastX',to=TensorProto.FLOAT),
            helper.make_node('Cast',[b],[bf],name=prefix+'/CastY',to=TensorProto.FLOAT),
            helper.make_node('Div',[af,bf],[q],name=prefix+'/Div'),
            helper.make_node('Floor',[q],[f],name=prefix+'/Floor'),
            helper.make_node('Mul',[f,bf],[prod],name=prefix+'/Mul'),
            helper.make_node('Sub',[af,prod],[rem],name=prefix+'/Sub'),
            helper.make_node('Cast',[rem],list(n.output),name=prefix+'/CastResult',to=TensorProto.INT64)])
        changes.append(n.name)
    assert changes==['/model.23/Mod']
    del model.graph.node[:];model.graph.node.extend(nodes)
    assert original==[x.SerializeToString() for x in model.graph.initializer]
    onnx.checker.check_model(model);onnx.save(model,str(target))
    receipt=dict(source_sha256=SOURCE_SHA256,target_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                 unchanged_initializers=len(original),all_initializer_bytes_equal=True,replaced_nodes=changes,
                 integer_input_bound=[0,16799],divisor=2,retrained=False)
    (root/'models/directml-graph.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


if __name__=='__main__':print(json.dumps(prepare(Path(__file__).resolve().parents[1]),indent=2))
