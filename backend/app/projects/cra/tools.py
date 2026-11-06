"""The CRA agent's own tools -- PLM access, understanding a part, searching, verifying.

All of them work on one CraSession (one agent run). Errors come back as {"error": ...}
so the agent can react (e.g. understand a part first, or ask for a missing size).
"""

from app.ai.tools import _tool


def cra_tools(session):
    async def plm_overview() -> dict:
        """What the PLM holds: number of parts, how many have a CAD model attached, how many have
        contradicting data, and which kinds of parts exist. Call this first to orient yourself."""
        return await session.overview()

    async def plm_parts_without_cad(limit: int = 50) -> dict:
        """PLM parts that have no CAD model attached (item number, name, kind)."""
        return await session.without_cad(limit)

    async def plm_item(item_number: str) -> dict:
        """Everything the PLM knows about one part: name, description, material, mass, attributes and
        the attached CAD files (with the size Cascadia measured from the geometry)."""
        return await session.item(item_number)

    async def understand_part(subject: str, description: str, attributes: dict | None = None) -> dict:
        """Understand what a part is and decide what a replacement must fulfil. `subject` is your name for
        it (the SysML part name or the PLM item number), `description` all you know in words (name,
        description, requirements), `attributes` its values as given (e.g. from sysml_attributes).
        Returns what it is, its kind and function, its properties and the RULES a replacement must meet
        (critical ones are interfaces/fits). Always call this before searching."""
        return await session.understand(subject, description, attributes)

    async def search_parts(subject: str, cad_required: bool = False, limit: int = 5) -> dict:
        """Search all PLM parts for a replacement of an understood `subject`, using its rules. Only parts of
        the same kind (or doing the same job) are considered. Each candidate gets a status: fits, unverified
        (a critical value is unknown), suspicious (its PLM record contradicts itself) or fails, with the
        rules it passed/failed and, if relaxing a rule would help, needs_tolerance_pct.
        cad_required=true: only parts that have a CAD model (use this to find a CAD model for a part)."""
        return await session.search(subject, cad_required, limit)

    async def verify_part(item_number: str) -> dict:
        """Do not trust a PLM record blindly: compare what its name/description say with its PLM fields and
        with the size measured from its CAD geometry. Returns contradictions and a verdict
        (consistent, suspicious, no geometry to check against). Use it on every part you recommend."""
        return await session.verify(item_number)

    async def relax_rule(subject: str, attribute: str, tolerance_pct: float, reason: str) -> dict:
        """Widen the tolerance of one non-critical 'within' rule when nothing fits, with an engineering
        reason. The guardrails refuse critical rules and anything beyond 30 %. Search again afterwards."""
        return session.relax(subject, attribute, tolerance_pct, reason)

    async def propose_envelope_model(subject: str) -> dict:
        """Last resort when no CAD model can be found: a simple placeholder model (cylinder or box) from the
        understood overall size, for the engineer to approve. Nothing is written to CAD by this tool."""
        return session.envelope(subject)

    return [_tool(fn) for fn in (plm_overview, plm_parts_without_cad, plm_item, understand_part,
                                 search_parts, verify_part, relax_rule, propose_envelope_model)]
