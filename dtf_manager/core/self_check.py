"""Headless check of the Windows-only pieces, usable from the frozen executable.

``DTFManager.exe --self-check result.json`` verifies that SMBIOS (ctypes), the
system disk query and DPAPI work in the packaged build. It makes no network call
and opens no window. The result never contains serial numbers or the machine id.
"""
import json
import re
import sys


def collect():
    result = {"frozen": bool(getattr(sys, "frozen", False)), "ok": False}
    try:
        from dtf_manager.services.machine_id import collect_components, compute_machine_id
        components = collect_components()
        result["machine_components"] = sorted(components)
        first = compute_machine_id(components)
        result["machine_id_is_sha256_hex"] = bool(re.fullmatch(r"[0-9a-f]{64}", first))
        result["machine_id_stable"] = first == compute_machine_id(collect_components())
    except Exception as error:  # report the class only, never data
        result["machine_id_error"] = type(error).__name__
    try:
        from dtf_manager.services.license_store import DpapiProtector, LicenseStoreError
        protector = DpapiProtector()
        blob = protector.protect(b"dtf-self-check", b"entropy-a")
        result["dpapi_round_trip"] = protector.unprotect(blob, b"entropy-a") == b"dtf-self-check"
        try:
            protector.unprotect(blob, b"entropy-b")
            result["dpapi_binds_entropy"] = False
        except LicenseStoreError:
            result["dpapi_binds_entropy"] = True
    except Exception as error:
        result["dpapi_error"] = type(error).__name__
    try:
        from PySide6 import QtNetwork, QtWidgets  # noqa: F401
        from win32ctypes.pywin32 import win32cred  # noqa: F401
        result["qt_and_credential_manager_imports"] = True
    except Exception as error:
        result["import_error"] = type(error).__name__
    try:
        from dtf_manager.services.plans import load_plans
        result["plans_loaded"] = len(load_plans())
    except Exception as error:
        result["plans_error"] = type(error).__name__
    try:
        import os
        from dtf_manager.core import config
        from dtf_manager.core.release_check import release_problems
        result["release_problems"] = release_problems()
        # The packaged number must be readable without any environment override.
        saved = {k: os.environ.pop(k) for k in ("DTF_WHATSAPP_NUMBER", "DTF_SUPPORT_CONTACT")
                 if k in os.environ}
        try:
            packaged = config._app_config()
            result["packaged_whatsapp_read_without_env"] = bool(
                config.whatsapp_number()
                and config.whatsapp_number() == config.text_field(packaged, "whatsapp_numero"))
            result["packaged_support_read_without_env"] = bool(
                config.support_contact()
                and config.support_contact() == config.text_field(packaged, "contato_suporte")[:120])
        finally:
            os.environ.update(saved)
    except Exception as error:
        result["release_error"] = type(error).__name__
        result["release_problems"] = ["Não foi possível verificar a configuração de release."]
    result["ok"] = bool(
        not result.get("release_problems", ["erro"]) and
        result.get("packaged_whatsapp_read_without_env") and
        result.get("packaged_support_read_without_env") and
        result.get("plans_loaded", 0) >= 1 and
        result.get("machine_id_is_sha256_hex") and result.get("machine_id_stable")
        and len(result.get("machine_components", [])) >= 2
        and result.get("dpapi_round_trip") and result.get("dpapi_binds_entropy")
        and result.get("qt_and_credential_manager_imports"))
    return result


def run(path):
    result = collect()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    return 0 if result["ok"] else 1
