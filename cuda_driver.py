"""Small CUDA Driver API owner; NVIDIA supplies nvcuda.dll. No Torch/CuPy."""
import contextlib,ctypes as C,os
import numpy as np

RGB_TO_CHW=r'''
.version 6.0
.target sm_50
.address_size 64
.visible .entry rgb_to_chw(.param .u64 source, .param .u64 output, .param .u32 pixels)
{
 .reg .pred %p;
 .reg .b32 %r<10>;
 .reg .b64 %d<10>;
 .reg .f32 %f<3>;
 ld.param.u64 %d0, [source];
 ld.param.u64 %d1, [output];
 ld.param.u32 %r0, [pixels];
 mov.u32 %r1, %ctaid.x;
 mov.u32 %r2, %ntid.x;
 mov.u32 %r3, %tid.x;
 mad.lo.u32 %r4, %r1, %r2, %r3;
 setp.ge.u32 %p, %r4, %r0;
 @%p bra DONE;
 mul.wide.u32 %d2, %r4, 3;
 add.u64 %d3, %d0, %d2;
 ld.global.u8 %r5, [%d3];
 ld.global.u8 %r6, [%d3+1];
 ld.global.u8 %r7, [%d3+2];
 cvt.rn.f32.u32 %f0, %r5;
 cvt.rn.f32.u32 %f1, %r6;
 cvt.rn.f32.u32 %f2, %r7;
 mul.rn.f32 %f0, %f0, 0f3B808081;
 mul.rn.f32 %f1, %f1, 0f3B808081;
 mul.rn.f32 %f2, %f2, 0f3B808081;
 mul.wide.u32 %d4, %r4, 4;
 mul.wide.u32 %d5, %r0, 4;
 add.u64 %d6, %d1, %d4;
 st.global.f32 [%d6], %f0;
 add.u64 %d7, %d6, %d5;
 st.global.f32 [%d7], %f1;
 add.u64 %d8, %d7, %d5;
 st.global.f32 [%d8], %f2;
 DONE:
 ret;
}
'''

class CudaDriver:
    def __init__(self,device=0,library=None):
        self.lib=library or C.WinDLL('nvcuda.dll')
        self.context=C.c_void_p();self.closed=False;self.device=None
        ptr=C.c_void_p;gpu=C.c_uint64
        signatures={
          'cuInit':[C.c_uint],'cuDriverGetVersion':[C.POINTER(C.c_int)],
          'cuDeviceGetCount':[C.POINTER(C.c_int)],'cuDeviceGet':[C.POINTER(C.c_int),C.c_int],
          'cuDeviceGetName':[C.c_char_p,C.c_int,C.c_int],
          'cuDeviceGetAttribute':[C.POINTER(C.c_int),C.c_int,C.c_int],
          'cuDevicePrimaryCtxRetain':[C.POINTER(ptr),C.c_int],'cuDevicePrimaryCtxRelease_v2':[C.c_int],
          'cuCtxPushCurrent_v2':[ptr],'cuCtxPopCurrent_v2':[C.POINTER(ptr)],
          'cuStreamCreate':[C.POINTER(ptr),C.c_uint],'cuStreamDestroy_v2':[ptr],'cuStreamSynchronize':[ptr],
          'cuMemAlloc_v2':[C.POINTER(gpu),C.c_size_t],'cuMemFree_v2':[gpu],
          'cuMemHostAlloc':[C.POINTER(ptr),C.c_size_t,C.c_uint],'cuMemFreeHost':[ptr],
          'cuMemcpyHtoDAsync_v2':[gpu,ptr,C.c_size_t,ptr],
          'cuMemcpyDtoHAsync_v2':[ptr,gpu,C.c_size_t,ptr],
          'cuModuleLoadData':[C.POINTER(ptr),ptr],'cuModuleUnload':[ptr],
          'cuModuleGetFunction':[C.POINTER(ptr),ptr,C.c_char_p],
          'cuLaunchKernel':[ptr,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,C.c_uint,ptr,C.POINTER(ptr),ptr]}
        for name,args in signatures.items():
            fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=C.c_int
        try:
            # Honor the explicit disabled-CUDA mask without changing DML selection.
            mask=os.environ.get('CUDA_VISIBLE_DEVICES')
            if mask is not None and mask.strip() in ('','-1'):raise RuntimeError('CUDA disabled by environment')
            self.call('cuInit',0);count=C.c_int();self.call('cuDeviceGetCount',C.byref(count))
            if not 0<=device<count.value:raise RuntimeError('No selected NVIDIA CUDA device')
            selected=C.c_int();self.call('cuDeviceGet',C.byref(selected),device);self.device=selected.value
            major=C.c_int();minor=C.c_int();version=C.c_int();name=C.create_string_buffer(256)
            self.call('cuDeviceGetAttribute',C.byref(major),75,self.device)
            self.call('cuDeviceGetAttribute',C.byref(minor),76,self.device)
            self.call('cuDriverGetVersion',C.byref(version));self.call('cuDeviceGetName',name,256,self.device)
            if (major.value,minor.value)<(7,5):raise RuntimeError('TensorRT 10.13 requires Turing or newer')
            self.info=dict(gpu=name.value.decode(errors='replace'),capability=[major.value,minor.value],driver_api=version.value,device=device)
            self.call('cuDevicePrimaryCtxRetain',C.byref(self.context),self.device)
        except BaseException:
            self.close();raise

    def call(self,name,*args):
        code=getattr(self.lib,name)(*args)
        if code:raise RuntimeError(f'CUDA {name} failed ({code})')

    @contextlib.contextmanager
    def current(self):
        if self.closed or not self.context.value:raise RuntimeError('CUDA context is closed')
        self.call('cuCtxPushCurrent_v2',self.context)
        try:yield
        finally:
            previous=C.c_void_p();self.call('cuCtxPopCurrent_v2',C.byref(previous))

    def close(self):
        if not self.closed and self.context.value:
            self.call('cuDevicePrimaryCtxRelease_v2',self.device);self.context=C.c_void_p()
        self.closed=True
    def __del__(self):
        try:self.close()
        except Exception:pass

