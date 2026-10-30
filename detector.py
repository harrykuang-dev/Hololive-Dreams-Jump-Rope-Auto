"""Whole-rope/marker inference: optional NVIDIA TensorRT, otherwise DirectML."""
from dataclasses import dataclass
import hashlib,json,logging,os,time
from pathlib import Path
import numpy as np
from model_runtime import RopeDetector,DirectMLRopeDetector
ROOT=Path(__file__).resolve().parent
LOG=logging.getLogger('jump-rope-auto')

@dataclass(frozen=True)
class Observation:
    features: np.ndarray
    valid: np.ndarray
    rope_xyxy: tuple|None
    marker_xyxy: tuple|None
    detections: np.ndarray
    timings_ms: dict

def device_fingerprint(driver,precision):
    import tensorrt as trt
    if not trt.__version__.startswith('10.13.'):raise RuntimeError('TensorRT 10.13 is required')
    source=ROOT/'models'/('rope.fp16.onnx' if precision=='fp16' else 'rope.onnx')
    return dict(model_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        **driver.info,tensorrt=trt.__version__,precision=precision,tf32=False,
        graph_types='strong',cache_version=2)

def resolve_engine(*,stopped=lambda:False,precision='fp16'):
    from optional_accelerator import activate_tensorrt_component
    from cuda_driver import CudaDriver
    if precision not in ('fp16','fp32'):raise ValueError('Unsupported precision')
    if stopped():raise InterruptedError('Model preparation stopped')
    activate_tensorrt_component()
    driver=CudaDriver()
    try:
        with driver.current():return _resolve_engine(driver,precision,stopped)
    finally:driver.close()

