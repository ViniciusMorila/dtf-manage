"""Named Windows mutex held while the app runs. installer.iss uses the same name (AppMutex) so the
installer/updater knows the app is open. It does not block a second instance by itself."""
import sys

APP_MUTEX_NAME = "DTFManager-AppMutex"          # must match AppMutex in installer.iss
_handle = None


def acquire(name: str = APP_MUTEX_NAME) -> bool:
    """Creates (or opens) the mutex and keeps the handle until the process ends."""
    global _handle
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        handle = kernel32.CreateMutexW(None, False, name)
    except Exception:                      # never stops the app from starting
        return False
    if not handle:
        return False
    _handle = handle
    return True


def exists(name: str = APP_MUTEX_NAME) -> bool:
    """True when some process holds the mutex (what Inno Setup checks)."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenMutexW(0x00100000, False, name)       # SYNCHRONIZE
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True
