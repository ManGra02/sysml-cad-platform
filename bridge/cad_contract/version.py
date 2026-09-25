"""Vertragsversion zwischen Bruecke und Backend.

Wird beim Handshake verglichen. Passt sie nicht, meldet das Backend das
deutlich, statt an unerwarteten Feldern zu scheitern -- der wahrscheinlichste
Fehler bei zwei getrennt deployten Prozessen.

REGEL: Jede Aenderung an types.py oder events.py bumpt diese Version UND
traegt eine Zeile in CHANGELOG.md ein, auf die die Mismatch-Meldung verweist.
"""

CONTRACT_VERSION = "0.3.0"
