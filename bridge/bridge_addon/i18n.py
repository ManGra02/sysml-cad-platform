"""Texts of the bridge's FreeCAD UI (workbench, commands, dock panel).

English is the default. German only if FreeCAD itself runs in German --
the panel should match the language of the UI it lives in.

Which language FreeCAD displays is NOT reliably stored in the preferences:
if no language was ever chosen there, the "Language" entry is missing
entirely, and FreeCAD uses the system language (verified: user.cfg without
the entry, Windows set to de-DE). Hence, in order:
  1. FreeCADGui.getLocale() -- what FreeCAD actually activated
  2. the "Language" entry in the preferences ("German")
  3. the system language (QLocale)

Deliberately a small dictionary instead of Qt .ts/.qm files: it is a few
dozen texts, and a translation build for the addon is not worth it.
The language is fixed at load time; FreeCAD requires a restart for a
language change anyway.
"""

import FreeCAD

_GENERAL = "User parameter:BaseApp/Preferences/General"

TEXTS = {
    "workbench.menu": ("SysML-CAD Bridge", "SysML-CAD Brücke"),
    "workbench.tooltip": (
        "Provides the CAD model to the SysML-CAD platform (local only)",
        "Stellt das CAD-Modell für die SysML-CAD-Plattform bereit (nur lokal)",
    ),
    "cmd.start": ("Start bridge", "Brücke starten"),
    "cmd.start.tip": (
        "Starts the local service through which the platform accesses the CAD model",
        "Startet den lokalen Dienst, über den die Plattform auf das CAD-Modell zugreift",
    ),
    "cmd.stop": ("Stop bridge", "Brücke stoppen"),
    "cmd.stop.tip": (
        "Stops the local service and removes observer, thread and handshake file",
        "Beendet den lokalen Dienst und räumt Observer, Thread und Handshake-Datei ab",
    ),
    "cmd.open": ("Open user interface", "Oberfläche öffnen"),
    "cmd.open.tip": (
        "Opens the platform user interface in the default browser",
        "Öffnet die Plattform-Oberfläche im Standardbrowser",
    ),
    "cmd.panel": ("Show status panel", "Status-Panel zeigen"),
    "cmd.panel.tip": ("Shows the bridge status panel again", "Blendet das Status-Panel der Brücke wieder ein"),
    "panel.title": ("SysML-CAD Bridge", "SysML-CAD Brücke"),
    "panel.bridge": ("Bridge", "Brücke"),
    "panel.connected": ("connected", "verbunden"),
    "panel.stopped": ("stopped", "gestoppt"),
    "panel.error": ("error", "Fehler"),
    "panel.running_on": ("running on {address}", "läuft auf {address}"),
    "panel.shutting_down": ("shutting down …", "wird beendet …"),
    "panel.access": ("Access", "Zugang"),
    "panel.address": ("Address", "Adresse"),
    "panel.copy": ("Copy", "Kopieren"),
    "panel.copied": ("Copied", "Kopiert"),
    "panel.start": ("Start", "Starten"),
    "panel.stop": ("Stop", "Stoppen"),
    "panel.open": ("Open user interface", "Oberfläche öffnen"),
    "fail.start": ("Starting the bridge", "Start der Brücke"),
    "fail.stop": ("Stopping the bridge", "Stoppen der Brücke"),
    "fail.browser": ("Opening the browser", "Öffnen des Browsers"),
    "fail.panel": ("Showing the panel", "Anzeigen des Panels"),
    "failed": ("{what} failed: {error}", "{what} fehlgeschlagen: {error}"),
}


def _is_german(name):
    """'de', 'de_DE', 'de-AT', 'German', 'Deutsch' -> True."""
    name = (name or "").strip().lower()
    return name in ("german", "deutsch") or name == "de" or name.startswith(("de_", "de-"))


def _candidates():
    try:
        import FreeCADGui

        yield FreeCADGui.getLocale()
    except Exception:
        pass  # headless: FreeCADGui is a stub without getLocale
    try:
        yield FreeCAD.ParamGet(_GENERAL).GetString("Language", "")
    except Exception:
        pass
    try:
        from PySide import QtCore

        yield QtCore.QLocale.system().name()
    except Exception:
        pass


def _language():
    """The first source that returns anything at all decides."""
    for name in _candidates():
        if name:
            return "de" if _is_german(name) else "en"
    return "en"


LANGUAGE = _language()


def tr(key, **params):
    """Text in FreeCAD's language; unknown keys display themselves."""
    english, german = TEXTS.get(key, (key, key))
    text = german if LANGUAGE == "de" else english
    return text.format(**params) if params else text
