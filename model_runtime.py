"""A single visual detector; no controller, screenshot or desktop side effects."""
from dataclasses import dataclass
import time
import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    xyxy: tuple[float,float,float,float]
    confidence: float
    class_id: int = 0

def letterbox(image,size):
    if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8 or min(image.shape[:2])<1:
        raise ValueError('Expected a nonempty uint8 BGR image')
    h,w=image.shape[:2]
    scale=min(size/w,size/h)
    nw,nh=round(w*scale),round(h*scale)
    left,top=(size-nw)//2,(size-nh)//2
    canvas=np.full((size,size,3),114,np.uint8)
    canvas[top:top+nh,left:left+nw]=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_LINEAR)
    tensor=np.ascontiguousarray(canvas[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255.
    return tensor,(scale,left,top,w,h)


def packed_letterbox_into(image,size,bgr,rgb):
    """Same resize/padding as letterbox; reuse uint8 storage, leave normalization to GPU."""
    if image.ndim!=3 or image.shape[2]!=3 or image.dtype!=np.uint8 or min(image.shape[:2])<1:
        raise ValueError('Expected a nonempty uint8 BGR image')
    if bgr.shape!=(size,size,3) or rgb.shape!=bgr.shape or bgr.dtype!=np.uint8 or rgb.dtype!=np.uint8:
        raise ValueError('Packed buffers must match uint8 model dimensions')
    h,w=image.shape[:2];scale=min(size/w,size/h)
    nw,nh=round(w*scale),round(h*scale);left,top=(size-nw)//2,(size-nh)//2
    bgr.fill(114)
    window=bgr[top:top+nh,left:left+nw]
    resized=cv2.resize(image,(nw,nh),dst=window,interpolation=cv2.INTER_LINEAR)
    if not np.shares_memory(resized,window):np.copyto(window,resized)
    cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB,dst=rgb)
    return scale,left,top,w,h

def decode_e2e(output,transform,confidence=.5,classes=(0,)):
    if output.ndim!=3 or output.shape[0]!=1 or output.shape[2]!=6:
        raise ValueError(f'Expected NMS-free [1,N,6] output, received {output.shape}')
    scale,left,top,w,h=transform
    accepted=[]
    rows=output[0]
    valid=np.isfinite(rows).all(axis=1)&(rows[:,4]>=confidence)&(rows[:,4]<=1)&np.isin(rows[:,5],tuple(classes))
    for x1,y1,x2,y2,score,cls in rows[valid]:
        box=(max(0.,min(1.,(x1-left)/scale/w)),max(0.,min(1.,(y1-top)/scale/h)),
             max(0.,min(1.,(x2-left)/scale/w)),max(0.,min(1.,(y2-top)/scale/h)))
        if box[2]>box[0] and box[3]>box[1]:
            accepted.append(Detection(tuple(map(float,box)),float(score),int(cls)))
    return accepted

class DirectMLRopeDetector:
    """Hardware DirectML only: reject CPU graph placement and EP retry."""
    backend = 'onnx-directml'

    def __init__(self, weights, *, size=640, device_id=None, confidence=.15, classes=(0,1),profile_prefix=None):
        import os
        import onnxruntime as ort
        import threading
        from gpu_adapters import hardware_adapters
        if 'DmlExecutionProvider' not in ort.get_available_providers():
            raise RuntimeError('DirectML execution provider is not installed; CPU inference is disabled')
        adapters=hardware_adapters()
        if device_id is not None:adapters=[a for a in adapters if a['device_id']==device_id]
        if not adapters:raise RuntimeError('No DirectX 12 hardware GPU is available; CPU inference is disabled')
        self.adapter=adapters[0]
        self.size,self.confidence,self.classes=size,confidence,tuple(classes)
        options=ort.SessionOptions()
        options.enable_mem_pattern=False
        options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry('session.disable_cpu_ep_fallback','1')
        options.intra_op_num_threads=1
        options.inter_op_num_threads=1
        if profile_prefix:
            options.enable_profiling=True;options.profile_file_prefix=str(profile_prefix)
        # DirectML selects DXGI adapters, not CUDA ordinals. On the tested NVIDIA
        # driver a CUDA=-1 mask crashes native DML session creation even without
        # importing Torch. Isolate it only during initialization, then restore it.
        cuda_mask=os.environ.pop('CUDA_VISIBLE_DEVICES',None)
        try:
            self.session=ort.InferenceSession(str(weights),sess_options=options,
                providers=[('DmlExecutionProvider',{'device_id':self.adapter['device_id']})])
        finally:
            if cuda_mask is not None:os.environ['CUDA_VISIBLE_DEVICES']=cuda_mask
        self.session.disable_fallback()
        if 'DmlExecutionProvider' not in self.session.get_providers():
            raise RuntimeError('DirectML initialization failed; refusing CPU inference')
        self._lock=threading.Lock()
        inputs=self.session.get_inputs();outputs=self.session.get_outputs()
        if len(inputs)!=1 or len(outputs)!=1 or inputs[0].shape!=[1,3,size,size] or inputs[0].type!='tensor(float)':
            raise ValueError('Expected one FP32 [1,3,640,640] model input and one output')
        self.input_name=inputs[0].name

    def observe(self,frame,*,already_cropped=True):
        start=time.perf_counter_ns()
        tensor,transform=letterbox(frame,self.size)
        ready=time.perf_counter_ns()
        with self._lock:output=self.session.run(None,{self.input_name:tensor})[0]
        inferred=time.perf_counter_ns()
        detections=decode_e2e(output,transform,self.confidence,self.classes)
        end=time.perf_counter_ns()
        return detections,dict(preprocess_ms=(ready-start)/1e6,inference_ms=(inferred-ready)/1e6,
            postprocess_ms=(end-inferred)/1e6,total_ms=(end-start)/1e6)


class RopeDetector:
    backend = 'tensorrt-fp16'
    def __init__(self,weights,*,device='cuda:0',size=640,threads=2,confidence=.15,classes=(0,1),fast_preprocess=True,precision='fp16'):
        import ctypes as C
        import threading
        from pathlib import Path
        from cuda_driver import CudaDriver,Buffer,PackedPreprocessor
        if not str(weights).lower().endswith('.engine') or not fast_preprocess:
            raise ValueError('Expected TensorRT engine and packed GPU preprocessing')
        if precision not in ('fp16','fp32'):raise ValueError('Unsupported precision')
        if not str(device).startswith('cuda:'):raise ValueError('CUDA device must be explicit')
        self.driver=None;self.buffers={};self.rgb=None;self.preprocessor=None
        self.stream=C.c_void_p();self.context=self.engine=self.trt_runtime=None
        self._lock=threading.RLock();self.closed=False
        self.size,self.confidence,self.classes=size,confidence,tuple(classes)
        self.precision=precision;self.backend='tensorrt-'+precision
        try:
            self.driver=CudaDriver(device=int(device.split(':')[1]))
            import tensorrt as trt
            if not trt.__version__.startswith('10.13.'):
                raise RuntimeError('This runtime requires TensorRT 10.13')
            self.trt_logger=trt.Logger(trt.Logger.WARNING)
            with self.driver.current():
                self.trt_runtime=trt.Runtime(self.trt_logger)
                self.engine=self.trt_runtime.deserialize_cuda_engine(Path(weights).read_bytes())
                if self.engine is None:raise ValueError('Engine cannot load on this GPU/runtime')
                self.context=self.engine.create_execution_context()
                if self.context is None:raise RuntimeError('Cannot create TensorRT execution context')
                self.driver.call('cuStreamCreate',C.byref(self.stream),1)
                inputs=[];outputs=[]
                for i in range(self.engine.num_io_tensors):
                    name=self.engine.get_tensor_name(i);shape=tuple(self.context.get_tensor_shape(name))
                    if any(d<=0 for d in shape):raise ValueError('Only fixed model shapes are supported')
                    buffer=Buffer(self.driver,shape,trt.nptype(self.engine.get_tensor_dtype(name)))
                    self.buffers[name]=buffer
                    if not self.context.set_tensor_address(name,buffer.device.value):raise RuntimeError('TensorRT binding failed')
                    (inputs if self.engine.get_tensor_mode(name)==trt.TensorIOMode.INPUT else outputs).append(name)
                if len(inputs)!=1 or len(outputs)!=1:raise ValueError('Expected one input and one output')
                self.input_name,self.output_name=inputs[0],outputs[0]
                source=self.buffers[self.input_name]
                if source.array.shape!=(1,3,size,size) or source.array.dtype!=np.float32:
                    raise ValueError('Expected FP32 [1,3,640,640] input')
                result=self.buffers[self.output_name]
                if result.array.shape!=(1,300,6) or result.array.dtype!=np.float32:
                    raise ValueError('Expected FP32 end-to-end [1,300,6] output')
                self.rgb=Buffer(self.driver,(size,size,3),np.uint8)
                self.preprocessor=PackedPreprocessor(self.driver)
                self.packed_bgr=np.empty((size,size,3),np.uint8)
        except BaseException:
            self.close();raise

    def observe(self,frame,*,already_cropped=True):
        start=time.perf_counter_ns()
        with self._lock,self.driver.current():
            if self.closed:raise RuntimeError('TensorRT runtime is closed')
            transform=packed_letterbox_into(frame,self.size,self.packed_bgr,self.rgb.array)
            self.driver.call('cuMemcpyHtoDAsync_v2',self.rgb.device,self.rgb.host,self.rgb.nbytes,self.stream)
            self.preprocessor.launch(self.rgb.device.value,self.buffers[self.input_name].device.value,self.size*self.size,self.stream)
            ready=time.perf_counter_ns()
            if not self.context.execute_async_v3(stream_handle=self.stream.value):raise RuntimeError('TensorRT execution failed')
            target=self.buffers[self.output_name]
            self.driver.call('cuMemcpyDtoHAsync_v2',target.host,target.device,target.nbytes,self.stream)
            self.driver.call('cuStreamSynchronize',self.stream)
            output=target.array.copy();self.last_raw_output=output
        inferred=time.perf_counter_ns()
        detections=decode_e2e(output,transform,self.confidence,self.classes);end=time.perf_counter_ns()
        return detections,dict(preprocess_ms=(ready-start)/1e6,inference_ms=(inferred-ready)/1e6,
            postprocess_ms=(end-inferred)/1e6,total_ms=(end-start)/1e6)

    def close(self):
        with self._lock:
            if self.closed:return
            first=None
            if self.driver is not None and self.driver.context.value:
                with self.driver.current():
                    if self.stream.value:
                        try:self.driver.call('cuStreamSynchronize',self.stream)
                        except Exception as error:first=error
                    self.context=self.engine=self.trt_runtime=None
                    for resource in [self.preprocessor,self.rgb,*self.buffers.values()]:
                        if resource is not None:
                            try:resource.close()
                            except Exception as error:first=first or error
                    self.buffers.clear();self.preprocessor=self.rgb=None
                    if self.stream.value:
                        try:self.driver.call('cuStreamDestroy_v2',self.stream)
                        except Exception as error:first=first or error
                        import ctypes as C
                        self.stream=C.c_void_p()
                try:self.driver.close()
                except Exception as error:first=first or error
            self.closed=True
            if first:raise RuntimeError('CUDA resource cleanup failed') from first

    def __del__(self):
        try:self.close()
        except Exception:pass
