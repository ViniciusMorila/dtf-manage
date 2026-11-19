import os
import unittest
from unittest.mock import patch

from dtf_manager.models.license import LicenseInfo, LicenseStatus, parse_timestamp
from dtf_manager.services.api_failure import ApiFailure
from dtf_manager.services.error_messages import describe, format_wait
from dtf_manager.services.session_storage import SessionStorage
from dtf_manager.utils.forms import (
    format_phone_mask, normalize_phone, validate_email, validate_name, validate_password)
from tests.license_fakes import license_data, status_body


class PhoneTests(unittest.TestCase):
    def test_equivalent_formats_normalize_to_digits(self):
        for text in ["(11) 91234-5678", "11912345678", "+55 11 91234-5678", "+5511912345678"]:
            with self.subTest(text=text):
                self.assertEqual(normalize_phone(text), "11912345678")

    def test_landline_and_invalid_numbers(self):
        self.assertEqual(normalize_phone("(11) 3123-4567"), "1131234567")
        for text in ["", "123", "(11) 81234-5678", "(11) 1234-5678", "(01) 91234-5678",
                     "(11) 91234-567", "119123456789", "abc"]:
            with self.subTest(text=text):
                self.assertIsNone(normalize_phone(text))

    def test_ddd_55_is_not_mistaken_for_the_country_code(self):
        self.assertEqual(normalize_phone("55912345678"), "55912345678")
        self.assertEqual(normalize_phone("+55 55 91234-5678"), "55912345678")

    def test_mask_is_progressive(self):
        steps = {"1": "(1", "11": "(11", "119": "(11) 9", "119123": "(11) 9123",
                 "1191234": "(11) 9123-4", "11912345678": "(11) 91234-5678",
                 "1131234567": "(11) 3123-4567", "119123456789999": "(11) 91234-5678", "": ""}
        for raw, masked in steps.items():
            with self.subTest(raw=raw):
                self.assertEqual(format_phone_mask(raw), masked)

    def test_mask_is_idempotent(self):
        self.assertEqual(format_phone_mask("(11) 91234-5678"), "(11) 91234-5678")


class FormValidationTests(unittest.TestCase):
    def test_name_email_password(self):
        self.assertIsNone(validate_name("Maria"))
        self.assertIsNotNone(validate_name(" "))
        self.assertIsNotNone(validate_name("x" * 201))
        self.assertIsNone(validate_email("maria@example.com"))
        for bad in ["", "maria", "maria@", "a b@c.com"]:
            self.assertIsNotNone(validate_email(bad))
        self.assertIsNone(validate_password("Exemplo123"))
        for bad in ["curta1", "somenteletras", "123456789", ""]:
            self.assertIsNotNone(validate_password(bad))


class LicenseModelTests(unittest.TestCase):
    def test_parses_the_contract_example_and_round_trips(self):
        info = LicenseInfo.from_dict(license_data())
        self.assertEqual((info.plano, info.status, info.plan_name, info.active),
                         ("MENSAL", "ATIVA", "Mensal", True))
        self.assertEqual(info.to_dict(), license_data())

    def test_lifetime_has_no_expiry(self):
        info = LicenseInfo.from_dict(license_data(plano="VITALICIO", data_expiracao=None,
                                                  dias_restantes=None, vitalicia=True))
        self.assertTrue(info.vitalicia)

    def test_malformed_licenses_are_rejected(self):
        for changes in [{"plano": "X"}, {"status": "ACTIVE"}, {"vitalicia": 1}, {"dias_restantes": -1},
                        {"dias_restantes": "3"}, {"data_expiracao": "nunca"}, {"data_ativacao": 5}]:
            with self.subTest(changes=changes):
                self.assertIsNone(LicenseInfo.from_dict(license_data(**changes)))
        self.assertIsNone(LicenseInfo.from_dict(None))
        self.assertIsNone(LicenseInfo.from_dict([]))

    def test_status_needs_a_valid_server_time(self):
        self.assertIsNotNone(LicenseStatus.from_response(status_body()))
        self.assertIsNone(LicenseStatus.from_response({"licenca": license_data()}))
        self.assertIsNone(LicenseStatus.from_response(status_body(server_now="amanhã")))

    def test_timestamps(self):
        self.assertEqual(parse_timestamp("2026-11-26T14:03:11.512345Z").microsecond, 512345)
        self.assertIsNone(parse_timestamp("x" * 100))


class MessageTests(unittest.TestCase):
    def test_every_contract_code_has_portuguese_text(self):
        for code in ["LICENCA_EXPIRADA", "LICENCA_BLOQUEADA", "MAQUINA_DIFERENTE", "MAQUINA_EM_USO",
                     "TESTE_JA_UTILIZADO", "CHAVE_INVALIDA", "LIMITE_RESETS", "TELEFONE_INVALIDO",
                     "LICENCA_NAO_ENCONTRADA", "LICENCA_JA_VITALICIA", "LICENCA_INDISPONIVEL",
                     "ID_MAQUINA_INVALIDO", "INVALID_CREDENTIALS", "INVALID_ACCESS_TOKEN",
                     "INVALID_REFRESH_TOKEN", "WEAK_PASSWORD", "EMAIL_ALREADY_EXISTS"]:
            with self.subTest(code=code):
                text = describe(ApiFailure("api", code, "SERVER-TEXT"))
                self.assertNotIn("SERVER-TEXT", text)
                self.assertTrue(text)

    def test_network_errors(self):
        for kind, text in [("network", "conectar"), ("timeout", "demorou"), ("server", "indisponível")]:
            self.assertIn(text, describe(ApiFailure(kind)))

    def test_unknown_code_uses_server_message_then_generic(self):
        self.assertEqual(describe(ApiFailure("api", "NOVO", "Texto novo.")), "Texto novo.")
        self.assertIn("indisponível", describe(ApiFailure("api", "NOVO")))

    def test_retry_after_formatting(self):
        self.assertEqual(format_wait(1), "1 segundo")
        self.assertEqual(format_wait(59), "59 segundos")
        self.assertEqual(format_wait(61), "2 minutos")
        self.assertEqual(format_wait(3540), "59 minutos")
        self.assertEqual(format_wait(3600), "1 hora")
        self.assertEqual(format_wait(3601), "2 horas")

    def test_failure_classification(self):
        from dtf_manager.services.api_client import ApiResult
        cases = [(ApiResult(error="network"), "network", True), (ApiResult(502, error="http"), "server", True),
                 (ApiResult(503, error="http", error_code="LICENCA_INDISPONIVEL"), "server", False),
                 (ApiResult(429, error="http"), "rate_limited", False),
                 (ApiResult(403, error="http"), "api", False), (ApiResult(401, error="http"), "unauthorized", False)]
        for result, kind, unreachable in cases:
            with self.subTest(status=result.status, kind=kind):
                failure = ApiFailure.from_result(result)
                self.assertEqual((failure.kind, failure.unreachable), (kind, unreachable))


class CredentialTargetTests(unittest.TestCase):
    def test_target_does_not_depend_on_the_url_of_production(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(SessionStorage().target, "DTF Manager/session/production")

    def test_custom_api_gets_its_own_scope(self):
        with patch.dict(os.environ, {"DTF_API_URL": "http://localhost:8000"}, clear=True):
            local = SessionStorage().target
        self.assertTrue(local.startswith("DTF Manager/session/dev-"))
        self.assertNotIn("localhost", local)
        self.assertNotEqual(local, "DTF Manager/session/production")


if __name__ == "__main__":
    unittest.main()
