"""In-memory test doubles. Never access the user credential store, DPAPI or disk."""
from dtf_manager.services.license_store import LicenseStoreError
from dtf_manager.services.session_storage import SessionStorageError

MACHINE_ID = "a" * 64


class FakeSessionStorage:
    def __init__(self, token=None):
        self.token = token
        self.saved = []
        self.deletions = 0
        self.fail_save = False
        self.fail_load = False
        self.fail_delete = False
        self.lock_available = True
        self.lock_released = False

    def acquire_session_lock(self):
        return self.lock_available

    def release_session_lock(self):
        self.lock_released = True

    def load_refresh_token(self):
        if self.fail_load:
            raise SessionStorageError("Fake storage read error")
        return self.token

    def save_refresh_token(self, token):
        if self.fail_save:
            raise SessionStorageError("Fake storage write error")
        self.token = token
        self.saved.append(token)

    def delete_refresh_token(self):
        if self.fail_delete:
            raise SessionStorageError("Fake storage delete error")
        self.token = None
        self.deletions += 1


class FakeLicenseStore:
    """In-memory license cache."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.saves = 0
        self.deletions = 0
        self.fail_save = False
        self.fail_load = False

    def save(self, snapshot):
        if self.fail_save:
            raise LicenseStoreError("Fake cache write error")
        self.snapshot = snapshot
        self.saves += 1

    def load(self):
        if self.fail_load:
            raise LicenseStoreError("Fake cache read error")
        return self.snapshot

    def delete(self):
        self.snapshot = None
        self.deletions += 1
