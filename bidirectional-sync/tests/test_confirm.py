"""The proposal store and the confirmation step (SRS FREQ-4, FREQ-5).

The two properties worth defending here:

* **A proposal cannot influence a run.** Nothing that computes a verdict reads
  `proposals.yaml`; an entry reaches `mapping.yaml` only through a confirmation
  that re-runs the gates.
* **Confirming does not rewrite the file.** `mapping.yaml` is design intent in
  review, and a command that reformatted it on every confirmation would make
  its diffs unreadable -- which is how review stops happening.
"""

from pathlib import Path

import pytest
import yaml

from sysmlcad.confirm import confirm, insert_into_section, reject, render_entry
from sysmlcad.mapping import load_mapping
from sysmlcad.project import load_project
from sysmlcad.proposals import (
    Proposal,
    add,
    decide,
    find,
    load_proposals,
    merged_mapping,
    next_id,
    save_proposals,
)

MOTOR = load_project("motor_housing")
MAPPING_SRC = MOTOR.mapping_path


def _proposal(**kwargs) -> Proposal:
    return Proposal(**{
        "id": "p-01",
        "sysml_part": "motorHousing",
        "attribute": "mass",
        "adapter": "build123d",
        "cad_object": "motor_housing",
        "method": "mass",
        "args": {},
        "requirement": "MaxMass",
        "confidence": 0.82,
        "rationale": "the attribute name matches the measurement method",
        "proposed_by": "baseline:difflib",
        **kwargs,
    })


@pytest.fixture
def workspace(tmp_path):
    """A mapping with the mass entry cut off, so there is something to propose,
    plus an empty proposal store."""
    source = MAPPING_SRC.read_text(encoding="utf-8")
    cut = source.index("  - sysml_part: motorHousing\n    attribute: mass")
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(source[:cut].rstrip() + "\n", encoding="utf-8")
    return mapping, tmp_path / "proposals.yaml"


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------

def test_proposals_survive_a_round_trip(tmp_path):
    store = tmp_path / "proposals.yaml"
    save_proposals([_proposal()], store)
    loaded = load_proposals(store)
    assert loaded == [_proposal()]


def test_the_store_says_it_is_machine_written(tmp_path):
    store = tmp_path / "proposals.yaml"
    save_proposals([_proposal()], store)
    assert "MACHINE-WRITTEN" in store.read_text(encoding="utf-8")


def test_ids_are_handed_out_in_order():
    assert next_id([]) == "p-01"
    assert next_id([_proposal(id="p-01"), _proposal(id="p-07")]) == "p-08"


def test_the_same_suggestion_is_not_stored_twice():
    existing, _ = add([], [_proposal(id="")])
    _again, added = add(existing, [_proposal(id="")])
    assert added == 0


def test_a_rejected_suggestion_is_not_proposed_again():
    """Otherwise the store is a treadmill: the proposer keeps suggesting what a
    human already turned down."""
    stored, _ = add([], [_proposal(id="")])
    stored = decide(stored, "p-01", "rejected", "vh", "wrong object")
    _after, added = add(stored, [_proposal(id="")])
    assert added == 0


def test_a_decision_keeps_the_proposal_and_records_who_made_it():
    stored = decide([_proposal()], "p-01", "rejected", "Vincent", "measures the cover")
    assert len(stored) == 1
    assert stored[0].status == "rejected"
    assert stored[0].decided_by == "Vincent"
    assert stored[0].decided_at
    assert stored[0].reason == "measures the cover"


def test_a_proposal_is_gated_as_if_it_were_confirmed():
    """"Would this be sound if it were used?" is the question before a
    confirmation -- so the merged entry must not carry `proposed`, or the
    uniqueness gate would ignore it."""
    mapping = load_mapping(MAPPING_SRC)
    merged = merged_mapping(mapping, _proposal(sysml_part="newPart"))
    assert merged.attributes[-1].status == "confirmed"
    assert merged.parts["newPart"].status == "confirmed"


def test_a_proposal_is_measured_on_the_object_it_names():
    """The inverse of what this test used to pin. The merged view kept the
    EXISTING part entry, so the gates measured an object the proposal did not
    name -- and the reviewer approved one object while the mapping recorded
    another. `gates.check_proposal` now reports that disagreement instead."""
    mapping = load_mapping(MAPPING_SRC)
    merged = merged_mapping(mapping, _proposal(cad_object="gearbox#Housing"))
    assert merged.parts["motorHousing"].cad_object == "gearbox#Housing"
    assert mapping.parts["motorHousing"].cad_object == "motor_housing", "input untouched"


# --------------------------------------------------------------------------
# Writing YAML without rewriting it
# --------------------------------------------------------------------------

def test_an_entry_is_inserted_at_the_end_of_its_section():
    text = "parts:\n  - a: 1\n\n# a comment for the next section\nattributes:\n  - b: 2\n"
    out = insert_into_section(text, "parts", "  - c: 3\n")
    assert out == "parts:\n  - a: 1\n  - c: 3\n\n# a comment for the next section\nattributes:\n  - b: 2\n"


def test_inserting_leaves_every_other_byte_alone(workspace):
    mapping, store = workspace
    before = mapping.read_text(encoding="utf-8")
    after = insert_into_section(before, "attributes", "  - x: 1\n")
    assert after.startswith(before.rstrip("\n"))


