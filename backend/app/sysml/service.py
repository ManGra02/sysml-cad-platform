"""The SysML side of the platform -- what project modules use as ``self.ctx.sysml``.

    snap = await self.ctx.sysml.snapshot("EBike Demo")     # project name or id; default branch head
    snap.parts(); snap.leaf_parts(); snap.requirements(); snap.attributes_of(part.id)
    await self.ctx.sysml.write_attribute_value("EBike Demo", attr.id, 11200, unit="g")   # -> new commit
    await self.ctx.sysml.diff("EBike Demo", old_commit, new_commit)

A snapshot is the whole model at ONE commit, already converted into the common
engineering model (models.py). ``snapshot.version`` is the commit id: record it
with every result so it can be traced to an exact model state (SRS FREQ-1).
Commits never change, so snapshots are cached per commit.
"""

import asyncio
import collections
import copy

from app.sysml import units
from app.sysml.client import FlexoClient, SysmlError
from app.sysml.config import SysmlConfig
from app.sysml.diff import diff_snapshots
from app.sysml.parser import normalise_elements, parse_elements

#: Parsed snapshots kept in memory (least recently used ones are dropped)
SNAPSHOT_CACHE = 16


class SysmlService:
    def __init__(self, config=None, client=None):
        self.config = config or SysmlConfig.from_env()
        self.client = client or FlexoClient(self.config)
        self._raw = collections.OrderedDict()    # (project, commit) -> elements
        self._snaps = collections.OrderedDict()  # (project, commit, include_library) -> snapshot

    async def start(self):
        """Nothing to connect: the repository is asked on demand."""

    async def stop(self):
        await self.client.close()

    # -- Status -----------------------------------------------------------

    async def status(self):
        try:
            projects = await self.client.list_projects()
        except SysmlError as exc:
            return {"url": self.config.api_url, "reachable": False, "code": exc.code, "message": exc.message}
        return {"url": self.config.api_url, "reachable": True, "projects": len(projects)}

    # -- Projects and versions -------------------------------------------

    async def projects(self):
        return [
            {"id": p.get("@id"), "name": p.get("name"), "description": p.get("description"),
             "defaultBranch": (p.get("defaultBranch") or {}).get("@id"), "created": p.get("created")}
            for p in await self.client.list_projects()
        ]

    async def resolve_project_id(self, project):
        """A project id or an exact (case-insensitive) project name."""
        projects = await self.client.list_projects()
        if any(p.get("@id") == project for p in projects):
            return project
        matches = [p for p in projects if (p.get("name") or "").lower() == project.lower()]
        if len(matches) == 1:
            return matches[0]["@id"]
        if len(matches) > 1:
            raise SysmlError(409, "sysml_ambiguous_project",
                             "Project name %r is ambiguous" % project, {"ids": [m["@id"] for m in matches]})
        raise SysmlError(404, "sysml_project_not_found", "Unknown SysML project %r" % project)

    async def resolve_commit(self, project, branch_id=None, commit_id=None):
        """-> (project_id, commit_id, branch_id). A commit wins; default = head of the default branch."""
        pid = await self.resolve_project_id(project)
        if commit_id:
            return pid, commit_id, branch_id
        if not branch_id:
            branch_id = ((await self.client.get_project(pid)).get("defaultBranch") or {}).get("@id")
        if branch_id:
            head = ((await self.client.get_branch(pid, branch_id)).get("head") or {}).get("@id")
            if head:
                return pid, head, branch_id
        commits = await self.client.list_commits(pid)
        if not commits:
            raise SysmlError(404, "sysml_empty_project", "SysML project %r has no commits yet" % project)
        return pid, commits[0]["@id"], branch_id

    async def commits(self, project):
        pid = await self.resolve_project_id(project)
        out = []
        for c in await self.client.list_commits(pid):
            previous = c.get("previousCommit")
            if isinstance(previous, list):
                previous = [x.get("@id") for x in previous]
            elif isinstance(previous, dict):
                previous = previous.get("@id")
            out.append({"id": c.get("@id"), "created": c.get("created"),
                        "description": c.get("description"), "previous": previous})
        return out

    # -- Reading ----------------------------------------------------------

    async def raw_elements(self, project, branch_id=None, commit_id=None):
        pid, cid, _ = await self.resolve_commit(project, branch_id, commit_id)
        return await self._raw_elements(pid, cid)

    async def _raw_elements(self, pid, cid):
        key = (pid, cid)
        if key not in self._raw:
            self._raw[key] = normalise_elements(await self.client.get_elements(pid, cid))
            _trim(self._raw)
        self._raw.move_to_end(key)
        return self._raw[key]

    async def snapshot(self, project, branch_id=None, commit_id=None, include_library=False):
        """The whole model at one commit, in the common model. One read per commit."""
        pid, cid, bid = await self.resolve_commit(project, branch_id, commit_id)
        key = (pid, cid, include_library)
        if key not in self._snaps:
            raw = await self._raw_elements(pid, cid)
            # parsing is pure CPU -- keep the event loop free for the bridge's event stream
            self._snaps[key] = await asyncio.to_thread(
                parse_elements, raw, project_id=pid, version=cid, branch_id=bid, include_library=include_library)
            _trim(self._snaps)
        self._snaps.move_to_end(key)
        return self._snaps[key]

    async def diff(self, project, base_commit, compare_commit):
        return diff_snapshots(await self.snapshot(project, commit_id=base_commit),
                              await self.snapshot(project, commit_id=compare_commit))

    # -- Writing ----------------------------------------------------------

    async def commit_changes(self, project, changes, description="", branch_id=None):
        pid = await self.resolve_project_id(project)
        return await self.client.post_commit(pid, changes, description=description, branch_id=branch_id)

    async def write_attribute_value(self, project, attribute_id, value, unit=None, branch_id=None,
                                    description=None):
        """Replace the number of an existing attribute value (e.g. the CAD mass -> SysML).

        Only the literal is rewritten; the unit stays as modelled. If ``unit`` is
        given and differs, the value is converted first (11200 g -> 11.2 kg).
        Returns the new commit.
        """
        pid, cid, bid = await self.resolve_commit(project, branch_id)
        snap = await self.snapshot(pid, commit_id=cid)
        attr = snap.attribute(attribute_id)
        if attr is None:
            raise SysmlError(404, "sysml_attribute_not_found",
                             "Attribute %s not found at commit %s" % (attribute_id, cid))
        if not attr.value_element_id:
            raise SysmlError(400, "sysml_no_literal",
                             "Attribute %r has no literal value to update (expression: %r)"
                             % (attr.name, attr.expression))
        if unit and attr.unit and units.normalise_symbol(unit) != units.normalise_symbol(attr.unit):
            try:
                value = units.convert(value, unit, attr.unit)
            except ValueError as exc:
                raise SysmlError(400, "invalid_value", str(exc), {"reason": "unit_mismatch",
                                                                 "expected": attr.unit}) from exc

        literal = copy.deepcopy({e["@id"]: e for e in await self._raw_elements(pid, cid)}[attr.value_element_id])
        if isinstance(value, float) and not value.is_integer():
            literal["@type"] = "LiteralRational"
        elif literal.get("@type") == "LiteralInteger":
            value = int(value)
        literal["value"] = value
        owner = snap.element(attr.owner_id)
        description = description or "Set %s.%s = %s [%s]" % (owner.name if owner else "?", attr.name,
                                                               value, attr.unit or "")
        # Flexo replaces all stored properties of an element -> send the complete literal
        return await self.client.post_commit(
            pid, [{"identity": {"@id": attr.value_element_id}, "payload": literal}],
            description=description, branch_id=bid)


def _trim(cache):
    while len(cache) > SNAPSHOT_CACHE:
        cache.popitem(last=False)
