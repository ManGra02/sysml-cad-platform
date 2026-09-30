# Changelog

Every change to `cad_contract` bumps `CONTRACT_VERSION` and gets a line here.
The backend's mismatch message points to this file.

## cad_contract 0.6.0 -- 2026-09-29

- Plain-text messages (`error.message`) from bridge and backend are now in **English** (the
  language of the API). The UI translates based on the codes, not the messages.
- `invalid_value`: `detail` is now `{field, reason, ...}` instead of just the field name.
  `reason` e.g. `unit_mismatch` (+ `expected`), `quantity_invalid` (+ `input`), `enum_choice`
  (+ `value`, `choices`), `int_expected`, `number_expected`, `text_expected`, `target_not_found`,
  `rejected` (+ `error`, `rolledBack`, `applied`). `invalid_patch` carries the same fields per entry.
- `POST .../operations`: errors additionally carry `field` and `reason` at the top level
  (next to `failedOp`, `op`, `detail`) -- the same shape as for PATCH. If FreeCAD itself
  rejects a value, `reason = "rejected"` (+ `error`).
- Backend: the bridge status carries `reason` (`not_started`, `orphaned_handshake`, `no_response`,
  `slow`, `computing`, `disconnected`, `token_rejected`, `connected`, `contract_mismatch`, …);
  the proxy's 503 responses carry it in `detail.reason`.

## cad_contract 0.5.0 -- 2026-09-28

- `POST /api/cad/documents/{doc}/operations` -- several changes as ONE operation (one
  undo step, all or nothing): `create`, `delete`, `patch`, `set_expression`,
  `set_cells`, `add_property`, `remove_property`. Placeholders `"as": "m"` / `"$m"`;
  response `{created, results, revs, errors, atomic, recomputed}`. Errors carry
  `detail.failedOp`. `strict` (default): newly invalid objects -> `409 recompute_failed`.
- New error codes: `invalid_operation`, `type_not_allowed`, `has_dependents`,
  `invalid_expression`, `property_exists`, `not_dynamic`, `recompute_failed`, `invalid_range`.
- `GET /api/cad/documents/{doc}/sheets/{sheet}/cells?range=A1:D100` -- used cells with
  content, value and alias.
- `types.OPERATIONS` with the operation names.

## cad_contract 0.4.0 -- 2026-09-25

- `PATCH .../objects/{name}` understands `If-Match: <rev>` (also `"12"`, `W/"12"`, `*`).
  If the rev differs: `409 rev_mismatch`, `detail = {expected, current, object}` with the
  current state of the object. Without the header, no check as before.

## cad_contract 0.3.0 -- 2026-09-25

- New module `events.py`: event vocabulary (cad.*, doc.*), origin
  (`freecad:user` / `bridge:<request-id>`), set `FULL_RELOAD`.
- WebSocket delivers events batched: one frame `{"type": "events", ...}` per flush.

## cad_contract 0.2.0 -- 2026-09-25

- Value format `types.py`: encoded / derived / unsupported, no str() fallback.
- Quantity carries `unit` (symbol, e.g. "mm") and `unitType` ("Length") instead of FreeCAD's repr.
- Objects carry `rev` (monotonic counter per object).
- Write response: `status`, `atomic`, `changed`, `applied`, `unchanged`, `recomputed`, `errors`, `rev`.

## cad_contract 0.1.0 -- 2026-09-11

- First version: `CONTRACT_VERSION`.
