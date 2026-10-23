"""The LLM reads part names into specs -- the only place in CRA where text is interpreted.

  * ``SpecReader.read(items)``  -- names -> specs, batched, parallel, cached on disk
  * ``SpecReader.groups(words)`` -- which kinds of part do the same job (screw = bolt), cached

Everything is cached (a part is read once, ever), so later searches need no LLM call.
"""

import asyncio
import hashlib
import json

from app.projects.cra.matching import empty_spec, norm_val, snake

BATCH = 20     # parts read per LLM call
WORKERS = 4    # LLM calls running at the same time

EXTRACT_PROMPT = """You read engineering part descriptions and turn them into specs.
For every part below return one JSON object. Reply with ONLY a JSON list, nothing else.
Keys:
- "id": the id given
- "category": ONE lowercase singular noun for what the part is (screw, nut, washer, key, gear, shaft, bearing, seal, housing, bracket, motor, tire ...)
- "type": short full type, e.g. "socket head cap screw"
- "function": 3 to 6 words on what it does, e.g. "fastens parts together"
- "material": lowercase, "" if unknown. A2 or A4 mean "stainless steel". Use "aluminum" for aluminium.
- "attrs": object with the part's properties. Use these names when they apply:
  length_mm, width_mm, height_mm, thickness_mm, diameter_mm, bore_diameter_mm, outer_diameter_mm,
  shaft_diameter_mm, thread_size (like "M6", no pitch), teeth, module_mm, pressure_angle_deg,
  load_rating_kn, mass_kg, head_type. Numbers are plain numbers in mm, kg, kN or degrees.
  Any other property: snake_case name with a unit suffix. Only include what the text states
  or what the named standard fixes for certain. Never guess.
Parts:
"""

GROUP_PROMPT = """Below is a list of part category words from an engineering parts catalogue.
Group the words that name parts which do the same job and can replace each other in a design.
Example: "screw" and "bolt" are one group. "nut", "washer", "shaft", "bearing" and "gear" are each their own group.
Generic words such as part, item, assembly or component stay alone.
Every word must be in exactly one group. Reply with ONLY a JSON list of lists of words.
Words:
"""


def _json_between(raw, open_, close):
    s = str(raw)
    a, b = s.find(open_), s.rfind(close)
    if a < 0 or b < a:
        raise ValueError("no JSON list")
    try:
        return json.loads(s[a:b + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc


def parse_specs(raw):
    return [d for d in _json_between(raw, "[", "]") if isinstance(d, dict)]


def parse_groups(raw):
    return [[str(w) for w in g] for g in _json_between(raw, "[", "]") if isinstance(g, list)]


def clean_spec(o):
    attrs = {snake(k): norm_val(v) for k, v in (o.get("attrs") or {}).items() if v not in (None, "")}
    return {"category": str(o.get("category", "")).strip().lower(),
            "type": str(o.get("type", "")).strip().lower(),
            "function": str(o.get("function", "")).strip().lower(),
            "material": str(o.get("material", "")).strip().lower(),
            "attrs": attrs}


def _text(reply):
    return getattr(reply, "content", reply)


class SpecReader:
    """``llm``: a LangChain chat model (``ctx.ai.chat_model(...)``); ``cache_file``: a JSON file."""

    def __init__(self, llm, cache_file):
        self.llm = llm
        self.cache_file = cache_file
        self.cache = {"specs": {}, "groups": {}}
        try:
            self.cache.update(json.loads(cache_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self._gate = asyncio.Semaphore(WORKERS)

    def _save(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self.cache), encoding="utf-8")
        except OSError:
            pass     # a cache that cannot be written only costs LLM calls next time

    def spec(self, key):
        return self.cache["specs"].get(key) or empty_spec()

    # -- names -> specs ----------------------------------------------------
    async def _ask(self, batch):
        prompt = EXTRACT_PROMPT + json.dumps([{"id": i, "text": t} for i, (_, t) in enumerate(batch)])
        async with self._gate:
            reply = await self.llm.ainvoke(prompt)
        got = {}
        for o in parse_specs(_text(reply)):
            try:
                i = int(o.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(batch):
                got[i] = clean_spec(o)
        return got

    async def _read_batch(self, batch):
        try:
            got = await self._ask(batch)
        except ValueError:
            got = {}
        for i, spec in got.items():
            self.cache["specs"][batch[i][0]] = spec
        missing = [b for i, b in enumerate(batch) if i not in got]
        if not missing:
            return
        if len(batch) == 1:
            self.cache["specs"][batch[0][0]] = {**empty_spec(), "failed": True}
        elif len(missing) == len(batch):      # nothing readable: split and retry
            mid = len(batch) // 2
            await asyncio.gather(self._read_batch(batch[:mid]), self._read_batch(batch[mid:]))
        else:
            await self._read_batch(missing)

    async def read(self, items):
        """items: ``[(key, text)]``. Reads what is not in the cache yet; returns how many were read."""
        specs = self.cache["specs"]
        todo = [(k, t) for k, t in dict(items).items() if k not in specs or specs[k].get("failed")]
        batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

        async def one(batch):
            await self._read_batch(batch)
            self._save()                      # progress is kept after every batch

        await asyncio.gather(*(one(b) for b in batches))
        return len(todo)

    # -- part kinds -> groups of the same job -----------------------------
    async def groups(self, words):
        """``{category word: group number}``; words in one group can replace each other."""
        words = sorted({w for w in words if w})
        h = hashlib.sha1("|".join(words).encode()).hexdigest()[:12]
        g = self.cache["groups"].get(h)
        if g is None:
            lists = []
            try:
                async with self._gate:
                    reply = await self.llm.ainvoke(GROUP_PROMPT + json.dumps(words))
                lists = parse_groups(_text(reply))
            except ValueError:
                pass                          # no grouping: only the exact same kind matches
            g, nid = {}, len(lists)
            for i, grp in enumerate(lists):
                for w in grp:
                    w = w.strip().lower()
                    if w in words and w not in g:
                        g[w] = i
            for w in words:
                if w not in g:
                    g[w] = nid
                    nid += 1
            self.cache["groups"][h] = g
            self._save()
        return g
