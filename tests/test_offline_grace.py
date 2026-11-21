from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from dtf_manager.models.license import LicenseInfo, LicenseStatus, format_timestamp
from dtf_manager.services.license_store import (
    DpapiProtector, LicenseSnapshot, LicenseStore, LicenseStoreError)
from dtf_manager.services.offline_grace import GRACE_PERIOD, OfflineGrace
from tests.session_fakes import FakeLicenseStore

T0 = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
MACHINE = "a" * 64


def license_dict(**changes):
    data = {"plano": "MENSAL", "status": "ATIVA", "data_ativacao": "2026-11-19T18:00:00Z",
            "data_expiracao": "2026-12-26T18:00:00Z", "dias_restantes": 37, "vitalicia": False}
    data.update(changes)
    return data


def status(server_now=T0, **changes):
    return LicenseStatus(LicenseInfo.from_dict(license_dict(**changes)), format_timestamp(server_now))


class Clock:
    def __init__(self, now=T0):
        self.now, self.mono = now, 1000.0

    def __call__(self):
        return self.now

    def monotonic(self):
        return self.mono

    def advance(self, **delta):
        step = timedelta(**delta)
        self.now += step
        self.mono += step.total_seconds()


class OfflineGraceTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = FakeLicenseStore()
        self.grace = OfflineGrace(self.store, clock=self.clock, monotonic=self.clock.monotonic)

    def test_no_cache_has_no_grace(self):
        self.assertEqual(self.grace.evaluate().reason, "no_cache")

    def test_inside_72_hours_is_allowed_with_remaining_time(self):
        self.grace.record_success(status())
        self.clock.advance(hours=71)
        decision = self.grace.evaluate()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.remaining, timedelta(hours=1))
        self.assertEqual(decision.info.plano, "MENSAL")

    def test_outside_72_hours_requires_connection(self):
        self.grace.record_success(status())
        self.clock.advance(hours=72)
        decision = self.grace.evaluate()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "grace_exhausted")

    def test_grace_survives_restart_using_persisted_validation(self):
        self.grace.record_success(status())
        clock2 = Clock(T0 + timedelta(hours=10))
        restarted = OfflineGrace(self.store, clock=clock2, monotonic=clock2.monotonic)
        self.assertTrue(restarted.evaluate().allowed)
        clock2.advance(hours=63)
        self.assertEqual(restarted.evaluate().reason, "grace_exhausted")

    def test_clock_set_back_in_the_same_process_does_not_extend_grace(self):
        self.grace.record_success(status())
        self.clock.advance(hours=60)
        self.clock.now -= timedelta(hours=40)  # user rewinds the clock, monotonic keeps going
        decision = self.grace.evaluate()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "clock_rolled_back")

    def test_clock_set_back_across_restart_is_detected_by_high_water(self):
        self.grace.record_success(status())
        self.clock.advance(hours=30)
        self.assertTrue(self.grace.evaluate().allowed)  # raises the persisted high-water mark
        clock2 = Clock(T0 + timedelta(hours=5))          # restart after rewinding the clock
        restarted = OfflineGrace(self.store, clock=clock2, monotonic=clock2.monotonic)
        self.assertEqual(restarted.evaluate().reason, "clock_rolled_back")

    def test_clock_behind_last_server_time_is_not_trusted(self):
        self.grace.record_success(status(server_now=T0 + timedelta(hours=3)))
        self.assertEqual(self.grace.evaluate().reason, "clock_rolled_back")

    def test_small_clock_differences_are_tolerated(self):
        self.grace.record_success(status(server_now=T0 + timedelta(minutes=2)))
        self.clock.advance(minutes=1)
        self.clock.now -= timedelta(minutes=2)
        self.assertTrue(self.grace.evaluate().allowed)

    def test_license_that_expires_during_the_grace_is_not_released(self):
        self.grace.record_success(status(data_expiracao=format_timestamp(T0 + timedelta(hours=10))))
        self.clock.advance(hours=11)
        self.assertEqual(self.grace.evaluate().reason, "expired")

    def test_lifetime_license_has_no_expiry_but_keeps_the_72_hour_limit(self):
        self.grace.record_success(status(plano="VITALICIO", data_expiracao=None,
                                         dias_restantes=None, vitalicia=True))
        self.clock.advance(hours=71)
        self.assertTrue(self.grace.evaluate().allowed)
        self.clock.advance(hours=2)
        self.assertEqual(self.grace.evaluate().reason, "grace_exhausted")

    def test_inactive_cached_license_never_gets_grace(self):
        self.grace.record_success(status(status="EXPIRADA", dias_restantes=0))
        self.assertEqual(self.grace.evaluate().reason, "not_active")

    def test_unreadable_cache_means_no_grace(self):
        self.grace.record_success(status())
        self.store.fail_load = True
        self.assertEqual(self.grace.evaluate().reason, "no_cache")

    def test_cache_write_failure_does_not_break_a_confirmed_validation(self):
        self.store.fail_save = True
        self.grace.record_success(status())  # must not raise
        self.assertEqual(self.grace.evaluate().reason, "no_cache")

    def test_clear_removes_cache(self):
        self.grace.record_success(status())
        self.grace.clear()
        self.assertEqual(self.grace.evaluate().reason, "no_cache")
        self.assertEqual(self.store.deletions, 1)

    def test_contact_is_remembered_merged_and_survives_revalidation(self):
        self.grace.record_success(status(), {"email": "a@b.com", "name": "Ana"})
        self.assertEqual(self.grace.contact(), {"email": "a@b.com", "name": "Ana"})
        self.grace.record_success(status(), {"phone": "11912345678", "name": ""})
        self.assertEqual(self.grace.contact(), {"email": "a@b.com", "name": "Ana", "phone": "11912345678"})
        self.grace.record_success(status())
        self.assertEqual(self.grace.contact()["email"], "a@b.com")
        self.clock.advance(hours=1)
        self.assertTrue(self.grace.evaluate().allowed)           # high-water update keeps it
        self.assertEqual(self.grace.contact()["name"], "Ana")
        self.grace.clear()
        self.assertEqual(self.grace.contact(), {})

    def test_grace_period_constant_is_72_hours(self):
        self.assertEqual(GRACE_PERIOD, timedelta(hours=72))


