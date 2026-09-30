"""The bridge's event vocabulary.

Every event carries only IDENTITY, no values. The receiver re-reads via
the normal read route, which sees a consistent state.

Common fields: type, seq (monotonic per session), session_id, doc, transacting.
Object events additionally: obj, label, origin, cause, rev.

Events arrive batched: one WebSocket frame {"type": "events",
"session_id", "events": [...]} per flush -- not one frame per change.
"""

# -- Framing ------------------------------------------------------------
HELLO = "hello"                     # on connect: session_id, last_seq
BATCH = "events"                    # one flush

# -- Objects ------------------------------------------------------------
CREATED = "cad.created"
DELETED = "cad.deleted"
CHANGED = "cad.changed"             # + props[]
SCHEMA_CHANGED = "cad.schema_changed"  # re-fetch metadata (ReadOnly/Hidden, dyn. property)

# -- Flow ---------------------------------------------------------------
TRANSACTION = "cad.transaction"     # + result: committed | aborted, name
HISTORY = "cad.history"             # + action: undo | redo -> discard the document's cache
RECOMPUTED = "cad.recomputed"
RESYNC = "cad.resync"               # reload everything (overflow)

# -- Documents ----------------------------------------------------------
DOC_OPENED = "doc.opened"           # + label, objectCount
DOC_CLOSED = "doc.closed"
DOC_SAVED = "doc.saved"             # + fileName, label
DOC_RELABELED = "doc.relabeled"     # + label
DOC_MODIFIED = "doc.modified"       # + dirty (GUI only)
DOC_ACTIVATED = "doc.activated"

# -- Origin -------------------------------------------------------------
ORIGIN_USER = "freecad:user"
ORIGIN_BRIDGE_PREFIX = "bridge:"    # + X-Request-Id of the triggering mutation
ORIGIN_MIXED = "mixed"

#: Events after which the receiver should discard the document's cache
#: COMPLETELY instead of catching up incrementally.
FULL_RELOAD = frozenset([HISTORY, RESYNC, DOC_OPENED])
