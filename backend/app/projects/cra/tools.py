"""Agent tools of the CRA module -- the part library search."""

from app.ai.tools import _tool
from app.projects.cra.finder import Finder
from app.projects.cra.matching import DEFAULT_TOL_PCT


def cra_tools(ctx, finder=None):
    finder = finder or Finder(ctx)

    async def find_matching_parts(attributes: dict, tolerance_pct: float = DEFAULT_TOL_PCT) -> dict:
        """Find the best existing part in the PLM part library for a required part, by function and
        dimensions (not by name). `attributes` are the attributes of the required SysML part with their
        modelled names and values in the modelled unit, e.g. {"partType": "Pulley", "function": "drives a belt",
        "teeth": 18, "boreDiameterMm": 12, "material": "steel"}. Returns the best match ("best", null if none
        fits), up to 3 near misses with what is wrong ("failures") and how much tolerance would fix it
        ("needs_tolerance_pct", null if no tolerance can). Default tolerance 10 %; if nothing fits and a near
        miss needs more, call again with that tolerance (maximum 30). Never widen it for fit-critical sizes."""
        return await finder.find(attributes, tolerance_pct)

    return [_tool(find_matching_parts)]
