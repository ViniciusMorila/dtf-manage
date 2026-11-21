import re
import sys
import unittest
import uuid
from unittest.mock import patch

from dtf_manager.core import config
from dtf_manager.services import machine_id as mid


def structure(kind, formatted_len, fields, strings=()):
    body = bytearray(formatted_len)
    body[0], body[1] = kind, formatted_len
    for offset, data in fields.items():
        body[offset:offset + len(data)] = data
    text = b"".join(s.encode() + b"\x00" for s in strings)
    return bytes(body) + (text + b"\x00" if strings else b"\x00\x00")


def smbios_table(*, board="BOARD-SER-001", system_uuid=None, cpu=b"\x01\x02\x03\x04\xff\xfb\x8b\x17"):
    system_uuid = system_uuid or uuid.UUID("11112222-3333-4444-5555-666677778888")
    return (
        structure(1, 0x1B, {8: system_uuid.bytes_le, 7: b"\x01"}, ["SYS-SERIAL"])
        + structure(2, 0x0F, {7: b"\x01" if board is not None else b"\x00"},
                    [board] if board is not None else [])
        + structure(4, 0x30, {8: cpu, 0x18: b"\x41"}, ["CPU"])
        + structure(127, 4, {})
    )


def smbios_reader(**kwargs):
    return lambda: smbios_table(**kwargs)


