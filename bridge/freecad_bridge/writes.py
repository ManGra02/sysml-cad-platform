"""Writing -- one transaction is exactly one undo, or honestly not.

Established empirically on FreeCAD 1.1 before this file was written:

  * ``App.setActiveTransaction`` creates the transaction only on the FIRST
    write access. ``HasPendingTransaction`` is ``False`` right after it --
    even with UndoMode 1. So this can only be checked after the first value.
  * With ``UndoMode == 0`` a value simply stays in place after the "abort",
    without an error. That is why UndoMode is checked BEFORE the first write.
  * ``closeActiveTransaction(True)`` rolls back all values of the transaction;
    an undo reverts the whole transaction at once.
  * A second setActiveTransaction (e.g. a FreeCAD command the user clicks
    during a recompute) silently takes over the active handle. A later
    abort would then be a no-op. That is why, before closing, we check
    whether the transaction is still ours, and otherwise report
    ``atomic: false`` instead of pretending to be atomic.
  * Wrong unit -> ArithmeticError, unparsable text -> ParserError.

Flow: check and convert all fields BEFOREHAND (an invalid field touches
nothing) -> transaction -> set values -> recompute -> check handle ->
commit. If something fails in between: abort, recompute, report the error.
"""

import collections

import FreeCAD

from freecad_bridge import documents, log, objects, observer, properties, revisions
from freecad_bridge import state as bridge_state
from freecad_bridge.dispatch import BridgeError, CadBusyError, main_thread_only

#: How many responses are remembered for idempotent retries.
#: An automatic retry (e.g. from TanStack Query) with the same
#: X-Request-Id must not apply the change a second time.
REPLAY_CACHE_SIZE = 100

_replay_cache = collections.OrderedDict()


class UndoDisabled(BridgeError):
    code = "undo_disabled"
    http_status = 409


class InvalidPatch(BridgeError):
    code = "invalid_patch"
    http_status = 400


class RevisionConflict(BridgeError):
    """The object has changed since the client read it.

    ``detail`` carries the object's current state along, so that the
    UI can offer "reload or overwrite" without having to ask a second
    time.
    """

    code = "rev_mismatch"
    http_status = 409


# -- Idempotency -------------------------------------------------------


def cached_response(request_id):
    if not request_id or request_id not in _replay_cache:
        return None
    response = dict(_replay_cache[request_id])
    response["replayed"] = True
    return response


def remember_response(request_id, response):
    if not request_id:
        return
    _replay_cache[request_id] = response
    while len(_replay_cache) > REPLAY_CACHE_SIZE:
        _replay_cache.popitem(last=False)


# -- Helpers -----------------------------------------------------------


def _transaction_name(obj, names):
    """Descriptive, so the user sees in FreeCAD's undo list what came from the browser."""
    if len(names) == 1:
        return "Browser: %s.%s" % (obj.Label, names[0])
    return "Browser: %s (%d Properties)" % (obj.Label, len(names))


def active_transaction_id():
    active = FreeCAD.getActiveTransaction()
    if not active:
        return None
    return active[1]


def state_errors(objs):
    """Objects that are in error after the recompute.

    Otherwise the bridge would report 200 while a feature has become invalid.
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
    """The object itself plus everything that depends on it."""
    try:
        dependents = list(obj.InListRecursive)
    except Exception:
        dependents = []
    return [obj] + dependents


def same_value(current, new):
    """Is ``new`` the same value as ``current``?

    Needed because FreeCAD does not detect this consistently: for bool and
    text an unchanged value creates no transaction, for Quantity it does --
    including an undo entry and a recompute. Without this check, a form that
    sends all fields would fill the undo stack, only 20 entries deep, with
    no-ops.
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


def _failure(exc):
    """A single error as an entry in the aggregate invalid_patch response.

    Passes on ``reason`` and parameters (for invalid_value) so that the
    UI can build each message in the user's language.
    """
    entry = {"code": exc.code, "message": exc.message}
    if isinstance(exc.detail, dict):
        entry.update(exc.detail)
    else:
        entry["field"] = exc.detail
    return entry


def decode_all(obj, changes):
    """Check all fields before anything is touched."""
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
        raise failures[0]  # single error with its own code (e.g. 409)
    raise InvalidPatch(
        "%d fields are invalid" % len(failures),
        [_failure(f) for f in failures],
    )


# -- Public operations -------------------------------------------------


def check_revision(obj, if_match):
    """Optimistic locking: only write if the client knows the current state.

    A flush happens first: a change in FreeCAD whose flush is still pending
    (up to 100 ms) would otherwise not have bumped its rev yet -- and the
    PATCH would run over it.
    """
    observer.flush_now("precondition")
    current = revisions.current(obj.Document.Name, obj.Name)
    if current != if_match:
        raise RevisionConflict(
            "%s has changed in the meantime (rev %d, expected %d)" % (obj.Label, current, if_match),
            {
                "expected": if_match,
                "current": current,
                "object": objects.describe_object(obj),
            },
        )


