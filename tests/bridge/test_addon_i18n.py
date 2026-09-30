"""Language of the FreeCAD side (workbench, commands, dock panel)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bridge"))

from bridge_addon import i18n  # noqa: E402


class LanguageDetectionTest(unittest.TestCase):
    def test_deutsche_namen_und_locales(self):
        for name in ("de", "de_DE", "de-AT", "German", "Deutsch", " german "):
            self.assertTrue(i18n._is_german(name), name)

    def test_alles_andere_ist_englisch(self):
        for name in ("", None, "en", "en_US", "English", "dev", "French"):
            self.assertFalse(i18n._is_german(name), name)

    def test_leere_einstellung_faellt_auf_die_naechste_quelle_zurueck(self):
        """Without a chosen language, 'Language' is missing from user.cfg -- then
        the next source decides, not English across the board."""
        original = i18n._candidates
        try:
            i18n._candidates = lambda: iter(["", "de_DE"])
            self.assertEqual(i18n._language(), "de")
            i18n._candidates = lambda: iter(["", ""])
            self.assertEqual(i18n._language(), "en")
        finally:
            i18n._candidates = original


class TextsTest(unittest.TestCase):
    def test_jeder_text_hat_beide_sprachen(self):
        for key, texts in i18n.TEXTS.items():
            self.assertEqual(len(texts), 2, key)
            self.assertTrue(all(texts), key)

    def test_platzhalter(self):
        original = i18n.LANGUAGE
        try:
            i18n.LANGUAGE = "en"
            self.assertEqual(i18n.tr("panel.running_on", address="127.0.0.1:8765"), "running on 127.0.0.1:8765")
            i18n.LANGUAGE = "de"
            self.assertEqual(i18n.tr("panel.running_on", address="127.0.0.1:8765"), "läuft auf 127.0.0.1:8765")
        finally:
            i18n.LANGUAGE = original

    def test_unbekannter_schluessel_zeigt_sich_selbst(self):
        self.assertEqual(i18n.tr("gibt.es.nicht"), "gibt.es.nicht")


if __name__ == "__main__":
    unittest.main()
