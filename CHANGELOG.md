# Changelog

Jede Aenderung an `cad_contract` bumpt `CONTRACT_VERSION` und bekommt hier eine
Zeile. Die Mismatch-Meldung des Backends verweist auf diese Datei.

## cad_contract 0.3.0 -- 2026-09-25

- Neues Modul `events.py`: Ereignis-Vokabular (cad.*, doc.*), Herkunft
  (`freecad:user` / `bridge:<request-id>`), Menge `FULL_RELOAD`.
- WebSocket liefert Ereignisse gebuendelt: ein Frame `{"type": "events", ...}` pro Flush.

## cad_contract 0.2.0 -- 2026-09-25

- Wertformat `types.py`: encoded / derived / unsupported, kein str()-Fallback.
- Quantity traegt `unit` (Symbol, z. B. "mm") und `unitType` ("Length") statt FreeCADs repr.
- Objekte tragen `rev` (monotoner Zaehler pro Objekt).
- Schreibantwort: `status`, `atomic`, `changed`, `applied`, `unchanged`, `recomputed`, `errors`, `rev`.

## cad_contract 0.1.0 -- 2026-09-11

- Erste Fassung: `CONTRACT_VERSION`.
