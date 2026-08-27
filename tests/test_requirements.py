"""pytest as the rule runner. Produces the JUnit XML the CI publishes.

Deliberately runs against the FIXTURE, not the API: switching this to "api"
would make every pytest run require a live server, and CI must be able to go
green without one.
"""

import pytest

from sysmlcad.verify import run

RESULT = run()


@pytest.mark.parametrize(
    "v", RESULT.verdicts, ids=[v.requirement.requirement_id for v in RESULT.verdicts]
)
def test_requirement_satisfied(v):
    assert v.passed, (
        f"{v.requirement.requirement_id}: {v.requirement.prop} = "
        f"{v.measured:.4g~P}, required {v.requirement.operator} "
        f"{v.requirement.limit:.4g~P}"
    )


def test_nothing_went_unchecked():
    """A gap is not a pass. If a requirement could not be evaluated the run has
    to say so out loud, or the report claims coverage it does not have."""
    assert RESULT.gaps == [], f"unchecked requirements: {RESULT.gaps}"


def test_run_records_its_provenance():
    """SRS FREQ-1: a verdict without a model state behind it is not evidence."""
    assert RESULT.context.cad_state_id
    assert RESULT.context.mapping_digest
    assert RESULT.context.started_at
