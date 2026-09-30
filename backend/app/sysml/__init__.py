"""SysML v2 adapter -- the SysML side of the platform.

Reads a versioned SysML v2 model from a SysML v2 API server (Flexo MMS, see
flexo/) and converts it into the common engineering model that the CAD side
is compared against:

    client.py       HTTP to the SysML v2 API (aiohttp), SysmlError
    parser.py       raw SysML JSON -> parts, attributes, requirements, relations
    expressions.py  evaluates values such as ``9.8 [kg]`` (an OperatorExpression tree)
    units.py        normalises to SI (mm -> m, g -> kg) so SysML and CAD compare like with like
    models.py       the common model: ModelElement, Attribute, Relation, ModelSnapshot
    service.py      SysmlService -- what modules get as ``self.ctx.sysml``
    diff.py         client-side diff of two commits
    routes.py       /api/sysml/* for the browser
    demo.py         the e-bike demo model
    __main__.py     command line: ``uv run python -m app.sysml --help``

Like app/bridge_client.py for CAD, this package is the only place that knows
the SysML v2 API. It never touches the bridge.
"""

from app.sysml.client import SysmlError
from app.sysml.models import Attribute, ModelElement, ModelSnapshot, Relation
from app.sysml.service import SysmlService

__all__ = ["SysmlService", "SysmlError", "ModelElement", "Attribute", "Relation", "ModelSnapshot"]