class ReversibleProtector:
    """Test double that binds data to the entropy, like the DPAPI optional entropy."""

    def protect(self, data, entropy):
        return hashlib.sha256(entropy).digest() + data[::-1]

    def unprotect(self, blob, entropy):
        if blob[:32] != hashlib.sha256(entropy).digest():
            raise LicenseStoreError("wrong entropy")
        return blob[32:][::-1]


class LicenseStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "license_cache.bin"
        self.snapshot = LicenseSnapshot(status().info, format_timestamp(T0),
                                        format_timestamp(T0), format_timestamp(T0))

    def store(self, machine=MACHINE, protector=None):
        return LicenseStore(machine, path=self.path, protector=protector or ReversibleProtector())

    def test_round_trip_and_delete(self):
        self.store().save(self.snapshot)
        self.assertEqual(self.store().load(), self.snapshot)
        self.store().delete()
        self.assertIsNone(self.store().load())
        self.store().delete()  # idempotent

    def test_file_is_not_plain_text(self):
        self.store().save(self.snapshot)
        raw = self.path.read_bytes()
        for text in [b"MENSAL", b"ATIVA", MACHINE.encode()]:
            self.assertNotIn(text, raw)

    def test_other_machine_cannot_read_the_cache(self):
        self.store().save(self.snapshot)
        self.assertIsNone(self.store("b" * 64).load())

    def test_corrupt_or_tampered_cache_is_ignored(self):
        self.store().save(self.snapshot)
        self.path.write_bytes(self.path.read_bytes()[:-3] + b"xyz")
        self.assertIsNone(self.store().load())
        self.path.write_bytes(b"")
        self.assertIsNone(self.store().load())

    def test_contact_round_trips_and_unknown_keys_are_dropped(self):
        snap = LicenseSnapshot(status().info, format_timestamp(T0), format_timestamp(T0),
                               format_timestamp(T0), {"email": "a@b.com", "senha": "x"})
        self.store().save(snap)
        self.assertEqual(self.store().load().contact, {"email": "a@b.com"})

    def test_machine_id_provider_may_be_callable(self):
        store = LicenseStore(lambda: MACHINE, path=self.path, protector=ReversibleProtector())
        store.save(self.snapshot)
        self.assertEqual(store.load(), self.snapshot)

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows only")
    def test_real_dpapi_round_trip_binds_to_machine_id(self):
        real = DpapiProtector()
        self.store(protector=real).save(self.snapshot)
        self.assertEqual(self.store(protector=real).load(), self.snapshot)
        self.assertNotIn(b"MENSAL", self.path.read_bytes())
        self.assertIsNone(self.store("b" * 64, protector=real).load())


if __name__ == "__main__":
    unittest.main()
