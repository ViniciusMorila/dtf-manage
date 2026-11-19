"""Local license cache protected with Windows DPAPI.

The cache only serves to display the plan and to count the 72 hour offline
grace period. It NEVER authorizes use by itself outside that grace period. The
machine id is the DPAPI optional entropy, so a copied cache file is useless on
another computer or user profile.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from dtf_manager.models.license import LicenseInfo, parse_timestamp

CACHE_VERSION = 1
_ENTROPY_PREFIX = "dtf-manager/license-cache/v1:"


class LicenseStoreError(RuntimeError):
    """Sanitized local error; never contains license or machine data."""


@dataclass(frozen=True)
class LicenseSnapshot:
    info: LicenseInfo
    server_now: str       # servidor_agora of the last successful validation
    validated_at: str     # local UTC clock at that validation
    high_water: str       # highest local UTC clock ever observed by the app


class DpapiProtector:
    """CryptProtectData / CryptUnprotectData through ctypes (current user scope)."""

    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def _call(self, name, data, entropy):
        if sys.platform != "win32":
            raise LicenseStoreError("Proteção local indisponível neste sistema.")
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def blob(raw):
            buffer = ctypes.create_string_buffer(raw, len(raw))
            return DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        function = getattr(crypt32, name)
        function.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.POINTER(DataBlob),
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(DataBlob)]
        source, keep_source = blob(data)
        extra, keep_extra = blob(entropy)
        out = DataBlob()
        if not function(ctypes.byref(source), None, ctypes.byref(extra), None, None,
                        self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise LicenseStoreError("Falha na proteção local da licença.")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
            del keep_source, keep_extra

    def protect(self, data, entropy):
        return self._call("CryptProtectData", data, entropy)

    def unprotect(self, blob, entropy):
        return self._call("CryptUnprotectData", blob, entropy)


def default_cache_path():
    from PySide6.QtCore import QStandardPaths
    folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(folder) / "license_cache.bin"


class LicenseStore:
    def __init__(self, machine_id, *, path=None, protector=None):
        self._machine_id = machine_id
        self._path = Path(path) if path is not None else None
        self._protector = protector if protector is not None else DpapiProtector()

    @property
    def path(self):
        if self._path is None:
            self._path = default_cache_path()
        return self._path

    def _entropy(self):
        machine = self._machine_id() if callable(self._machine_id) else self._machine_id
        return (_ENTROPY_PREFIX + str(machine)).encode("utf-8")

    def save(self, snapshot):
        payload = json.dumps({
            "v": CACHE_VERSION, "license": snapshot.info.to_dict(),
            "server_now": snapshot.server_now, "validated_at": snapshot.validated_at,
            "high_water": snapshot.high_water,
        }, separators=(",", ":")).encode("utf-8")
        try:
            blob = self._protector.protect(payload, self._entropy())
            path = self.path
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(blob)
            os.replace(temporary, path)
        except LicenseStoreError:
            raise
        except Exception:
            raise LicenseStoreError("Não foi possível salvar o cache da licença.") from None

    def load(self):
        """Snapshot, or None when missing, corrupt, tampered or from another machine."""
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            raise LicenseStoreError("Não foi possível ler o cache da licença.") from None
        try:
            data = json.loads(self._protector.unprotect(blob, self._entropy()))
            info = LicenseInfo.from_dict(data["license"])
            snapshot = LicenseSnapshot(info, data["server_now"], data["validated_at"],
                                       data["high_water"])
            if (data.get("v") != CACHE_VERSION or info is None
                    or any(parse_timestamp(v) is None for v in
                           (snapshot.server_now, snapshot.validated_at, snapshot.high_water))):
                return None
            return snapshot
        except Exception:
            return None

    def delete(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise LicenseStoreError("Não foi possível apagar o cache da licença.") from None
