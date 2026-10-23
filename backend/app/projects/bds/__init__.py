"""Bi-Directional Synchronization -- keep the SysML v2 model and the CAD model in sync.

The domain logic is the bidirectional-sync PoC, ported onto the platform: SysML from
Flexo (``ctx.sysml``), CAD from FreeCAD through the bridge (``ctx.cad``), the LLM via
``ctx.ai`` (model OLLAMA_MODEL_BDS). One WORKSPACE = one SysML project, one FreeCAD
document and the mapping between them (workspace.py).

    catalog -> propose (difflib | ai) -> gates -> proposals.yaml -> confirm -> mapping.yaml
    mapping + requirements + measurements -> verify (verdicts and gaps)
    mapping + requirements -> sync (limits into the FreeCAD sheet "SysML")

Rules that hold everywhere: the AI only proposes, it never evaluates; only confirmed
mapping entries take part in a run; SysML owns limits, CAD owns actual values; a gap
is never a pass.

Routes under /api/projects/bds.
"""

import functools

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.projects.bds import confirm as confirm_mod
from app.projects.bds import limits, verify
from app.projects.bds.adapters import AdapterPool
from app.projects.bds.freecad_snapshot import FreeCADSnapshot
from app.projects.bds.catalog import build_catalog
from app.projects.bds.extract import by_key, extract
from app.projects.bds.gates import check_mapping, check_proposal, unused_parts
from app.projects.bds.mapping import load_mapping
from app.projects.bds.model import RunContext
from app.projects.bds.proposals import add, load_proposals, save_proposals
from app.projects.bds.propose import DifflibProposer, dropped_report
from app.projects.bds.propose import run as propose_run
from app.projects.bds.propose_ai import OllamaProposer
from app.projects.bds.score import load_gold, score
from app.projects.bds.workspace import (
    BdsError,
    list_workspaces,
    load_workspace,
    save_workspace,
)
from app.projects.stub import StubModule


class WorkspaceSettings(BaseModel):
    sysml_project: str
    cad_document: str = ""
    axes: dict[str, str] | None = None
    limits_sheet: str | None = None


class ModelVersion(BaseModel):
    branch: str | None = None
    commit: str | None = None


class ProposeRequest(ModelVersion):
    proposer: str = "difflib"
    top: int = 1
    dry_run: bool = False


class ConfirmRequest(ModelVersion):
    requirement: str | None = None


class RejectRequest(BaseModel):
    reason: str = ""


class SyncRequest(ModelVersion):
    apply: bool = False


def _bds_errors(handler):
    """BdsError -> the platform's error shape. SysmlError and AiError have global handlers."""
    @functools.wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except BdsError as exc:
            body = {"code": exc.code, "message": exc.message}
            if exc.detail is not None:
                body["detail"] = exc.detail
            return JSONResponse({"error": body}, status_code=exc.status)
    return wrapper


class Session:
    """Everything one request needs, read once: workspace, model state, requirements,
    mapping, the CAD snapshot and the catalogue of both sides."""

    @classmethod
    async def open(cls, ctx, name, branch=None, commit=None):
        self = cls()
        self.workspace = load_workspace(name)
        pid, cid, _bid = await ctx.sysml.resolve_commit(self.workspace.sysml_project, branch, commit)
        self.elements = await ctx.sysml.raw_elements(pid, commit_id=cid)
        self.state = {"sysml_project_id": pid, "sysml_commit_id": cid}
        self.requirements, self.skipped = extract(self.elements)
        self.by_key = by_key(self.requirements)
        self.mapping = load_mapping(self.workspace.mapping_path)
        documents = [self.workspace.cad_document] + [
            p.cad_object.split("#", 1)[0] for p in self.mapping.parts.values() if p.adapter == FreeCADSnapshot.name]
        self.adapter = await FreeCADSnapshot.load(ctx.cad, documents, self.workspace.limits_sheet)
        self.pool = AdapterPool({FreeCADSnapshot.name: self.adapter})
        self.catalog = build_catalog(self.elements, self.adapter, self.workspace.axes,
                                     source="flexo:%s@%s" % (pid, cid))
        return self

    def context(self):
        return RunContext(workspace=self.workspace.name, **self.state)


