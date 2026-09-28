# Changelog

Jede Aenderung an `cad_contract` bumpt `CONTRACT_VERSION` und bekommt hier eine
Zeile. Die Mismatch-Meldung des Backends verweist auf diese Datei.

## cad_contract 0.5.0 -- 2026-09-28

- `POST /api/cad/documents/{doc}/operations` -- mehrere Aenderungen als EIN Vorgang (ein
  Undo-Schritt, alles oder nichts): `create`, `delete`, `patch`, `set_expression`,
  `set_cells`, `add_property`, `remove_property`. Platzhalter `"as": "m"` / `"$m"`;
  Antwort `{created, results, revs, errors, atomic, recomputed}`. Fehler tragen
  `detail.failedOp`. `strict` (Standard): neu ungueltige Objekte -> `409 recompute_failed`.
- Neue Fehlercodes: `invalid_operation`, `type_not_allowed`, `has_dependents`,
  `invalid_expression`, `property_exists`, `not_dynamic`, `recompute_failed`, `invalid_range`.
- `GET /api/cad/documents/{doc}/sheets/{sheet}/cells?range=A1:D100` -- benutzte Zellen mit
  Inhalt, Wert und Alias.
- `types.OPERATIONS` mit den Operationsnamen.

## cad_contract 0.4.0 -- 2026-09-25

- `PATCH .../objects/{name}` versteht `If-Match: <rev>` (auch `"12"`, `W/"12"`, `*`).
  Weicht der rev ab: `409 rev_mismatch`, `detail = {expected, current, object}` mit dem
  aktuellen Stand des Objekts. Ohne Header wie bisher ohne Pruefung.

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