class Buffer:
    def __init__(self,driver,shape,dtype):
        self.driver=driver;self.device=C.c_uint64();self.host=C.c_void_p()
        self.nbytes=int(np.prod(shape))*np.dtype(dtype).itemsize
        try:
            driver.call('cuMemAlloc_v2',C.byref(self.device),self.nbytes)
            driver.call('cuMemHostAlloc',C.byref(self.host),self.nbytes,0)
            raw=np.ctypeslib.as_array((C.c_ubyte*self.nbytes).from_address(self.host.value))
            self.array=raw.view(dtype).reshape(shape)
        except BaseException:self.close();raise
    def close(self):
        first=None
        if self.device.value:
            try:self.driver.call('cuMemFree_v2',self.device)
            except Exception as error:first=error
            self.device=C.c_uint64()
        if self.host.value:
            try:self.driver.call('cuMemFreeHost',self.host)
            except Exception as error:first=first or error
            self.host=C.c_void_p()
        self.array=None
        if first:raise first

class PackedPreprocessor:
    def __init__(self,driver):
        self.driver=driver;self.module=C.c_void_p();self.function=C.c_void_p()
        text=C.create_string_buffer(RGB_TO_CHW.encode())
        try:
            driver.call('cuModuleLoadData',C.byref(self.module),C.cast(text,C.c_void_p))
            driver.call('cuModuleGetFunction',C.byref(self.function),self.module,b'rgb_to_chw')
        except BaseException:self.close();raise
    def launch(self,rgb,output,pixels,stream):
        src=C.c_uint64(rgb);dst=C.c_uint64(output);count=C.c_uint(pixels)
        args=(C.c_void_p*3)(C.cast(C.byref(src),C.c_void_p),C.cast(C.byref(dst),C.c_void_p),C.cast(C.byref(count),C.c_void_p))
        self.driver.call('cuLaunchKernel',self.function,(pixels+255)//256,1,1,256,1,1,0,stream,args,None)
    def close(self):
        if self.module.value:self.driver.call('cuModuleUnload',self.module);self.module=C.c_void_p()
