"""/api/sysml/* -- the SysML model for the browser (and for anyone else over HTTP).

Project modules do not need these routes: they use ``self.ctx.sysml`` directly.
Errors in the platform's usual shape: ``{"error": {"code", "message", "detail"}}``.
"""

from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.sysml.client import SysmlError


class SetValue(BaseModel):
    value: float
    unit: str | None = None
    branch: str | None = None
    description: str | None = None


async def _sysml_error(_request, exc):
    body = {"code": exc.code, "message": exc.message}
    if exc.detail is not None:
        body["detail"] = exc.detail
    return JSONResponse({"error": body}, status_code=exc.status)


def install(app, service):
    """Mount /api/sysml/* and turn every SysmlError into the platform's error shape."""
    app.add_exception_handler(SysmlError, _sysml_error)
    app.include_router(build_router(service))


def build_router(service):
    router = APIRouter(prefix="/api/sysml", tags=["SysML"])

    async def snap(project, branch, commit, include_library=False):
        return await service.snapshot(project, branch_id=branch, commit_id=commit,
                                      include_library=include_library)

    @router.get("/status")
    async def status():
        """Is the SysML repository reachable? (Not reachable is a normal state.)"""
        return await service.status()

    @router.get("/projects")
    async def projects():
        return await service.projects()

    @router.get("/projects/{project}/commits")
    async def commits(project: str):
        return await service.commits(project)

    @router.get("/projects/{project}/snapshot")
    async def snapshot(project: str, branch: str | None = None, commit: str | None = None,
                       include_library: bool = False):
        """The whole model at one commit in the common engineering model."""
        return (await snap(project, branch, commit, include_library)).to_dict()

    @router.get("/projects/{project}/tree", response_class=PlainTextResponse)
    async def tree(project: str, branch: str | None = None, commit: str | None = None):
        s = await snap(project, branch, commit)
        return PlainTextResponse("# %s @ %s\n\n%s\n" % (s.project_id, s.version, s.tree_text()))

    @router.get("/projects/{project}/parts")
    async def parts(project: str, leafOnly: bool = False, branch: str | None = None,
                    commit: str | None = None):
        """Part usages. ``leafOnly`` = physical parts without sub-parts (need a CAD model)."""
        s = await snap(project, branch, commit)
        items = s.leaf_parts() if leafOnly else s.parts()
        return {"version": s.version, "parts": [asdict(p) for p in items]}

    @router.get("/projects/{project}/requirements")
    async def requirements(project: str, branch: str | None = None, commit: str | None = None):
        s = await snap(project, branch, commit)
        return {"version": s.version,
                "requirements": [asdict(r) for r in s.requirements()],
                "satisfies": [asdict(r) for r in s.relations if r.kind == "satisfies"]}

    @router.get("/projects/{project}/attributes")
    async def attributes(project: str, element: str | None = None, branch: str | None = None,
                         commit: str | None = None):
        s = await snap(project, branch, commit)
        items = s.attributes_of(element) if element else s.attributes
        return {"version": s.version, "attributes": [asdict(a) for a in items]}

    @router.get("/projects/{project}/elements/{element_id}")
    async def element(project: str, element_id: str, branch: str | None = None,
                      commit: str | None = None):
        s = await snap(project, branch, commit)
        el = s.element(element_id)
        if el is None:
            raise SysmlError(404, "sysml_element_not_found",
                             "Element %s not found at commit %s" % (element_id, s.version))
        return {"version": s.version, "element": asdict(el),
                "attributes": [asdict(a) for a in s.attributes_of(element_id)],
                "children": [asdict(c) for c in s.children(element_id)],
                "relations": [asdict(r) for r in s.relations if element_id in (r.source_id, r.target_id)]}

    @router.get("/projects/{project}/diff")
    async def diff(project: str, base: str, compare: str):
        """What changed between two commits (Flexo has no diff endpoint yet)."""
        return await service.diff(project, base, compare)

    @router.put("/projects/{project}/attributes/{attribute_id}/value")
    async def set_value(project: str, attribute_id: str, body: SetValue):
        """Write a new value for an attribute -> a new commit in the repository."""
        return await service.write_attribute_value(project, attribute_id, body.value, unit=body.unit,
                                                   branch_id=body.branch, description=body.description)

    return router