def _resolve_engine(driver,precision,stopped):
    fingerprint=device_fingerprint(driver,precision)
    key=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()[:24]
    base=Path(os.environ.get('JUMPROPE_ENGINE_CACHE',str(Path(os.environ.get('LOCALAPPDATA',str(ROOT)))/'HololiveJumpRopeAuto/models')))
    cache=base/key
    engine,metadata=cache/'rope.engine',cache/'device.json'
    if engine.exists() and metadata.exists():
        record=json.loads(metadata.read_text())
        if record.get('key')==fingerprint and record.get('sha256')==hashlib.sha256(engine.read_bytes()).hexdigest():return engine
    if stopped():raise InterruptedError('Model preparation stopped')
    LOG.info('正在為目前顯示卡準備模型；完成後才會開始操作')
    import tensorrt as trt
    from optional_accelerator import load_builder_library
    load_builder_library()
    logger=trt.Logger(trt.Logger.WARNING);builder=trt.Builder(logger)
    flags=(1<<int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))|(1<<int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
    network=builder.create_network(flags);parser=trt.OnnxParser(network,logger)
    source=ROOT/'models'/('rope.fp16.onnx' if precision=='fp16' else 'rope.onnx')
    if not parser.parse(source.read_bytes()):
        raise RuntimeError('Cannot prepare model: '+'; '.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
    config=builder.create_builder_config();config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE,1<<30)
    config.clear_flag(trt.BuilderFlag.TF32)
    class Progress(trt.IProgressMonitor):
        def __init__(self):trt.IProgressMonitor.__init__(self)
        def phase_start(self,*_):pass
        def phase_finish(self,*_):pass
        def step_complete(self,*_):return not stopped()
    monitor=Progress();config.progress_monitor=monitor
    serialized=builder.build_serialized_network(network,config)
    if serialized is None:raise RuntimeError('TensorRT model preparation failed')
    if stopped():raise InterruptedError('Model preparation stopped')
    cache.mkdir(parents=True,exist_ok=True)
    temporary=engine.with_suffix('.tmp');temporary.write_bytes(bytes(serialized));temporary.replace(engine)
    record=dict(key=fingerprint,sha256=hashlib.sha256(bytes(serialized)).hexdigest())
    meta_tmp=metadata.with_suffix('.tmp');meta_tmp.write_text(json.dumps(record,indent=2),encoding='utf-8');meta_tmp.replace(metadata)
    return engine

def create_gpu_runtime(stopped,engine):
    from optional_accelerator import activate_tensorrt_component
    activate_tensorrt_component()
    return RopeDetector(engine or resolve_engine(stopped=stopped),device='cuda:0',
                        confidence=.15,classes=(0,1),fast_preprocess=True)


class FullFrameDetector:
    def __init__(self,*,stopped=lambda:False,engine=None,backend='auto',diagnostics=None):
        if backend=='auto':backend=os.environ.get('JUMPROPE_BACKEND','auto')
        if backend not in ('auto','directml','gpu'):raise ValueError('Only TensorRT or DirectML GPU inference is supported')
        self.fallback_reason=None
        self.runtime=None
        self._diagnostics=diagnostics
        self.warmup_diagnostics=[]
        if stopped():raise InterruptedError('Model preparation stopped')
        if backend!='directml':
            began=time.perf_counter_ns()
            if diagnostics:diagnostics('backend_initialization_begin',backend='tensorrt-fp16',requested=backend)
            try:
                self.runtime=create_gpu_runtime(stopped,engine)
                self._warmup(stopped)
            except InterruptedError:
                self._discard_gpu_runtime();raise
            except Exception as error:
                self._discard_gpu_runtime()
                if diagnostics:
                    import traceback
                    diagnostics('backend_initialization_failed',backend='tensorrt-fp16',
                        elapsed_ms=(time.perf_counter_ns()-began)/1e6,error_type=type(error).__name__,
                        message=str(error),traceback=traceback.format_exc())
                if backend=='gpu':raise
                if stopped():raise InterruptedError('Model preparation stopped')
                self.fallback_reason=f'{type(error).__name__}: {error}'
                self.runtime=None
                LOG.info('TensorRT 無法使用，改用 DirectML：%s',self.fallback_reason)
        else:self.runtime=None
        if self.runtime is None:
            began=time.perf_counter_ns()
            if diagnostics:diagnostics('backend_initialization_begin',backend='onnx-directml',requested=backend)
            try:
                self.runtime=DirectMLRopeDetector(ROOT/'models/rope.directml.onnx')
                self._warmup(stopped)
            except Exception as error:
                if diagnostics:
                    import traceback
                    diagnostics('backend_initialization_failed',backend='onnx-directml',
                        elapsed_ms=(time.perf_counter_ns()-began)/1e6,error_type=type(error).__name__,
                        message=str(error),traceback=traceback.format_exc())
                raise
        self.backend=self.runtime.backend
        LOG.info('辨識後端：%s',self.backend)
        if hasattr(self.runtime,'adapter'):LOG.info('DirectML 顯示卡：%s',self.runtime.adapter['name'])

    def _discard_gpu_runtime(self):
        runtime=self.runtime;self.runtime=None
        if runtime is not None and hasattr(runtime,'close'):runtime.close()

    def _warmup(self,stopped):
        self.warmup_diagnostics=[]
        for _ in range(15):
            if stopped():raise InterruptedError('Model preparation stopped')
            observation=self.observe(np.zeros((720,1280,3),np.uint8))
            self.warmup_diagnostics.append(observation.timings_ms)
    def observe(self,frame,*,already_cropped=True):
        began=time.perf_counter_ns();h,w=frame.shape[:2]
        detections,timing=self.runtime.observe(frame,already_cropped=True)
        rows=np.array([[*(np.asarray(d.xyxy)*[w,h,w,h]).tolist(),d.confidence,d.class_id]
            for d in detections],np.float32).reshape(-1,6)
        rope,markers=rows[rows[:,5]==0],rows[rows[:,5]==1]
        box=None if not len(rope) else tuple(map(float,rope[rope[:,4].argmax(),:4]))
        marker=None if not len(markers) else tuple(map(float,markers[markers[:,4].argmax(),:4]))
        features=np.full(4,np.nan)
        if box is not None:features[:]=[box[1]/h,box[3]/h,box[0]/w,box[2]/w]
        timing=dict(timing);timing['full_frame_total_ms']=(time.perf_counter_ns()-began)/1e6
        return Observation(features,np.isfinite(features),box,marker,rows,timing)