def test_a_rendered_entry_is_valid_yaml():
    entry = render_entry({"sysml_part": "p", "args": {"axis": "X"}, "tolerance": None})
    parsed = yaml.safe_load(entry)
    assert parsed == [{"sysml_part": "p", "args": {"axis": "X"}, "tolerance": None}]


def test_a_rationale_with_awkward_characters_stays_readable():
    """Rationales come from a proposer, and one day from a language model. A
    colon in a rationale must not corrupt the file."""
    entry = render_entry({"note": "matches: length -> LENGTH_MM, 90% sure"})
    assert yaml.safe_load(entry)[0]["note"] == "matches: length -> LENGTH_MM, 90% sure"


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------

def test_confirming_appends_the_entry_and_records_the_person(workspace, capsys):
    mapping, store = workspace
    before = mapping.read_text(encoding="utf-8")
    save_proposals([_proposal()], store)

    assert confirm(MOTOR, "p-01", user="Vincent Hey", path=mapping, proposals_path=store) == 0

    after = mapping.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n")), "existing content was modified"

    entry = next(
        e for e in load_mapping(mapping).attributes if e.attribute == "mass"
    )
    assert entry.status == "confirmed"
    assert entry.author == "Vincent Hey"
    assert entry.confirmed_at
    assert entry.method == "mass"

    assert find(load_proposals(store), "p-01").status == "confirmed"


def test_the_note_records_where_the_entry_came_from(workspace):
    """Once confirmed, the origin no longer influences anything -- but it stays
    readable, because "why is this here" is the first question in review."""
    mapping, store = workspace
    save_proposals([_proposal()], store)
    confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store)

    entry = next(e for e in load_mapping(mapping).attributes if e.attribute == "mass")
    assert "baseline:difflib" in entry.note
    assert "p-01" in entry.note


def test_an_invalid_proposal_is_refused_and_the_file_untouched(workspace, capsys):
    """The gates run again at confirmation time. Confirming a wrong mapping
    would make a wrong rule deterministic, which is the one thing the
    confirmation step exists to prevent."""
    mapping, store = workspace
    before = mapping.read_text(encoding="utf-8")
    save_proposals([_proposal(attribute="wheelbase")], store)

    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 1
    assert mapping.read_text(encoding="utf-8") == before
    assert find(load_proposals(store), "p-01").status == "proposed"
    assert "gate says" in capsys.readouterr().out


def test_a_proposal_naming_another_object_for_a_mapped_part_is_refused(workspace, capsys):
    """`motorHousing` is already `build123d:motor_housing`. A proposal for its
    mass on `gearbox#Housing` passes dimension, existence and plausibility --
    and used to be confirmed, gated and then measured on `motor_housing`, the
    object nobody had reviewed. A part stands for one CAD object."""
    mapping, store = workspace
    before = mapping.read_text(encoding="utf-8")
    save_proposals([_proposal(cad_object="gearbox#Housing")], store)

    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 1
    assert mapping.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "already mapped to build123d:motor_housing" in out
    assert find(load_proposals(store), "p-01").status == "proposed"


def test_confirming_twice_is_refused(workspace):
    mapping, store = workspace
    save_proposals([_proposal()], store)
    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 0
    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 2


def test_an_unknown_id_is_an_error_not_a_crash(workspace):
    mapping, store = workspace
    save_proposals([_proposal()], store)
    assert confirm(MOTOR, "p-99", path=mapping, proposals_path=store) == 2


def test_rejecting_records_the_reason_and_writes_nothing_to_the_mapping(workspace):
    mapping, store = workspace
    before = mapping.read_text(encoding="utf-8")
    save_proposals([_proposal()], store)

    assert reject(MOTOR, "p-01", "that bore belongs to the cover", "vh", store) == 0
    assert mapping.read_text(encoding="utf-8") == before

    decided = find(load_proposals(store), "p-01")
    assert decided.status == "rejected"
    assert decided.reason == "that bore belongs to the cover"


def test_a_decided_proposal_cannot_be_rejected(workspace):
    """Rejecting a confirmed proposal would leave the record saying "no" while
    mapping.yaml still carries the entry. Undoing a confirmation is an edit to
    mapping.yaml, in review."""
    mapping, store = workspace
    save_proposals([_proposal()], store)
    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 0

    assert reject(MOTOR, "p-01", "changed my mind", "vh", store) == 2
    assert find(load_proposals(store), "p-01").status == "confirmed"


def test_a_confirmed_entry_is_what_a_run_would_use(workspace):
    """The end of the chain: after confirmation the entry is an ordinary
    deterministic rule, indistinguishable from a hand-written one."""
    mapping, store = workspace
    save_proposals([_proposal()], store)
    confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store)

    entry = load_mapping(mapping).for_requirement("MaxMass", "motorHousing")
    assert entry is not None and entry.usable


def test_confirming_onto_an_unconfirmed_part_says_a_run_will_not_use_it(workspace, capsys):
    """The part entry already exists with the same object, so only the
    attribute is written -- but the part is still `proposed`. Claiming that a
    run will now use the entry would be false."""
    mapping, store = workspace
    text = mapping.read_text(encoding="utf-8")
    mapping.write_text(text.replace("    status: confirmed\n", "    status: proposed\n", 1),
                       encoding="utf-8")
    assert not load_mapping(mapping).parts["motorHousing"].usable
    save_proposals([_proposal()], store)

    assert confirm(MOTOR, "p-01", user="vh", path=mapping, proposals_path=store) == 0
    out = capsys.readouterr().out
    assert "is `proposed` under `parts:`" in out
    assert "will use it" not in out
