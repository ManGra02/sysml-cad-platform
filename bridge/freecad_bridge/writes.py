"""Schreiben -- ein Vorgang ist genau ein Undo, oder ehrlich nicht.

Empirisch an FreeCAD 1.1 geklaert, bevor diese Datei entstand:

  * ``App.setActiveTransaction`` legt die Transaktion ERST beim ersten
    Schreibzugriff an. ``HasPendingTransaction`` ist direkt danach ``False`` --
    auch bei UndoMode 1. Pruefen laesst sich das also erst nach dem ersten Wert.
  * Bei ``UndoMode == 0`` bleibt ein Wert nach dem "Abbruch" einfach stehen,
    ohne Fehler. Deshalb wird UndoMode VOR dem ersten Schreibzugriff geprueft.
  * ``closeActiveTransaction(True)`` rollt alle Werte der Transaktion zurueck;
    ein Undo nimmt die ganze Transaktion auf einmal zurueck.
  * Ein zweites setActiveTransaction (z. B. ein FreeCAD-Befehl, den der Nutzer
    waehrend eines Recomputes klickt) uebernimmt still den aktiven Handle. Ein
    spaeteres Abort waere dann ein No-Op. Deshalb wird vor dem Schliessen
    geprueft, ob die Transaktion noch unsere ist, und sonst ``atomic: false``
    gemeldet statt Atomaritaet vorzutaeuschen.
  * Falsche Einheit -> ArithmeticError, unparsbarer Text -> ParserError.

Ablauf: alle Felder VORHER pruefen und umwandeln (ein ungueltiges Feld fasst
nichts an) -> Transaktion -> Werte setzen -> recompute -> Handle pruefen ->
commit. Scheitert etwas dazwischen: Abbruch, Nachrechnen, Fehler melden.
"""

import collections

import FreeCAD

from freecad_bridge import documents, log, objects, observer, properties, revisions
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import BridgeError, CadBusyError, main_thread_only

#: Wie viele Antworten fuer idempotente Wiederholungen gemerkt werden.
#: Ein automatischer Retry (etwa von TanStack Query) mit derselben
#: X-Request-Id darf die Aenderung nicht ein zweites Mal ausfuehren.
REPLAY_CACHE_SIZE = 100

_replay_cache = collections.OrderedDict()


class UndoDisabled(BridgeError):
    code = "undo_disabled"
    http_status = 409


class InvalidPatch(BridgeError):
    code = "invalid_patch"
    http_status = 400


# -- Idempotenz --------------------------------------------------------


def _cached(request_id):
    if not request_id or request_id not in _replay_cache:
        return None
    response = dict(_replay_cache[request_id])
    response["replayed"] = True
    return response


def _remember(request_id, response):
    if not request_id:
        return
    _replay_cache[request_id] = response
    while len(_replay_cache) > REPLAY_CACHE_SIZE:
        _replay_cache.popitem(last=False)


# -- Hilfen ------------------------------------------------------------


def _transaction_name(obj, names):
    """Sprechend, damit der Nutzer in FreeCADs Undo-Liste sieht, was vom Browser kam."""
    if len(names) == 1:
        return "Browser: %s.%s" % (obj.Label, names[0])
    return "Browser: %s (%d Properties)" % (obj.Label, len(names))


def _active_transaction_id():
    active = FreeCAD.getActiveTransaction()
    if not active:
        return None
    return active[1]


def _state_errors(objs):
    """Objekte, die nach dem Recompute fehlerhaft sind.

    Sonst meldete die Bruecke 200, waehrend ein Feature ungueltig geworden ist.
    """
    errors = []
    for obj in objs:
        try:
            state = list(obj.State)
        except Exception:
            continue
        bad = [flag for flag in state if flag in ("Invalid", "Error", "RecomputeError")]
        if bad:
            errors.append({"doc": obj.Document.Name, "name": obj.Name, "state": state})
    return errors


def _affected(obj):
    """Das Objekt selbst plus alles, was davon abhaengt."""
    try:
        dependents = list(obj.InListRecursive)
    except Exception:
        dependents = []
    return [obj] + dependents


def _same(current, new):
    """Ist ``new`` derselbe Wert wie ``current``?

    Noetig, weil FreeCAD das nicht einheitlich erkennt: bei Bool und Text
    entsteht fuer einen unveraenderten Wert keine Transaktion, bei Quantity
    schon -- inklusive Undo-Eintrag und Recompute. Ohne diese Pruefung fuellte
    ein Formular, das alle Felder mitschickt, den 20 Eintraege kurzen
    Undo-Stack mit Leerlaeufen.
    """
    try:
        if isinstance(current, FreeCAD.Units.Quantity):
            value = new.Value if isinstance(new, FreeCAD.Units.Quantity) else float(new)
            return abs(current.Value - value) <= 1e-12 * max(1.0, abs(value))
        if isinstance(current, (FreeCAD.Placement, FreeCAD.Rotation)):
            return current.isSame(new, 1e-12)
        if isinstance(current, FreeCAD.Vector):
            return current.isEqual(new, 1e-12)
        if hasattr(current, "Name") and hasattr(current, "Document"):
            return new is not None and current.Name == getattr(new, "Name", None)
        return type(current) is type(new) and current == new
    except Exception:
        return False