@main_thread_only
def patch_object(doc_name, obj_name, changes, request_id=None, recompute=True, if_match=None):
    """Set an object's properties -- all in ONE transaction.

    ``if_match`` is the ``rev`` the client has seen. If it differs,
    nothing is written (409 rev_mismatch). None = no check.
    """
    replay = cached_response(request_id)
    if replay is not None:
        return replay

    if not isinstance(changes, dict) or not changes:
        raise InvalidPatch("At least one field expected: {\"Property\": value}")

    obj = objects.get_object(doc_name, obj_name)
    doc = obj.Document
    if if_match is not None:
        check_revision(obj, if_match)
    decoded = decode_all(obj, changes)

    documents.ensure_undo_enabled(doc)
    if doc.UndoMode == 0:
        raise UndoDisabled(
            "Undo is disabled for %r -- without undo nothing could be rolled back" % doc.Name
        )

    if active_transaction_id() is not None:
        # A FreeCAD command of the user is currently running. Writing into it
        # would mix our change into ITS undo unit.
        raise CadBusyError("A transaction is currently open in FreeCAD", "transaction_open")

    unchanged = [name for name, value in decoded.items() if same_value(getattr(obj, name), value)]
    for name in unchanged:
        del decoded[name]

    if not decoded:
        # Nothing to do: no transaction, no undo entry, no recompute.
        response = {
            "status": "done",
            "atomic": True,
            "changed": False,
            "applied": [],
            "unchanged": unchanged,
            "recomputed": 0,
            "errors": state_errors(_affected(obj)),
            "rev": revisions.current(doc.Name, obj.Name),
            "ref": {"doc": doc.Name, "name": obj.Name},
        }
        remember_response(request_id, response)
        return response

    state = bridge_state.get_state()
    # Marks all changes in this window as "bridge:<id>" so that the frontend
    # recognizes the echo of its own mutation and ignores it.
    state.active_request_id = request_id or "anonymous"
    try:
        response = _apply(doc, obj, decoded, unchanged, request_id, recompute)
    finally:
        state.active_request_id = None
    observer.flush_now("write")

    # With the observer running, the flush has already bumped the revision --
    # the event and this response then carry the same value.
    if response["changed"] and getattr(state, "observer", None) is None:
        response["rev"] = revisions.bump(doc.Name, obj.Name)
    else:
        response["rev"] = revisions.current(doc.Name, obj.Name)

    remember_response(request_id, response)
    return response


def _apply(doc, obj, decoded, unchanged, request_id, recompute):
    tid = FreeCAD.setActiveTransaction(_transaction_name(obj, list(decoded)))
    applied = []
    try:
        for name, value in decoded.items():
            setattr(obj, name, value)
            applied.append(name)
        # Setting a value to its previous value is not a change for FreeCAD
        # -- no transaction is created. Since UndoMode has already been
        # ensured above, "no transaction" here therefore means "nothing
        # changed", not "undo broken".
        changed = bool(doc.HasPendingTransaction)
        recomputed = doc.recompute() if (recompute and changed) else 0
    except Exception as exc:
        ours = active_transaction_id() == tid
        if ours:
            FreeCAD.closeActiveTransaction(True)
            try:
                doc.recompute()  # otherwise a Touched marker remains for what was rolled back
            except Exception:
                pass
        if isinstance(exc, BridgeError):
            raise
        if isinstance(exc, (ArithmeticError, ValueError, TypeError)) or type(exc).__name__ == "ParserError":
            raise properties.InvalidValue(
                "%s: %s" % (applied[-1] if applied else "value", exc),
                applied[-1] if applied else None,
                "rejected",
                error=str(exc),
                rolledBack=ours,
                applied=applied,
            )
        raise BridgeError(
            "Write failed: %s" % exc,
            {"rolledBack": ours, "applied": applied},
        )

    atomic = active_transaction_id() == tid
    if atomic:
        FreeCAD.closeActiveTransaction()
    else:
        log.warn(
            "Transaction %s was taken over by a FreeCAD command; "
            "the change is not a separate undo step" % tid,
            request_id,
        )

    return {
        "status": "done",  # later, additively: "running" + "job_id"
        "atomic": atomic,
        "changed": changed,
        "applied": applied,
        "unchanged": unchanged,
        "recomputed": recomputed,
        "errors": state_errors(_affected(obj)),
        "rev": None,  # set by patch_object after the flush
        "ref": {"doc": doc.Name, "name": obj.Name},
    }


@main_thread_only
def recompute_document(doc_name, request_id=None):
    """Recompute the document -- without a transaction, since it changes no inputs."""
    replay = cached_response(request_id)
    if replay is not None:
        return replay

    doc = documents.get_document(doc_name)
    count = doc.recompute()
    response = {
        "status": "done",
        "recomputed": count,
        "errors": state_errors(list(doc.Objects)),
    }
    remember_response(request_id, response)
    return response
