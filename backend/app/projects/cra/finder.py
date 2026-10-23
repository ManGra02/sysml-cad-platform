"""CRA search: required part (SysML attributes) -> best existing PLM part.

    finder = Finder(ctx)
    await finder.find({"partType": "Pulley", "teeth": 18, "boreDiameterMm": 12}, tolerance_pct=10)
    # -> {"best": {...} | None, "near_misses": [...], "checked", "same_function", "passed", "tolerance_pct"}

The PLM is read on every search (always current); the LLM only reads names it has not read before.
"""

import asyncio

from app import config
from app.projects.cra import matching, plm
from app.projects.cra.specs import SpecReader

CACHE_NAME = "cra_spec_cache.json"
_lock = asyncio.Lock()    # one search at a time: two would read the same new parts twice


class Finder:
    def __init__(self, ctx, load_parts=None, cache_file=None):
        self.ctx = ctx
        self.load_parts = load_parts or plm.load_parts
        self.cache_file = cache_file or config.state_dir() / CACHE_NAME

    async def find(self, attributes, tolerance_pct=matching.DEFAULT_TOL_PCT):
        tolerance_pct = min(max(float(tolerance_pct), 0.0), matching.MAX_TOL_PCT)
        rows = await self.load_parts()
        async with _lock:
            reader = SpecReader(self.ctx.ai.chat_model(temperature=0, reasoning=False), self.cache_file)
            keys = [(f"{r['item_number']}|{r['name']}", r["name"]) for r in rows]
            req_text = matching.requirement_text(attributes)
            req_key = f"REQ|{req_text}"
            await reader.read(keys + ([(req_key, req_text)] if req_text else []))
            cands = [self._candidate(r, reader.spec(k)) for r, (k, _) in zip(rows, keys)]
            req = matching.requirement_spec(attributes, reader.spec(req_key) if req_text else None)
            groups = await reader.groups({c["category"] for c in cands} | {req["category"]})
        return matching.rank(req, cands, tolerance_pct, groups)

    @staticmethod
    def _candidate(row, spec):
        spec = {**spec, "attrs": dict(spec["attrs"])}
        for k, v in (row.get("attributes") or {}).items():       # real PLM attributes win over the name
            if v is not None and v != "":
                spec["attrs"][matching.snake(k)] = matching.norm_val(v)
        spec["item_number"], spec["name"] = row["item_number"], row["name"]
        return spec
