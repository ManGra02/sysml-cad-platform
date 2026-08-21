"""pytest als Regel-Runner. Liefert JUnit-XML fuer die CI."""

import pytest

from sysmlcad.verify import run

VERDICTS = run()


@pytest.mark.parametrize("v", VERDICTS, ids=[v.requirement.requirement_id for v in VERDICTS])
def test_requirement_satisfied(v):
    assert v.passed, (
        f"{v.requirement.requirement_id}: {v.requirement.prop} = "
        f"{v.measured:.4g~P}, gefordert {v.requirement.operator} "
        f"{v.requirement.limit:.4g~P}"
    )
