"""DXGI hardware enumeration for DirectML, without CUDA or Torch imports."""
import ctypes
from ctypes import wintypes
import uuid


class Desc(ctypes.Structure):
    _fields_=[('name',wintypes.WCHAR*128),('vendor',wintypes.UINT),('device',wintypes.UINT),
              ('subsystem',wintypes.UINT),('revision',wintypes.UINT),
              ('dedicated',ctypes.c_size_t),('system',ctypes.c_size_t),('shared',ctypes.c_size_t),
              ('luid_low',wintypes.DWORD),('luid_high',wintypes.LONG),('flags',wintypes.UINT)]


def _method(pointer,index,result,*args):
    table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result,ctypes.c_void_p,*args)(table[index])


def adapter_inventory():
    factory=ctypes.c_void_p();result=[]
    guid=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    device_guid=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('189819f1-1db6-4b57-be54-1821339b85f7').bytes_le)
    create=ctypes.WinDLL('dxgi').CreateDXGIFactory1
    create.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)];create.restype=ctypes.c_long
    code=create(ctypes.byref(guid),ctypes.byref(factory))
    if code<0:raise OSError(f'DXGI factory failed: {code:#x}')
    d3d=ctypes.WinDLL('d3d12').D3D12CreateDevice
    d3d.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p];d3d.restype=ctypes.c_long
    try:
        for index in range(32):
            adapter=ctypes.c_void_p()
            code=_method(factory,12,ctypes.c_long,wintypes.UINT,ctypes.POINTER(ctypes.c_void_p))(
                factory,index,ctypes.byref(adapter))
            if code<0:
                if code&0xffffffff==0x887a0002:break
                raise OSError(f'DXGI adapter enumeration failed: {code:#x}')
            try:
                desc=Desc();code=_method(adapter,10,ctypes.c_long,ctypes.POINTER(Desc))(adapter,ctypes.byref(desc))
                if code<0:raise OSError(f'DXGI adapter description failed: {code:#x}')
                software=bool(desc.flags&2 or desc.vendor==0x1414)
                support=None if software else d3d(adapter,0xb000,ctypes.byref(device_guid),None)
                result.append(dict(device_id=index,name=desc.name,vendor_id=desc.vendor,
                    pci_device_id=desc.device,subsystem_id=desc.subsystem,revision=desc.revision,
                    dedicated_bytes=desc.dedicated,shared_bytes=desc.shared,
                    luid=f'{desc.luid_high&0xffffffff:08x}:{desc.luid_low:08x}',software=software,
                    d3d12_hresult=None if support is None else f'0x{support&0xffffffff:08X}',
                    eligible=not software and support>=0,
                    exclusion_reason='software_adapter' if software else 'd3d12_unavailable' if support<0 else None))
            finally:_method(adapter,2,ctypes.c_ulong)(adapter)
    finally:_method(factory,2,ctypes.c_ulong)(factory)
    return result


def hardware_adapters():
    # Same explicit device selection as before; inventory includes excluded
    # adapters so a report explains why a visible GPU was not selected.
    return sorted((a for a in adapter_inventory() if a['eligible']),
                  key=lambda a:(-a['dedicated_bytes'],a['device_id']))
