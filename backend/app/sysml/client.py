"""HTTP client for the SysML v2 API as implemented by Flexo MMS (flexo-mms-sysmlv2).

Only HTTP + JSON here -- no SysML knowledge (that is parser.py).

Endpoints flexo-mms-sysmlv2 v0.2 implements (its src/main/kotlin/.../apis/*.kt):
    GET/POST   /projects                         GET/PUT/DELETE /projects/{p}
    GET/POST   /projects/{p}/branches            GET/DELETE     /projects/{p}/branches/{b}
    GET/POST   /projects/{p}/commits             GET            /projects/{p}/commits/{c}
    GET        /projects/{p}/commits/{c}/elements[/{e}]   GET   /projects/{p}/commits/{c}/roots
NOT implemented yet (501): commit changes, diff, merge -- diffs are computed
client-side (diff.py).

Errors arrive as ``SysmlError`` -- the same shape as ``CadError``:
``status`` (HTTP status the backend answers with), ``code``, ``message``, ``detail``.
"""

import json
import uuid

import aiohttp


class SysmlError(Exception):
    def __init__(self, status, code, message, detail=None):
        super().__init__("%s: %s" % (code, message))
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


def _timeout(total):
    """Connecting gets its own, shorter limit, so "nobody there" is told apart from "slow".

    On Windows a connection to a closed port is not refused at once: the SYN is
    retried for about 2 s. Without a separate connect limit that ends as a plain
    timeout and a stopped Flexo would look like a slow one.
    """
    return aiohttp.ClientTimeout(total=total, sock_connect=min(3.0, total / 2))


class FlexoClient:
    def __init__(self, config):
        self.config = config
        self.base = config.api_url.rstrip("/")
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            headers = {"Accept": "application/json"}
            if self.config.token:
                token = self.config.token
                headers["Authorization"] = token if token.lower().startswith("bearer ") else "Bearer " + token
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=_timeout(self.config.timeout_s),
            )
        return self._session

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # -- low level --------------------------------------------------------

    async def request(self, method, path, *, params=None, body=None, timeout=None):
        session = await self._get_session()
        url = self.base + path
        params = {k: v for k, v in (params or {}).items() if v is not None} or None
        kwargs = {"params": params}
        if body is not None:
            kwargs["json"] = body
        if timeout is not None:
            kwargs["timeout"] = _timeout(timeout)
        try:
            async with session.request(method, url, **kwargs) as response:
                text = await response.text()
                status = response.status
        except aiohttp.ConnectionTimeoutError as exc:   # could not connect in time = not there
            raise SysmlError(503, "sysml_unreachable",
                             "SysML v2 API not reachable at %s" % self.base,
                             {"reason": "connect_timeout"}) from exc
        except TimeoutError as exc:   # before ClientConnectionError: ServerTimeoutError is both
            raise SysmlError(504, "sysml_timeout",
                             "SysML v2 API did not answer %s %s in time" % (method, path),
                             {"reason": "timeout"}) from exc
        except (aiohttp.ClientConnectionError, OSError) as exc:
            raise SysmlError(503, "sysml_unreachable",
                             "SysML v2 API not reachable at %s" % self.base,
                             {"reason": "connect_failed", "error": str(exc)}) from exc

        if status >= 400:
            detail = {"upstreamStatus": status, "body": text[:2000], "method": method, "path": path}
            if status == 404:
                raise SysmlError(404, "sysml_not_found", "Not found in the SysML repository: %s" % path, detail)
            if status in (401, 403):
                raise SysmlError(502, "sysml_unauthorized",
                                 "SysML v2 API rejected the credentials (check SYSML_API_TOKEN / FLEXO_AUTH)", detail)
            raise SysmlError(502, "sysml_upstream_error",
                             "SysML v2 API answered %s %s with HTTP %d" % (method, path, status), detail)
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return text

    async def get(self, path, **params):
        return await self.request("GET", path, params=params)

    async def post(self, path, body, **params):
        return await self.request("POST", path, params=params, body=body)

    # -- projects, branches, commits --------------------------------------

    async def list_projects(self):
        return await self.get("/projects") or []

    async def get_project(self, project_id):
        return await self.get("/projects/%s" % project_id)

    async def create_project(self, name, description="", project_id=None):
        body = {"@type": "Project", "@id": project_id or str(uuid.uuid4()),
                "name": name, "description": description}
        return await self.post("/projects", body)

    async def list_branches(self, project_id):
        return await self.get("/projects/%s/branches" % project_id) or []

    async def get_branch(self, project_id, branch_id):
        return await self.get("/projects/%s/branches/%s" % (project_id, branch_id))

    async def list_commits(self, project_id):
        """Newest first (Flexo sorts by ``created`` descending)."""
        return await self.get("/projects/%s/commits" % project_id) or []

    async def get_commit(self, project_id, commit_id):
        return await self.get("/projects/%s/commits/%s" % (project_id, commit_id))

    async def post_commit(self, project_id, changes, description="", branch_id=None):
        """Create a commit. A change: ``{"identity": {"@id": id}, "payload": {...} | None}``.

        Flexo semantics: the payload REPLACES all stored properties of the element,
        so always send the complete element. ``payload=None`` deletes it.
        """
        body = {
            "@type": "Commit",
            "description": description,
            "change": [
                dict({"@type": "DataVersion", "payload": c.get("payload")},
                     **({"identity": c["identity"]} if c.get("identity") else {}))
                for c in changes
            ],
        }
        return await self.post("/projects/%s/commits" % project_id, body, branchId=branch_id)

    # -- elements ---------------------------------------------------------

    async def get_elements(self, project_id, commit_id):
        """All elements of a commit -- Flexo returns them in one response, no paging."""
        return await self.get("/projects/%s/commits/%s/elements" % (project_id, commit_id)) or []

    async def get_element(self, project_id, commit_id, element_id):
        return await self.get("/projects/%s/commits/%s/elements/%s" % (project_id, commit_id, element_id))


async def create_sysmlv2_org(config, layer1_token):
    """One-time setup on a FRESH Flexo database: create the org the SysML v2 service writes into.

    The first request of flexo-mms-sysmlv2's Postman collection:
    ``PUT {layer1}/orgs/sysmlv2`` with Turtle. ``layer1_token`` = FLEXO_AUTH from
    flexo/env/flexo-sysmlv2.env.
    """
    token = layer1_token if layer1_token.lower().startswith("bearer ") else "Bearer " + layer1_token
    url = "%s/orgs/%s" % (config.layer1_url, config.org)
    body = '<> <http://purl.org/dc/terms/title> "%s"@en .' % config.org
    try:
        async with aiohttp.ClientSession(timeout=_timeout(config.timeout_s)) as session:
            async with session.put(url, data=body.encode(),
                                   headers={"Authorization": token, "Content-Type": "text/turtle"}) as response:
                if response.status >= 400:
                    raise SysmlError(502, "sysml_upstream_error",
                                     "layer1 answered PUT %s with HTTP %d" % (url, response.status),
                                     {"body": (await response.text())[:2000]})
    except (aiohttp.ClientConnectionError, OSError, TimeoutError) as exc:
        raise SysmlError(503, "sysml_unreachable", "Flexo layer1 not reachable at %s" % config.layer1_url,
                         {"reason": "connect_failed"}) from exc
