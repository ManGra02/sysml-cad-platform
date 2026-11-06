"""One CRA agent run: the PLM data, what the agent has understood, the rules it made.

The agent's tools (tools.py) are thin wrappers around these methods. A session lives
for one run: the PLM is read once at its start (always current), name reading is cached
on disk across runs (a part is read by the LLM once, ever).
"""

import asyncio
import hashlib

from app import config
from app.projects.cra import guardrails, plm, profile as profiles
from app.projects.cra.specs import SpecReader

CACHE_NAME = "cra_spec_cache.json"
_reading = asyncio.Lock()   # two runs at once must not read the same new parts twice


class SessionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class CraSession:
    def __init__(self, ctx, load_parts=None, cache_file=None):
        self.ctx = ctx
        self.load_parts = load_parts or plm.load_parts
        self.cache_file = cache_file or config.state_dir() / CACHE_NAME
        self._llm = None
        self._reader = None
        self.records = None        # PLM records
        self.cands = None          # records + what their text says (specs)
        self.groups = {}
        self.profiles = {}         # subject -> profile
        self.rules = {}            # subject -> rules
        self.journal = []          # what the agent decided along the way (relaxed rules, ...)

    # -- plumbing -------------------------------------------------------------
    @property
    def llm(self):
        if self._llm is None:
            self._llm = self.ctx.ai.chat_model(temperature=0, reasoning=False)
        return self._llm

    @property
    def reader(self):
        if self._reader is None:
            self._reader = SpecReader(self.llm, self.cache_file)
        return self._reader

    @staticmethod
    def _text(rec):
        return rec["name"] + (" -- " + rec["description"] if rec.get("description") else "")

    @staticmethod
    def _key(rec):
        text = CraSession._text(rec)
        return "%s|%s" % (rec["item_number"], hashlib.sha1(text.encode()).hexdigest()[:12])

    async def _load(self):
        if self.cands is not None:
            return
        self.records = await self.load_parts()
        async with _reading:
            await self.reader.read([(self._key(r), self._text(r)) for r in self.records])
        cands = []
        for rec in self.records:
            spec = self.reader.spec(self._key(rec))
            attrs = dict(spec["attrs"])
            for k, v in rec["attributes"].items():          # real PLM values win over the text
                if v not in (None, ""):
                    attrs[guardrails.snake(k)] = guardrails.norm_val(v)
            material = (rec.get("material") or spec["material"]).strip().lower()
            if material:
                attrs.setdefault("material", material)
            if rec.get("mass_kg") is not None:
                attrs["mass_kg"] = rec["mass_kg"]
            ext = plm.extents(rec)
            cands.append({**rec, "category": spec["category"], "type": spec["type"],
                          "function": spec["function"], "material_read": spec["material"],
                          "attrs": attrs, "extents": ext,
                          "plm_issues": guardrails.plausibility(rec, spec, ext)})
        self.cands = cands

    async def _groups(self, extra=()):
        words = {c["category"] for c in self.cands} | set(extra)
        self.groups = await self.reader.groups(words)

    def _find(self, item_number):
        for c in self.cands:
            if c["item_number"].lower() == str(item_number).strip().lower():
                return c
        raise SessionError("item_not_found", "No PLM part %r" % item_number)

    def _subject(self, subject):
        if subject not in self.profiles:
            raise SessionError("not_understood", "Call understand_part for %r first" % subject)
        return self.profiles[subject], self.rules[subject]

    @staticmethod
    def _cad(c):
        if c["cad"] is None:
            return "unknown"
        return sorted({f["format"] for f in c["cad"]}) or "none"

    # -- what the tools do ------------------------------------------------------
    async def overview(self):
        await self._load()
        known = [c for c in self.cands if c["cad"] is not None]
        return {"parts": len(self.cands),
                "with_cad": sum(1 for c in known if c["cad"]),
                "without_cad": sum(1 for c in known if not c["cad"]),
                "cad_info_available": bool(known),
                "with_contradictions": sum(1 for c in self.cands if c["plm_issues"]),
                "kinds": sorted({c["category"] for c in self.cands if c["category"]})}

    async def without_cad(self, limit=50):
        await self._load()
        rows = [c for c in self.cands if c["cad"] == []]
        return {"count": len(rows), "parts": [{"item_number": c["item_number"], "name": c["name"],
                                               "kind": c["category"]} for c in rows[:limit]]}

    async def item(self, item_number):
        await self._load()
        c = self._find(item_number)
        return {"item_number": c["item_number"], "name": c["name"], "description": c["description"],
                "material": c["material"], "mass_kg": c["mass_kg"], "part_type": c["part_type"],
                "attributes": c["attributes"], "cad_files": c["cad"], "kind": c["category"]}

    async def understand(self, subject, description, attributes=None):
        await self._load()
        prof, rules, notes = await profiles.understand(self.llm, description, attributes)
        self.profiles[subject], self.rules[subject] = prof, rules
        return {"subject": subject, **prof,
                "rules": [{k: r[k] for k in ("attribute", "check", "value", "tolerance_pct", "critical", "reason")}
                          for r in rules],
                "guardrail_notes": notes}

    async def search(self, subject, cad_required=False, limit=5):
        await self._load()
        prof, rules = self._subject(subject)
        await self._groups([prof["category"]])
        pool = [c for c in self.cands if c["item_number"].lower() != str(subject).strip().lower()]
        if cad_required:
            pool = [c for c in pool if c["cad"]]
        ranked = guardrails.rank(guardrails.evaluate(prof, rules, c, self.groups) for c in pool)
        by_number = {c["item_number"]: c for c in pool}
        out = []
        for r in ranked[:max(1, min(int(limit), 10))]:
            c = by_number[r["item_number"]]
            out.append({**r, "cad": self._cad(c), "size_mm": c["extents"]})
        counts = {s: sum(1 for r in ranked if r["status"] == s) for s in guardrails.STATUS_ORDER}
        return {"subject": subject, "searched": len(pool), "same_kind_or_job": len(ranked),
                "counts": counts, "candidates": out}

    async def verify(self, item_number):
        await self._load()
        c = self._find(item_number)
        return {"item_number": c["item_number"], "name": c["name"], "description": c["description"],
                "plm_fields": {"material": c["material"], "mass_kg": c["mass_kg"], "attributes": c["attributes"]},
                "text_says": {"kind": c["category"], "material": c["material_read"], "values": c["attrs"]},
                "cad": self._cad(c), "measured_size_mm": c["extents"],
                "contradictions": c["plm_issues"],
                "verdict": ("suspicious" if c["plm_issues"] else
                            "consistent" if c["extents"] else "no geometry to check against")}

    def relax(self, subject, attribute, tolerance_pct, reason):
        _, rules = self._subject(subject)
        attribute = guardrails.snake(attribute)
        for i, rule in enumerate(rules):
            if rule["attribute"] == attribute:
                new, refusal = guardrails.relax(rule, tolerance_pct)
                if refusal:
                    return {"relaxed": False, "refused_by_guardrail": refusal}
                rules[i] = new
                self.journal.append("%s: %s within %g %% -> %g %% (%s)" % (
                    subject, attribute, rule["tolerance_pct"], new["tolerance_pct"], reason))
                return {"relaxed": True, "rule": {k: new[k] for k in ("attribute", "check", "value", "tolerance_pct")}}
        return {"relaxed": False, "refused_by_guardrail": "no rule on %s for %s" % (attribute, subject)}

    def envelope(self, subject):
        """A placeholder model from the understood overall size: a cylinder for round parts, else a box."""
        prof, rules = self._subject(subject)
        vals = {**prof["properties"], **{r["attribute"]: r["value"] for r in rules}}
        nums = {k: guardrails.num(v) for k, v in vals.items() if guardrails.num(v) and k.endswith("_mm")}
        dia = next((nums[k] for k in ("outer_diameter_mm", "diameter_mm") if k in nums), None)
        length = next((nums[k] for k in ("length_mm", "height_mm", "thickness_mm") if k in nums), None)
        label = "CRA envelope - %s" % subject
        if dia and length:
            return {"subject": subject, "label": label, "type": "Part::Cylinder",
                    "props": {"Radius": "%g mm" % (dia / 2), "Height": "%g mm" % length},
                    "basis": "round part: diameter %g mm, length %g mm" % (dia, length)}
        box = [nums.get(k) for k in ("length_mm", "width_mm", "height_mm")]
        if all(box):
            return {"subject": subject, "label": label, "type": "Part::Box",
                    "props": {"Length": "%g mm" % box[0], "Width": "%g mm" % box[1], "Height": "%g mm" % box[2]},
                    "basis": "box %g x %g x %g mm" % tuple(box)}
        raise SessionError("size_unknown", "The overall size of %r is not known (need diameter + length, or "
                                           "length + width + height)" % subject)
