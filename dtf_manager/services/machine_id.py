"""Hardware based machine identifier.

Reads the SMBIOS table with GetSystemFirmwareTable and the serial of the system
disk with DeviceIoControl, both through ctypes (no external process). The
Windows installation GUID (registry) and the network adapters are deliberately NOT used, so the
identifier survives a reinstall of Windows.

Raw serial numbers never leave this module: only a salted SHA-256 of the valid
components is exposed.

Design note: the *set* of valid components is part of the identity. Replacing
the motherboard, the CPU or the system disk changes the identifier (the
administrator then resets the machine binding on the server).
"""
import hashlib
import os
import re
import struct
import sys
import uuid

MACHINE_ID_SALT = "dtf-manager/machine-id/v1"
MIN_COMPONENTS = 2
_RSMB = 0x52534D42  # 'RSMB'

_GENERIC_EXACT = {
    "none", "n/a", "na", "null", "unknown", "default", "invalid", "not available",
    "o.e.m.", "oem", "123456789", "0123456789", "1234567890", "1234567890123456",
    "system serial number", "base board serial number", "chassis serial number",
    "system product name", "base board", "type2 - board serial number",
}
_GENERIC_PATTERNS = re.compile(
    r"to be filled|o\.e\.m|default string|not specified|not applicable|not present"
    r"|serial number|no asset|empty|sernum|xxxx", re.IGNORECASE)


class MachineIdError(RuntimeError):
    """The hardware identity could not be established; message is safe to show."""


def clean_component(value):
    """Return a normalized component, or None when the value is missing or generic."""
    if value is None:
        return None
    text = " ".join(str(value).replace("\x00", " ").split())
    if not text:
        return None
    lowered = text.lower()
    if lowered in _GENERIC_EXACT or _GENERIC_PATTERNS.search(lowered):
        return None
    compact = re.sub(r"[\s\-_.:{}]", "", lowered)
    if len(compact) < 4 or len(set(compact)) == 1:  # zeros, F's, repeated filler
        return None
    return text.upper()


def parse_smbios(table):
    """Parse the SMBIOS structure table into (type, formatted_bytes, strings)."""
    structures, i = [], 0
    while i + 4 <= len(table):
        kind, length = table[i], table[i + 1]
        if length < 4 or i + length > len(table):
            break
        formatted = bytes(table[i:i + length])
        j, strings = i + length, []
        if table[j:j + 2] == b"\x00\x00":
            j += 2
        else:
            while j < len(table) and table[j] != 0:
                end = table.find(b"\x00", j)
                if end == -1:
                    end = len(table)
                strings.append(bytes(table[j:end]).decode("ascii", "replace"))
                j = end + 1
            j += 1
        structures.append((kind, formatted, strings))
        if kind == 127:
            break
        i = j
    return structures


def _string_at(formatted, strings, offset):
    if len(formatted) <= offset:
        return None
    index = formatted[offset]
    return strings[index - 1] if 1 <= index <= len(strings) else None


def smbios_components(table):
    """Extract board serial, system UUID and processor id from an SMBIOS table."""
    found = {}
    for kind, formatted, strings in parse_smbios(table):
        if kind == 1 and "uuid" not in found and len(formatted) >= 0x18:
            raw = formatted[8:24]
            if raw not in (b"\x00" * 16, b"\xff" * 16):
                found["uuid"] = str(uuid.UUID(bytes_le=raw))
        elif kind == 2 and "board" not in found:
            found["board"] = _string_at(formatted, strings, 7)
        elif kind == 4 and "cpu" not in found and len(formatted) >= 0x10:
            populated = len(formatted) <= 0x18 or bool(formatted[0x18] & 0x40)
            if populated:
                found["cpu"] = formatted[8:16][::-1].hex()
    return found


def read_smbios_table():
    """Raw SMBIOS structure table through GetSystemFirmwareTable (Windows only)."""
    if sys.platform != "win32":
        raise OSError("SMBIOS is only available on Windows")
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.GetSystemFirmwareTable
    function.restype = ctypes.c_uint32
    function.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    size = function(_RSMB, 0, None, 0)
    if not size:
        raise OSError("SMBIOS unavailable")
    buffer = ctypes.create_string_buffer(size)
    if function(_RSMB, 0, buffer, size) != size:
        raise OSError("SMBIOS read failed")
    raw = buffer.raw
    (length,) = struct.unpack_from("<I", raw, 4)
    return raw[8:8 + length]


def read_system_disk_serial():
    """Serial of the physical disk that holds the Windows system drive."""
    if sys.platform != "win32":
        raise OSError("Disk serial is only available on Windows")
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE]
    kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                         wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = ctypes.c_void_p(-1).value

    def open_device(path):
        # Access 0: query metadata only, no administrator rights required.
        handle = kernel32.CreateFileW(path, 0, 3, None, 3, 0, None)
        if handle in (None, invalid):
            raise OSError("Cannot open storage device")
        return handle

    def ioctl(handle, code, request, size):
        out = ctypes.create_string_buffer(size)
        returned = wintypes.DWORD(0)
        request_buffer = ctypes.create_string_buffer(request, len(request)) if request else None
        if not kernel32.DeviceIoControl(handle, code, request_buffer, len(request or b""),
                                        out, size, ctypes.byref(returned), None):
            raise OSError("Storage query failed")
        return out.raw[:returned.value]

    drive = os.environ.get("SystemDrive", "C:").rstrip("\\")[:2]
    volume = open_device("\\\\.\\" + drive)
    try:
        number = struct.unpack_from("<I", ioctl(volume, 0x2D1080, None, 12), 4)[0]
    finally:
        kernel32.CloseHandle(volume)
    disk = open_device(f"\\\\.\\PhysicalDrive{number}")
    try:
        query = struct.pack("<IIB3x", 0, 0, 0)  # StorageDeviceProperty, PropertyStandardQuery
        descriptor = ioctl(disk, 0x2D1400, query, 1024)
    finally:
        kernel32.CloseHandle(disk)
    (offset,) = struct.unpack_from("<I", descriptor, 24)
    if not 0 < offset < len(descriptor):
        raise OSError("Disk has no serial number")
    end = descriptor.find(b"\x00", offset)
    serial = descriptor[offset:end if end != -1 else len(descriptor)].decode("ascii", "replace")
    return serial.strip().strip("_.")


def collect_components(*, smbios_reader=read_smbios_table, disk_reader=read_system_disk_serial):
    """Valid components only. A reader that fails simply contributes nothing."""
    raw = {}
    try:
        raw.update(smbios_components(smbios_reader()))
    except Exception:
        pass
    try:
        raw["disk"] = disk_reader()
    except Exception:
        pass
    cleaned = {name: clean_component(value) for name, value in raw.items()}
    return {name: value for name, value in cleaned.items() if value}


def compute_machine_id(components):
    if len(components) < MIN_COMPONENTS:
        raise MachineIdError(
            "Não foi possível identificar este computador com segurança. "
            "Entre em contato com o suporte.")
    payload = "|".join(f"{name}={components[name]}" for name in sorted(components))
    return hashlib.sha256(f"{MACHINE_ID_SALT}\n{payload}".encode("utf-8")).hexdigest()


def build_machine_id(*, smbios_reader=read_smbios_table, disk_reader=read_system_disk_serial):
    return compute_machine_id(collect_components(smbios_reader=smbios_reader,
                                                 disk_reader=disk_reader))


_cached = None


def get_machine_id():
    """Machine id of this process, calculated once."""
    global _cached
    if _cached is None:
        _cached = build_machine_id()
    return _cached


def reset_cache():
    global _cached
    _cached = None
