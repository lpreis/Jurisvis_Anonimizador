from __future__ import annotations

import unittest

from anonymizer_core import ReversibleAnonymizer, is_valid_iban, is_valid_luhn, is_valid_pt_tax_id


class ReversibleAnonymizerTests(unittest.TestCase):
    def test_anonymizes_and_deanonymizes_legal_text(self) -> None:
        text = (
            "O Dr. Joao Silva, NIF 123456789, residente na Rua da Prata n.o 10, "
            "1100-420 Lisboa, intentou acao contra ABC Lda no Processo n.o "
            "1234/24.3T8LSB. Contacto: joao@example.com, 912345678."
        )

        anonymizer = ReversibleAnonymizer()
        anonymized, matches = anonymizer.anonymize(text)

        self.assertIn("[PESSOA_1]", anonymized)
        self.assertIn("[NIF_1]", anonymized)
        self.assertIn("[LOCALIZACAO_1]", anonymized)
        self.assertIn("[ORGANIZACAO_1]", anonymized)
        self.assertIn("[PROCESSO_1]", anonymized)
        self.assertIn("[EMAIL_1]", anonymized)
        self.assertIn("[TELEFONE_1]", anonymized)
        self.assertGreaterEqual(len(matches), 7)
        self.assertEqual(anonymizer.deanonymize(anonymized), text)

    def test_reuses_token_for_canonical_equivalent_values(self) -> None:
        anonymizer = ReversibleAnonymizer()
        first = anonymizer.add_manual_entity("ABC, Lda.", "ORGANIZACAO")
        second = anonymizer.add_manual_entity("ABC Lda", "ORGANIZACAO")

        self.assertEqual(first, second)

    def test_deanonymizes_token_aliases(self) -> None:
        anonymizer = ReversibleAnonymizer()
        token = anonymizer.add_manual_entity("Joao Silva", "PESSOA")

        self.assertEqual(token, "[PESSOA_1]")
        self.assertEqual(anonymizer.deanonymize("Autor: [PERSON 1]"), "Autor: Joao Silva")

    def test_unresolved_tokens(self) -> None:
        anonymizer = ReversibleAnonymizer()
        anonymizer.add_manual_entity("Joao Silva", "PESSOA")

        self.assertEqual(anonymizer.unresolved_tokens("[PESSOA_1] e [PESSOA_2]"), ["[PESSOA_2]"])

    def test_manual_replacement_updates_text(self) -> None:
        anonymizer = ReversibleAnonymizer()
        updated, token = anonymizer.replace_manual_entity("Autor Joao Silva.", "Joao Silva", "PESSOA")

        self.assertEqual(token, "[PESSOA_1]")
        self.assertEqual(updated, "Autor [PESSOA_1].")
        self.assertEqual(anonymizer.deanonymize(updated), "Autor Joao Silva.")


class ValidationTests(unittest.TestCase):
    def test_validates_pt_tax_ids(self) -> None:
        self.assertTrue(is_valid_pt_tax_id("123456789"))
        self.assertTrue(is_valid_pt_tax_id("500000000"))
        self.assertFalse(is_valid_pt_tax_id("123456780"))

    def test_validates_iban(self) -> None:
        self.assertTrue(is_valid_iban("PT50 0002 0123 1234 5678 9015 4"))
        self.assertFalse(is_valid_iban("PT50 0002 0123 1234 5678 9015 5"))

    def test_validates_credit_card_luhn(self) -> None:
        self.assertTrue(is_valid_luhn("4111 1111 1111 1111"))
        self.assertFalse(is_valid_luhn("4111 1111 1111 1112"))


if __name__ == "__main__":
    unittest.main()
