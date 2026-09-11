"""pytest as the rule runner. Produces the JUnit XML the CI publishes.

Deliberately runs against each project's CAPTURE, not the API: switching this
to "api" would make every pytest run require a live server, and CI must be able
to go green without one.

Every project is verified on every run. Before projects existed, only the motor
housing was -- the gearbox had a mapping and a capture but no test ever ran
its verification, because the one fixture only knew one model.
"""

import pytest

from sysmlcad.project import list_projects, load_project
from sysmlcad.verify import run

RESULTS = {name: run(load_project(name)) for name in list_projects()}

VERDICTS = [
    (name, v)
    for name, result in RESULTS.items()
    for v in result.verdicts
]


@pytest.mark.parametrize(
    "name, v", VERDICTS,
    ids=[f"{name}:{v.requirement.requirement_id}" for name, v in VERDICTS],
)
def test_requirement_satisfied(name, v):
    assert v.passed, (
        f"{name} {v.requirement.requirement_id}: {v.requirement.prop} = "
        f"{v.measured:.4g~P}, required {v.requirement.operator} "
        f"{v.requirement.limit:.4g~P}"
    )


@pytest.mark.parametrize("name", list(RESULTS), ids=list(RESULTS))
def test_every_gap_is_a_known_one(name):
    """A gap is not a pass. If a requirement could not be evaluated the run has
    to say so out loud, or the report claims coverage it does not have.

    The gearbox has exactly one, on purpose: MinBoreRadius, which no
    measurement in the vocabulary can express. It is listed here so that a
    NEW gap -- a mapping that quietly stopped working -- still fails the run.
    """
    known = {"gearbox": ["MinBoreRadius"]}
    reported = [gap.split(":", 1)[0] for gap in RESULTS[name].gaps]
    assert reported == known.get(name, []), f"unexpected gaps: {RESULTS[name].gaps}"


@pytest.mark.parametrize("name", list(RESULTS), ids=list(RESULTS))
def test_run_records_its_provenance(name):
    """SRS FREQ-1: a verdict without a model state behind it is not evidence."""
    ctx = RESULTS[name].context
    assert ctx.project == name
    assert ctx.cad_state_id
    assert ctx.mapping_digest
    assert ctx.started_at


def test_the_reference_project_still_measures_what_it_always_did():
    """The documented reference run: 118 mm against 120, 0.7429 kg against 0.9.
    Pinned by value so the capture replacing the hand-written fixture cannot
    have shifted anything."""
    by_id = {v.requirement.requirement_id: v for v in RESULTS["motor_housing"].verdicts}
    assert by_id["MaxLength"].measured.to("mm").magnitude == pytest.approx(118.0)
    assert by_id["MaxMass"].measured.to("kg").magnitude == pytest.approx(0.7429, abs=1e-4)
