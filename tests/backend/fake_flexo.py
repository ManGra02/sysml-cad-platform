"""In-memory stand-in for the flexo-sysmlv2 service -- for tests and for work without Docker.

Mimics the part of the SysML v2 API the adapter uses, with Flexo's semantics:
a commit payload REPLACES the whole element, payload null deletes it, the
branch head moves. It is not Flexo: no auth, no RDF, no persistence.

    cd backend
    uv run python ../tests/backend/fake_flexo.py --port 8083
"""

import argparse
import copy
import re
import uuid
from datetime import datetime, timezone

from aiohttp import web

VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FakeFlexo:
    def __init__(self):
        self.projects = {}
        self.branches = {}   # project -> branch id -> branch
        self.commits = {}    # project -> commit id -> commit
        self.states = {}     # commit id -> {element id -> element}
        self.requests = []
        self.app = web.Application(middlewares=[self._record])
        r = self.app.router
        r.add_get("/projects", self._list_projects)
        r.add_post("/projects", self._create_project)
        r.add_get("/projects/{p}", self._get_project)
        r.add_get("/projects/{p}/branches", self._list_branches)
        r.add_get("/projects/{p}/branches/{b}", self._get_branch)
        r.add_get("/projects/{p}/commits", self._list_commits)
        r.add_post("/projects/{p}/commits", self._post_commit)
        r.add_get("/projects/{p}/commits/{c}", self._get_commit)
        r.add_get("/projects/{p}/commits/{c}/elements", self._elements)
        r.add_get("/projects/{p}/commits/{c}/elements/{e}", self._element)
        self._runner = None
        self.port = None

    async def start(self, port=0, host="127.0.0.1"):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return "http://%s:%d" % (host, self.port)

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()

    @web.middleware
    async def _record(self, request, handler):
        self.requests.append((request.method, request.path_qs))
        return await handler(request)

    def _project(self, request):
        pid = request.match_info["p"]
        if pid not in self.projects:
            raise web.HTTPNotFound(text="project %s not found" % pid)
        return pid

    async def _list_projects(self, _request):
        return web.json_response(list(self.projects.values()))

    async def _create_project(self, request):
        body = await request.json()
        pid = body.get("@id") or str(uuid.uuid4())
        if not VALID_ID.match(pid):
            raise web.HTTPBadRequest(text="projectId must match [a-zA-Z0-9_-]+")
        bid = (body.get("defaultBranch") or {}).get("@id") or str(uuid.uuid4())
        project = {"@id": pid, "@type": "Project", "name": body.get("name", ""),
                   "description": body.get("description", ""), "created": _now(),
                   "defaultBranch": {"@id": bid}}
        self.projects[pid] = project
        self.commits[pid] = {}
        self.branches[pid] = {bid: {"@id": bid, "@type": "Branch", "name": "main", "created": _now(),
                                    "owningProject": {"@id": pid}, "head": None, "referencedCommit": None}}
        return web.json_response(project)

    async def _get_project(self, request):
        return web.json_response(self.projects[self._project(request)])

    async def _list_branches(self, request):
        return web.json_response(list(self.branches[self._project(request)].values()))

    async def _get_branch(self, request):
        branch = self.branches[self._project(request)].get(request.match_info["b"])
        if branch is None:
            raise web.HTTPNotFound()
        return web.json_response(branch)

    async def _list_commits(self, request):
        commits = sorted(self.commits[self._project(request)].values(), key=lambda c: c["created"], reverse=True)
        return web.json_response(commits)

    async def _get_commit(self, request):
        commit = self.commits[self._project(request)].get(request.match_info["c"])
        if commit is None:
            raise web.HTTPNotFound()
        return web.json_response(commit)

    async def _post_commit(self, request):
        pid = self._project(request)
        branch = self.branches[pid][request.query.get("branchId") or self.projects[pid]["defaultBranch"]["@id"]]
        previous = (branch.get("head") or {}).get("@id")
        state = copy.deepcopy(self.states.get(previous, {})) if previous else {}
        body = await request.json()
        for change in body.get("change", []):
            payload = change.get("payload")
            eid = (change.get("identity") or {}).get("@id") or (payload or {}).get("@id") or str(uuid.uuid4())
            if payload is None:
                state.pop(eid, None)
                continue
            element = {k: v for k, v in payload.items() if k != "@id"}   # replace the whole element
            element["@id"] = eid
            state[eid] = element
        cid = str(uuid.uuid4())
        commit = {"@id": cid, "@type": "Commit", "created": _now(), "description": body.get("description", ""),
                  "owningProject": {"@id": pid}, "previousCommit": {"@id": previous} if previous else None}
        self.commits[pid][cid] = commit
        self.states[cid] = state
        branch["head"] = branch["referencedCommit"] = {"@id": cid}
        return web.json_response(commit)

    async def _elements(self, request):
        self._project(request)
        state = self.states.get(request.match_info["c"])
        if state is None:
            raise web.HTTPNotFound()
        return web.json_response(list(state.values()))

    async def _element(self, request):
        self._project(request)
        element = self.states.get(request.match_info["c"], {}).get(request.match_info["e"])
        if element is None:
            raise web.HTTPNotFound()
        return web.json_response(element)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="In-memory SysML v2 API (Flexo stand-in), for development only")
    ap.add_argument("--port", type=int, default=8083)
    args = ap.parse_args()
    fake = FakeFlexo()
    print("Fake Flexo SysML v2 API on http://127.0.0.1:%d (in memory)" % args.port)
    web.run_app(fake.app, host="127.0.0.1", port=args.port, print=None)
