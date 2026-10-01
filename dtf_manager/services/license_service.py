from PySide6.QtCore import QObject, Signal

from dtf_manager.services.auth_service import failure_kind


class LicenseService(QObject):
    checked = Signal(bool, str, str)
    failed = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._generation = 0

    def cancel(self):
        self._generation += 1

    def check(self, access_token):
        self._generation += 1
        generation = self._generation

        def completed(result):
            if generation != self._generation:
                return
            if result.error or not 200 <= result.status < 300:
                self.failed.emit(failure_kind(result))
                return
            data = result.data or {}
            active, status = data.get("active"), data.get("status")
            if not isinstance(active, bool) or not isinstance(status, str):
                self.failed.emit("invalid_json")
                return
            plan = data.get("plan")
            name = plan.get("name", "") if isinstance(plan, dict) else ""
            self.checked.emit(active is True and status == "ACTIVE", status,
                              name if isinstance(name, str) else "")

        self.client.get("/license/status", completed, access_token=access_token)
