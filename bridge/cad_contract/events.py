"""Das Ereignis-Vokabular der Bruecke.

Jedes Ereignis traegt nur IDENTITAET, keine Werte. Der Empfaenger liest ueber
die normale Leseroute nach, die einen konsistenten Stand sieht.

Gemeinsame Felder: type, seq (monoton je Sitzung), session_id, doc, transacting.
Objektereignisse zusaetzlich: obj, label, origin, cause, rev.

Ereignisse kommen gebuendelt: ein WebSocket-Frame {"type": "events",
"session_id", "events": [...]} pro Flush -- nicht ein Frame pro Aenderung.
"""

# -- Rahmen -------------------------------------------------------------
HELLO = "hello"                     # beim Verbinden: session_id, last_seq
BATCH = "events"                    # ein Flush

# -- Objekte ------------------------------------------------------------
CREATED = "cad.created"
DELETED = "cad.deleted"
CHANGED = "cad.changed"             # + props[]
SCHEMA_CHANGED = "cad.schema_changed"  # Metadaten neu holen (ReadOnly/Hidden, dyn. Property)

# -- Ablauf -------------------------------------------------------------
TRANSACTION = "cad.transaction"     # + result: committed | aborted, name
HISTORY = "cad.history"             # + action: undo | redo -> Cache des Dokuments verwerfen
RECOMPUTED = "cad.recomputed"
RESYNC = "cad.resync"               # alles neu laden (Ueberlauf)

# -- Dokumente ----------------------------------------------------------
DOC_OPENED = "doc.opened"           # + label, objectCount
DOC_CLOSED = "doc.closed"
DOC_SAVED = "doc.saved"             # + fileName, label
DOC_RELABELED = "doc.relabeled"     # + label
DOC_MODIFIED = "doc.modified"       # + dirty (nur mit GUI)
DOC_ACTIVATED = "doc.activated"

# -- Herkunft -----------------------------------------------------------
ORIGIN_USER = "freecad:user"
ORIGIN_BRIDGE_PREFIX = "bridge:"    # + X-Request-Id der ausloesenden Mutation
ORIGIN_MIXED = "mixed"

#: Ereignisse, nach denen der Empfaenger den Cache des Dokuments KOMPLETT
#: verwerfen soll, statt inkrementell nachzuziehen.
FULL_RELOAD = frozenset([HISTORY, RESYNC, DOC_OPENED])