class BdsModule(StubModule):
    id = "bds"
    title = "Bi-Directional Synchronization"
    description = "Keep the SysML v2 system model and the CAD model in sync in both directions."
    icon = "arrow-left-right"

    def _proposer(self, which):
        if which == "difflib":
            return DifflibProposer()
        if which == "ai":
            return OllamaProposer(self.ctx.ai)
        raise BdsError(400, "bds_unknown_proposer", "proposer %r: 'difflib' or 'ai'" % which)

    def register_routes(self, router):
        super().register_routes(router)

        # -- Workspaces ---------------------------------------------------

        @router.get("/workspaces")
        @_bds_errors
        async def workspaces():
            return {"workspaces": [w.to_dict() for w in list_workspaces()]}

        @router.get("/workspaces/{name}")
        @_bds_errors
        async def workspace(name: str):
            return load_workspace(name).to_dict()

        @router.put("/workspaces/{name}")
        @_bds_errors
        async def put_workspace(name: str, body: WorkspaceSettings):
            """Create or change a workspace. The SysML project must exist in Flexo."""
            await self.ctx.sysml.resolve_project_id(body.sysml_project)
            return save_workspace(name, body.sysml_project, body.cad_document, body.axes,
                                  body.limits_sheet).to_dict()

        # -- What is there ------------------------------------------------

        @router.get("/workspaces/{name}/catalog")
        @_bds_errors
        async def catalog(name: str, branch: str | None = None, commit: str | None = None):
            session = await Session.open(self.ctx, name, branch, commit)
            return {**session.catalog.to_dict(), **session.state,
                    "requirements": [r.to_dict() for r in session.requirements],
                    "not_extracted": session.skipped}

        @router.get("/workspaces/{name}/mapping")
        @_bds_errors
        async def mapping(name: str):
            return load_mapping(load_workspace(name).mapping_path).to_dict()

        @router.get("/workspaces/{name}/gates")
        @_bds_errors
        async def gates(name: str, branch: str | None = None, commit: str | None = None):
            """Is the MAPPING sound? (Not: is the design compliant -- that is verify.)"""
            session = await Session.open(self.ctx, name, branch, commit)
            checks = check_mapping(session.mapping, session.catalog, session.by_key, session.pool)
            counts = {v: sum(1 for c in checks if c.verdict == v) for v in ("valid", "unknown", "invalid")}
            return {"mapping_digest": session.mapping.digest, **session.state,
                    "entries": [c.to_dict() for c in checks], "summary": counts,
                    "unused_parts": unused_parts(session.mapping)}

        # -- Proposals ----------------------------------------------------

        @router.get("/workspaces/{name}/proposals")
        @_bds_errors
        async def proposals(name: str, status: str | None = None, check: bool = False,
                            branch: str | None = None, commit: str | None = None):
            """Stored proposals. ``check=true`` gates every pending one against the mapping
            as it is NOW (reads Flexo and FreeCAD) -- what a reviewer needs before deciding."""
            stored = [p for p in load_proposals(load_workspace(name).proposals_path)
                      if status is None or p.status == status]
            out = [p.to_dict() for p in stored]
            if check and any(p.pending for p in stored):
                session = await Session.open(self.ctx, name, branch, commit)
                for entry, proposal in zip(out, stored):
                    if proposal.pending:
                        entry["check"] = check_proposal(proposal, session.mapping, session.catalog,
                                                        session.by_key, session.pool).to_dict()
            return {"proposals": out}

        @router.post("/workspaces/{name}/proposals")
        @_bds_errors
        async def propose(name: str, body: ProposeRequest):
            """Suggest mapping entries. Nothing is applied: candidates past the gates land
            in proposals.yaml with status proposed (unless dry_run)."""
            proposer = self._proposer(body.proposer)
            session = await Session.open(self.ctx, name, body.branch, body.commit)
            kept, dropped = await propose_run(proposer, session.catalog, session.mapping,
                                              session.by_key, session.pool, top=max(1, body.top))
            added = []
            if not body.dry_run and kept:
                path = session.workspace.proposals_path
                stored, added = add(load_proposals(path), kept)
                save_proposals(stored, path)
            return {"proposer": proposer.name, "candidates": [p.to_dict() for p in kept],
                    "stored": [p.id for p in added], "rejected_by_gates": dropped_report(dropped),
                    "dropped_by_proposer": list(getattr(proposer, "dropped", []))}

        @router.post("/workspaces/{name}/proposals/{proposal_id}/confirm")
        @_bds_errors
        async def confirm(name: str, proposal_id: str, body: ConfirmRequest | None = None):
            """Gate once more, then write the proposal into mapping.yaml. ``requirement``
            links it to the requirement it is checked through -- without one, a run
            never uses the entry."""
            body = body or ConfirmRequest()
            session = await Session.open(self.ctx, name, body.branch, body.commit)
            return confirm_mod.confirm(session.workspace, proposal_id, session.catalog, session.by_key,
                                       session.pool, requirement=body.requirement)

        @router.post("/workspaces/{name}/proposals/{proposal_id}/reject")
        @_bds_errors
        async def reject(name: str, proposal_id: str, body: RejectRequest | None = None):
            return confirm_mod.reject(load_workspace(name), proposal_id, (body or RejectRequest()).reason)

        # -- Verification and sync ----------------------------------------

        @router.post("/workspaces/{name}/verify")
        @_bds_errors
        async def run_verify(name: str, body: ModelVersion | None = None):
            """Requirements against the CAD geometry -> verdicts and gaps."""
            body = body or ModelVersion()
            session = await Session.open(self.ctx, name, body.branch, body.commit)
            result = verify.run(session.requirements, session.skipped, session.mapping, session.pool,
                                session.context()).to_dict()
            session.workspace.save_last_run(result)
            self.ctx.publish("verify.done", {"workspace": name, "summary": result["summary"],
                                             "violated": result["violated"]})
            return result

        @router.get("/workspaces/{name}/verify/last")
        @_bds_errors
        async def last_verify(name: str):
            """The most recent verification result, as POST .../verify returned it."""
            last = load_workspace(name).last_run()
            if last is None:
                raise BdsError(404, "bds_no_run", "Workspace %r has not been verified yet" % name)
            return last

        @router.post("/workspaces/{name}/sync")
        @_bds_errors
        async def sync(name: str, body: SyncRequest | None = None):
            """Requirement limits into the FreeCAD sheet the sync owns. Dry run unless
            ``apply`` -- then one undo step in FreeCAD and a line in sync_log.jsonl."""
            body = body or SyncRequest()
            session = await Session.open(self.ctx, name, body.branch, body.commit)
            return await limits.sync(session.workspace, session.requirements, session.mapping,
                                     session.pool, session.state, apply=body.apply)

        @router.get("/workspaces/{name}/score")
        @_bds_errors
        async def run_score(name: str, proposer: str = "difflib", branch: str | None = None,
                            commit: str | None = None):
            """A proposer against the workspace's gold set (gold_mapping.yaml), from an
            empty mapping. Nothing is stored; with proposer=ai it costs a model call."""
            chosen = self._proposer(proposer)
            session = await Session.open(self.ctx, name, branch, commit)
            gold = load_gold(session.workspace.gold_path)
            result = await score(chosen, gold, session.catalog, session.by_key, session.pool)
            return {**result.to_dict(), "dropped_by_proposer": list(getattr(chosen, "dropped", []))}
