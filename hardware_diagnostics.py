"""Bounded, read-only startup inventory. No screenshots or device activation."""
import ctypes
from ctypes import wintypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def system_status():
    result = {}
    class Memory(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load_percent', wintypes.DWORD)]+[
            (name, ctypes.c_ulonglong) for name in ('physical_total', 'physical_available',
                'pagefile_total', 'pagefile_available', 'virtual_total', 'virtual_available', 'extended')]
    memory = Memory(); memory.length = ctypes.sizeof(memory)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        result['memory'] = {key: getattr(memory, key) for key in
                            ('load_percent', 'physical_total', 'physical_available')}
    class Power(ctypes.Structure):
        _fields_ = [('ac_line_status', ctypes.c_ubyte), ('battery_flag', ctypes.c_ubyte),
                    ('battery_percent', ctypes.c_ubyte), ('energy_saver', ctypes.c_ubyte),
                    ('battery_seconds', wintypes.DWORD), ('battery_full_seconds', wintypes.DWORD)]
    power = Power()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)):
        result['power'] = {key: getattr(power, key) for key in
                           ('ac_line_status', 'battery_percent', 'energy_saver')}
    return result


def _windows_hardware():
    # Fixed script, no shell interpolation or broad environment/process export.
    script = r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new();
    $gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,ConfigManagerErrorCode,Status);
    $cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed);
    @{gpus=$gpu;cpus=$cpu}|ConvertTo-Json -Depth 4 -Compress"""
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    return json.loads(completed.stdout.decode('utf-8-sig'))


def collect_system(directory):
    result = dict(windows=platform.platform(), python=platform.python_version(),
                  architecture=platform.machine(), logical_cpus=os.cpu_count())
    for name, query in (('status', system_status), ('windows_hardware', _windows_hardware)):
        try:
            result[name] = query()
        except Exception as error:
            result[name] = dict(error=f'{type(error).__name__}: {error}')
    try:
        from gpu_adapters import adapter_inventory
        result['dxgi_adapters'] = adapter_inventory()
    except Exception as error:
        result['dxgi_adapters'] = dict(error=f'{type(error).__name__}: {error}')
    result['gpu_selection'] = dict(tensorrt='CUDA device 0; requires compatible NVIDIA driver and SM >= 7.5',
        directml='D3D12-compatible hardware adapters ordered by dedicated video memory, then DXGI index',
        windows_graphics_preference='Explicit inference device selection can override the Windows preference')
    result['environment'] = {name: os.environ.get(name) for name in
        ('JUMPROPE_BACKEND', 'CUDA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')}
    result['libraries'] = {}
    for name in ('onnxruntime-directml', 'numpy', 'opencv-python', 'dxcam'):
        try:
            result['libraries'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result['libraries'][name] = 'bundled; see loaded module version'
    try:
        import shutil
        usage = shutil.disk_usage(directory)
        result['diagnostic_disk'] = dict(total_bytes=usage.total, free_bytes=usage.free)
    except Exception as error:
        result['diagnostic_disk'] = dict(error=str(error))
    return result


def loaded_runtime(detector=None):
    result = dict(torch_imported='torch' in sys.modules)
    for name in ('onnxruntime', 'tensorrt', 'dxcam', 'numpy', 'cv2'):
        module = sys.modules.get(name)
        if module:
            result[name] = getattr(module, '__version__', None)
    for name in ('nvcuda.dll', 'DirectML.dll', 'd3d12.dll', 'dxgi.dll'):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE
        kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        handle = kernel.GetModuleHandleW(name)
        if handle:
            buffer = ctypes.create_unicode_buffer(32768)
            if kernel.GetModuleFileNameW(handle, buffer, len(buffer)):
                entry = dict(path=buffer.value)
                try:
                    import win32api
                    version = win32api.GetFileVersionInfo(buffer.value, '\\')
                    ms, ls = version['FileVersionMS'], version['FileVersionLS']
                    entry['version'] = f'{ms>>16}.{ms&65535}.{ls>>16}.{ls&65535}'
                except Exception as error:
                    entry['version_error'] = str(error)
                result[name] = entry
    if detector is not None:
        runtime = detector.runtime
        result.update(backend=detector.backend, fallback_reason=detector.fallback_reason,
                      adapter=getattr(runtime, 'adapter', None), cpu_inference=False,
                      warmup=getattr(detector, 'warmup_diagnostics', None))
        driver = getattr(runtime, 'driver', None)
        if driver:
            result['cuda_device'] = getattr(driver, 'info', {})
        session = getattr(runtime, 'session', None)
        if session:
            result['providers'] = session.get_providers()
            result['provider_options'] = session.get_provider_options()
    return result


def model_identity(root):
    return {name: dict(bytes=(root/name).stat().st_size,
                       sha256=hashlib.sha256((root/name).read_bytes()).hexdigest())
            for name in ('models/rope.onnx', 'models/rope.fp16.onnx',
                         'models/rope.directml.onnx', 'models/control.json') if (root/name).is_file()}