def _decode_all(obj, changes):
    """Alle Felder pruefen, bevor irgendetwas angefasst wird."""
    decoded = collections.OrderedDict()
    failures = []
    for name, payload in changes.items():
        try:
            decoded[name] = properties.decode_for_write(obj, name, payload)
        except BridgeError as exc:
            failures.append(exc)

    if not failures:
        return decoded
    if len(failures) == 1:
        raise failures[0]  # Einzelfehler mit seinem eigenen Code (z. B. 409)
    raise InvalidPatch(
        "%d Felder sind ungueltig" % len(failures),
        [{"code": f.code, "message": f.message, "field": f.detail} for f in failures],
    )


# -- Oeffentliche Operationen ------------------------------------------


@main_thread_only
def patch_object(doc_name, obj_name, changes, request_id=None, recompute=True):
    """Properties eines Objekts setzen -- alle in EINER Transaktion."""
    replay = _cached(request_id)
    if replay is not None:
        return replay

    if not isinstance(changes, dict) or not changes:
        raise InvalidPatch("Mindestens ein Feld erwartet: {\"Property\": Wert}")

    obj = objects.get_object(doc_name, obj_name)
    doc = obj.Document
    decoded = _decode_all(obj, changes)

    documents.ensure_undo_enabled(doc)
    if doc.UndoMode == 0:
        raise UndoDisabled(
            "Undo ist fuer %r abgeschaltet -- ohne Undo waere kein Abbruch moeglich" % doc.Name
        )

    if _active_transaction_id() is not None:
        # Ein FreeCAD-Befehl des Nutzers laeuft gerade. Hineinzuschreiben
        # wuerde unsere Aenderung in SEINE Undo-Einheit mischen.
        raise CadBusyError("In FreeCAD ist gerade eine Transaktion offen", "transaction_open")

    unchanged = [name for name, value in decoded.items() if _same(getattr(obj, name), value)]
    for name in unchanged:
        del decoded[name]

    if not decoded:
        # Nichts zu tun: keine Transaktion, kein Undo-Eintrag, kein Recompute.
        response = {
            "status": "done",
            "atomic": True,
            "changed": False,
            "applied": [],
            "unchanged": unchanged,
            "recomputed": 0,
            "errors": _state_errors(_affected(obj)),
            "rev": revisions.current(doc.Name, obj.Name),
            "ref": {"doc": doc.Name, "name": obj.Name},
        }
        _remember(request_id, response)
        return response

    state = bridge_state.get_state()
    # Markiert alle Aenderungen dieses Fensters als "bridge:<id>", damit das
    # Frontend das Echo seiner eigenen Mutation erkennt und ignoriert.
    state.active_request_id = request_id or "anonymous"
    try:
        response = _apply(doc, obj, decoded, unchanged, request_id, recompute)
    finally:
        state.active_request_id = None
    observer.flush_now("write")

    # Mit laufendem Observer hat der Flush die Revision bereits erhoeht --
    # das Ereignis und diese Antwort tragen dann denselben Wert.
    if response["changed"] and getattr(state, "observer", None) is None:
        response["rev"] = revisions.bump(doc.Name, obj.Name)
    else:
        response["rev"] = revisions.current(doc.Name, obj.Name)

    _remember(request_id, response)
    return response


def _apply(doc, obj, decoded, unchanged, request_id, recompute):
    tid = FreeCAD.setActiveTransaction(_transaction_name(obj, list(decoded)))
    applied = []
    try:
        for name, value in decoded.items():
            setattr(obj, name, value)
            applied.append(name)
        # Einen Wert auf seinen bisherigen Wert zu setzen, ist fuer FreeCAD
        # keine Aenderung -- es entsteht keine Transaktion. Da UndoMode oben
        # bereits sichergestellt ist, heisst "keine Transaktion" hier also
        # "nichts geaendert", nicht "Undo kaputt".
        changed = bool(doc.HasPendingTransaction)
        recomputed = doc.recompute() if (recompute and changed) else 0
    except Exception as exc:
        ours = _active_transaction_id() == tid
        if ours:
            FreeCAD.closeActiveTransaction(True)
            try:
                doc.recompute()  # sonst bleibt ein Touched-Marker fuer Zurueckgerolltes
            except Exception:
                pass
        if isinstance(exc, BridgeError):
            raise
        if isinstance(exc, (ArithmeticError, ValueError, TypeError)) or type(exc).__name__ == "ParserError":
            raise properties.InvalidValue(
                "%s: %s" % (applied[-1] if applied else "Wert", exc),
                {"rolledBack": ours, "applied": applied},
            )
        raise BridgeError(
            "Schreiben fehlgeschlagen: %s" % exc,
            {"rolledBack": ours, "applied": applied},
        )

    atomic = _active_transaction_id() == tid
    if atomic:
        FreeCAD.closeActiveTransaction()
    else:
        log.warn(
            "Transaktion %s wurde von einem FreeCAD-Befehl uebernommen; "
            "die Aenderung ist nicht als eigene Undo-Einheit gesichert" % tid,
            request_id,
        )

    return {
        "status": "done",  # spaeter additiv: "running" + "job_id"
        "atomic": atomic,
        "changed": changed,
        "applied": applied,
        "unchanged": unchanged,
        "recomputed": recomputed,
        "errors": _state_errors(_affected(obj)),
        "rev": None,  # setzt patch_object nach dem Flush
        "ref": {"doc": doc.Name, "name": obj.Name},
    }


@main_thread_only
def recompute_document(doc_name, request_id=None):
    """Dokument neu berechnen -- ohne Transaktion, denn es aendert keine Eingaben."""
    replay = _cached(request_id)
    if replay is not None:
        return replay

    doc = documents.get_document(doc_name)
    count = doc.recompute()
    response = {
        "status": "done",
        "recomputed": count,
        "errors": _state_errors(list(doc.Objects)),
    }
    _remember(request_id, response)
    return response