class MachineIdTests(unittest.TestCase):
    def setUp(self):
        mid.reset_cache()
        self.addCleanup(mid.reset_cache)

    def test_components_parse_board_uuid_and_cpu(self):
        parts = mid.smbios_components(smbios_table())
        self.assertEqual(parts["board"], "BOARD-SER-001")
        self.assertEqual(parts["uuid"], "11112222-3333-4444-5555-666677778888")
        self.assertEqual(parts["cpu"], "178bfbff04030201")

    def test_id_is_stable_hex_sha256_and_valid_for_the_api(self):
        build = lambda: mid.build_machine_id(smbios_reader=smbios_reader(), disk_reader=lambda: "DISK123456")
        first, second = build(), build()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        # Contract: 8-128 chars from a-z 0-9 . _ : { } -
        self.assertRegex(first, r"^[a-z0-9._:{}-]{8,128}$")

    def test_raw_serial_numbers_never_appear_in_the_id(self):
        value = mid.build_machine_id(smbios_reader=smbios_reader(), disk_reader=lambda: "DISK123456")
        for raw in ["board-ser-001", "disk123456", "11112222"]:
            self.assertNotIn(raw, value)

    def test_any_component_change_changes_the_id(self):
        base = mid.build_machine_id(smbios_reader=smbios_reader(), disk_reader=lambda: "DISK123456")
        other_disk = mid.build_machine_id(smbios_reader=smbios_reader(), disk_reader=lambda: "OTHERDISK9")
        other_board = mid.build_machine_id(smbios_reader=smbios_reader(board="BOARD-SER-002"),
                                           disk_reader=lambda: "DISK123456")
        self.assertEqual(len({base, other_disk, other_board}), 3)

    def test_generic_values_are_discarded(self):
        for value in ["To be filled by O.E.M.", "Default string", "None", "N/A", "0", "00000000",
                      "0000-0000-0000", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "System Serial Number",
                      "Not Specified", "123456789", "", "   ", None, "xxxxxxxx", "O.E.M."]:
            with self.subTest(value=value):
                self.assertIsNone(mid.clean_component(value))
        self.assertEqual(mid.clean_component("  abc-123  "), "ABC-123")

    def test_generic_board_leaves_other_components(self):
        components = mid.collect_components(
            smbios_reader=smbios_reader(board="To be filled by O.E.M."), disk_reader=lambda: "DISK123456")
        self.assertEqual(sorted(components), ["cpu", "disk", "uuid"])

    def test_zero_uuid_is_ignored(self):
        parts = mid.smbios_components(smbios_table(system_uuid=uuid.UUID(int=0)))
        self.assertNotIn("uuid", parts)

    def test_hardware_read_failure_with_two_components_still_works(self):
        def failing_disk():
            raise OSError("no disk")
        self.assertRegex(mid.build_machine_id(smbios_reader=smbios_reader(), disk_reader=failing_disk),
                         r"^[0-9a-f]{64}$")

    def test_fewer_than_two_components_is_refused_without_mac_or_machine_guid(self):
        def failing():
            raise OSError("unreadable")
        with self.assertRaises(mid.MachineIdError) as raised:
            mid.build_machine_id(smbios_reader=failing, disk_reader=failing)
        self.assertIn("suporte", str(raised.exception))
        with self.assertRaises(mid.MachineIdError):
            mid.build_machine_id(smbios_reader=smbios_reader(board=None, system_uuid=uuid.UUID(int=0),
                                                            cpu=b"\x00" * 8),
                                 disk_reader=lambda: "DISK123456")

    def test_truncated_or_garbage_table_never_raises_outside_machine_id_error(self):
        for table in [b"", b"\x01", b"\x01\xff\x00", bytes(range(40))]:
            with self.subTest(table=table):
                with self.assertRaises(mid.MachineIdError):
                    mid.build_machine_id(smbios_reader=lambda t=table: t,
                                         disk_reader=lambda: (_ for _ in ()).throw(OSError()))

    def test_id_is_computed_once_per_process(self):
        with patch.object(mid, "build_machine_id", return_value="a" * 64) as build:
            self.assertEqual(mid.get_machine_id(), "a" * 64)
            self.assertEqual(mid.get_machine_id(), "a" * 64)
            build.assert_called_once()

    def test_no_forbidden_sources_in_module(self):
        with open(mid.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ["MachineGuid", "uuid.getnode", "subprocess", "winreg", "getmac"]:
            self.assertNotIn(forbidden, source)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_real_hardware_read_is_stable_and_hashed(self):
        first, second = mid.build_machine_id(), mid.build_machine_id()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")


class ConfigTests(unittest.TestCase):
    def test_default_url_and_environment(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.api_base_url(), config.DEFAULT_API_URL)
            self.assertEqual(config.environment_name(), "production")

    def test_custom_urls_and_scoped_environment(self):
        with patch.dict("os.environ", {"DTF_API_URL": "http://localhost:8000/"}, clear=True):
            self.assertEqual(config.api_base_url(), "http://localhost:8000")
            self.assertRegex(config.environment_name(), r"^dev-[0-9a-f]{8}$")
        with patch.dict("os.environ", {"DTF_API_URL": "https://api.example.com"}, clear=True):
            self.assertEqual(config.api_base_url(), "https://api.example.com")

    def test_insecure_or_malformed_urls_are_rejected(self):
        for value in ["http://api.example.com", "ftp://x", "api.example.com", "https://u:p@x.com",
                      "https://"]:
            with self.subTest(value=value), patch.dict("os.environ", {"DTF_API_URL": value}, clear=True):
                with self.assertRaises(config.ConfigError):
                    config.api_base_url()

    def test_payment_url_is_optional_and_https_only(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(config.payment_url())
        with patch.dict("os.environ", {"DTF_PAYMENT_URL": "https://pay.example.com/x"}, clear=True):
            self.assertEqual(config.payment_url(), "https://pay.example.com/x")
        with patch.dict("os.environ", {"DTF_PAYMENT_URL": "javascript:alert(1)"}, clear=True):
            self.assertIsNone(config.payment_url())

    def test_no_auth_requires_explicit_variable(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(config.no_auth_allowed())
        with patch.dict("os.environ", {"DTF_ALLOW_NO_AUTH": "1"}, clear=True):
            self.assertTrue(config.no_auth_allowed())
        with patch.dict("os.environ", {"DTF_ALLOW_NO_AUTH": "true"}, clear=True):
            self.assertFalse(config.no_auth_allowed())


if __name__ == "__main__":
    unittest.main()
