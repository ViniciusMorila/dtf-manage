import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from dtf_manager.core import config
from dtf_manager.services import plans as plans_module
from dtf_manager.services.plans import Plan, PlansError, load_plans, parse_plans
from dtf_manager.services.whatsapp import build_message, build_url

ANUAL = Plan("ANUAL", "Anual", "12 meses", "R$ 449,90", "Mais vantajoso", True)


def plan_item(**changes):
    item = {"codigo": "MENSAL", "nome": "Mensal", "duracao": "1 mês", "preco": "R$ 1,00"}
    item.update(changes)
    return item


class PlansTests(unittest.TestCase):
    def test_bundled_file_has_the_four_plans_with_the_annual_one_highlighted(self):
        loaded = load_plans()
        self.assertEqual([p.code for p in loaded], ["MENSAL", "SEMESTRAL", "ANUAL", "VITALICIO"])
        self.assertEqual([p.code for p in loaded if p.highlight], ["ANUAL"])
        self.assertEqual(next(p for p in loaded if p.code == "ANUAL").highlight, "Mais vantajoso")

    def test_no_invented_discount_text(self):
        text = (Path(plans_module.__file__).parents[1] / "data" / "planos.json").read_text(encoding="utf-8")
        self.assertNotIn("%", text)
        self.assertNotIn("desconto", text.lower())

    def test_custom_file_through_environment(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "p.json"
            path.write_text(json.dumps({"exemplo": False, "planos": [plan_item(preco="R$ 9,00")]}),
                            encoding="utf-8")
            with patch.dict(os.environ, {"DTF_PLANS_FILE": str(path)}):
                loaded = load_plans()
        self.assertEqual((loaded[0].price, loaded[0].example), ("R$ 9,00", False))

    def test_invalid_files_are_rejected(self):
        for data in [[], {}, {"planos": []}, {"planos": [plan_item(codigo="OUTRO")]},
                     {"planos": [plan_item(), plan_item()]}, {"planos": [plan_item(preco="")]},
                     {"planos": [plan_item(nome=5)]}, {"planos": ["x"]}]:
            with self.subTest(data=data), self.assertRaises(PlansError):
                parse_plans(data)

    def test_missing_or_corrupt_file(self):
        with TemporaryDirectory() as folder:
            bad = Path(folder) / "bad.json"
            bad.write_text("{nope", encoding="utf-8")
            for path in [bad, Path(folder) / "missing.json"]:
                with self.subTest(path=path.name), self.assertRaises(PlansError):
                    load_plans(path)


class WhatsappConfigTests(unittest.TestCase):
    def setUp(self):
        missing = patch.object(config, "APP_CONFIG_FILE", Path("nonexistent-app-config.json"))
        missing.start()
        self.addCleanup(missing.stop)

    def test_number_must_be_international_digits(self):
        for value, expected in [("5511999999999", "5511999999999"), (" 5511999999999 ", "5511999999999"),
                                ("", None), ("+5511999999999", None), ("11 99999-9999", None),
                                ("123", None), ("5" * 16, None), ("55119999999a", None)]:
            with self.subTest(value=value), patch.dict(os.environ, {"DTF_WHATSAPP_NUMBER": value}, clear=True):
                self.assertEqual(config.whatsapp_number(), expected)

    def test_there_is_no_builtin_number(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(config.whatsapp_number())


class MessageTests(unittest.TestCase):
    def test_message_with_session_data(self):
        text = build_message(ANUAL, name="Maria Silva", email="maria@example.com", phone="11912345678")
        self.assertEqual(text, "Olá! Quero assinar o Layera. Plano: Anual (R$ 449,90). "
                               "Nome: Maria Silva. E-mail da conta: maria@example.com. "
                               "Telefone: 11912345678.")

    def test_message_without_session_asks_for_the_email_in_the_chat(self):
        text = build_message(ANUAL)
        self.assertIn("Plano: Anual (R$ 449,90)", text)
        self.assertIn("vou informar aqui na conversa", text)
        self.assertNotIn("Nome:", text)
        self.assertNotIn("Telefone:", text)

    def test_partial_data_only_includes_what_is_known(self):
        text = build_message(ANUAL, email="a@b.com")
        self.assertIn("E-mail da conta: a@b.com.", text)
        self.assertNotIn("Nome:", text)

    def test_control_characters_are_removed(self):
        text = build_message(ANUAL, name="Ana\r\nSilva\x00", email="a@b.com")
        self.assertNotIn("\n", text)
        self.assertNotIn("\x00", text)

    def test_never_contains_secrets(self):
        text = build_message(ANUAL, name="Maria", email="maria@example.com", phone="11912345678")
        for forbidden in ["senha", "token", "id_maquina", "Bearer", "a" * 64]:
            self.assertNotIn(forbidden, text.lower() if forbidden.islower() else text)


class UrlTests(unittest.TestCase):
    def test_url_is_wa_me_with_percent_encoded_text(self):
        message = build_message(ANUAL, name="João & Cia", email="joao+x@example.com")
        url = build_url("5511999999999", message)
        self.assertTrue(url.startswith("https://wa.me/5511999999999?text="))
        encoded = url.split("?text=", 1)[1]
        for raw in [" ", "&", "+", "@", "á", "(", ")", "R$"]:
            self.assertNotIn(raw, encoded)
        self.assertIn("%20", encoded)
        self.assertEqual(parse_qs(urlsplit(url).query)["text"], [message])

    def test_round_trip_keeps_accents_and_reserved_characters(self):
        message = "Olá! Plano: Vitalício (R$ 1.299,00). E-mail: a+b@c.com?x=1&y=2#z"
        url = build_url("5511999999999", message)
        self.assertEqual(parse_qs(urlsplit(url).query)["text"], [message])
        self.assertEqual(urlsplit(url).fragment, "")


if __name__ == "__main__":
    unittest.main()
