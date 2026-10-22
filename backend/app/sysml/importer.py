"""Import a .sysml file (textual notation) into the repository as a NEW project.

Flexo speaks only the JSON of the SysML v2 API. The text is parsed by the SysML v2 Pilot
kernel (Jupyter, ``sysml-kernel`` in flexo/docker-compose.yml, profile ``import``): the
backend runs three cells on a fresh kernel over Jupyter's REST and websocket API --

    %repo <SYSML_KERNEL_TARGET>          the kernel posts to Flexo, never to a default server
    <the .sysml text>                    parse; errors come back as printed "ERROR:..." lines
    %publish -d --project="<name>" <Package>

-- and the kernel resolves names and the standard library (ISQ, SI, ...) and posts one
commit. ``-d`` includes derived properties: without them parser.py finds no attribute
values and no satisfy links. Adapted from bidirectional-sync/src/sysmlcad/publish.py
(Vincent Hey, branch merge/bidirectional-sync).

One upload = one new project: ``%publish`` into an existing project name would add a
commit with all-new element ids, so a taken name gets a suffix ("Box (2)").
"""

import asyncio
import re
import uuid

import aiohttp

from app.sysml.client import SysmlError, _timeout

#: Upper limit for the text of one import
MAX_TEXT = 2_000_000
#: A cold kernel (a JVM) takes ~10-20 s before the websocket handshake completes
OPEN_TIMEOUT_S = 120
#: Per cell; publishing a few thousand elements to Flexo takes ~30 s
CELL_TIMEOUT_S = 600

_lock = asyncio.Lock()   # one import at a time: the free-name check must hold until the publish

_NAME = r"(?:'(?:[^'\\]|\\.)*'|[A-Za-z_][A-Za-z0-9_]*)"
_PACKAGE = re.compile(r"\bpackage\s+(?:<\s*" + _NAME + r"\s*>\s*)?(" + _NAME + ")")


def _blank_comments(text):
    """The text with comments and string literals replaced by spaces (positions kept)."""
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two in ("//", "/*"):
            end = text.find("\n", i) if two == "//" else text.find("*/", i + 2)
            end = n if end < 0 else end + (0 if two == "//" else 2)
            out.append(re.sub(r"[^\n]", " ", text[i:end]))
            i = end
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(" " * (min(j, n - 1) - i + 1))
            i = j + 1
        elif text[i] == "'":   # quoted name: keep it, but braces inside do not count
            j = i + 1
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def top_level_packages(text):
    """Names of the packages at the top of a .sysml text, as written (quoted names keep quotes)."""
    clean = _blank_comments(text)
    depth, top = 0, []
    for i, ch in enumerate(clean):
        if ch in "{}":
            depth += 1 if ch == "{" else -1
        elif depth == 0 and ch == "p" and clean.startswith("package", i):
            m = _PACKAGE.match(clean, i)
            if m and (i == 0 or not (clean[i - 1].isalnum() or clean[i - 1] == "_")):
                top.append(m.group(1))
    return top


def plain_name(name):
    """'My Package' -> My Package"""
    if len(name) >= 2 and name[0] == name[-1] == "'":
        return re.sub(r"\\(.)", r"\1", name[1:-1])
    return name


def free_project_name(wanted, taken):
    taken = {t.lower() for t in taken if t}
    name, n = wanted, 2
    while name.lower() in taken:
        name, n = "%s (%d)" % (wanted, n), n + 1
    return name


def _errors(output):
    """The kernel's error lines, readable: "ERROR:x (2.sysml line : 3 column : 5)" -> "x (line 3, column 5)"."""
    return [re.sub(r"\(\d+\.sysml line : (\d+) column : (\d+)\)", r"(line \1, column \2)",
                   re.sub(r"^ERROR:?\s*", "", line))
            for line in output.splitlines() if line.startswith("ERROR")]


class _Kernel:
    """One SysML kernel on the Jupyter server, started for one import and shut down after."""

    def __init__(self, config):
        self.url = config.kernel_url.rstrip("/")
        self.headers = {"Authorization": "token " + config.kernel_token}
        self.session = None
        self.kernel_id = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers, timeout=_timeout(OPEN_TIMEOUT_S))
        try:
            async with self.session.post(self.url + "/api/kernels", json={"name": "sysml"}) as r:
                body = await r.text()
                if r.status in (401, 403):
                    raise SysmlError(502, "sysml_kernel_unauthorized",
                                     "Jupyter at %s rejected the token (check SYSML_KERNEL_TOKEN)" % self.url)
                if r.status >= 400:
                    raise SysmlError(502, "sysml_kernel_error",
                                     "Jupyter could not start the SysML kernel (HTTP %d)" % r.status,
                                     {"body": body[:2000]})
                self.kernel_id = (await r.json(content_type=None))["id"]
        except (aiohttp.ClientConnectionError, OSError, TimeoutError) as exc:
            await self.session.close()
            raise SysmlError(503, "sysml_kernel_unreachable",
                             "SysML kernel (Jupyter) not reachable at %s" % self.url,
                             {"error": str(exc)}) from exc
        except BaseException:
            await self.session.close()
            raise
        return self

    async def __aexit__(self, *exc):
        try:
            if self.kernel_id:
                async with self.session.delete(self.url + "/api/kernels/" + self.kernel_id):
                    pass
        except (aiohttp.ClientError, OSError, TimeoutError):
            pass
        finally:
            await self.session.close()

    async def run(self, cells):
        """Run the cells in order and return what each printed. Stops after the first cell that
        fails -- the SysML kernel reports parse errors as printed text and still answers ``ok``."""
        ws_url = re.sub(r"^http", "ws", self.url) + "/api/kernels/%s/channels" % self.kernel_id
        session_id, outputs = uuid.uuid4().hex, []
        try:
            async with self.session.ws_connect(ws_url, max_msg_size=0,
                                               timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                for code in cells:
                    msg_id = uuid.uuid4().hex
                    await ws.send_json({
                        "header": {"msg_id": msg_id, "username": "sysml-cad-platform", "session": session_id,
                                   "msg_type": "execute_request", "version": "5.3"},
                        "parent_header": {}, "metadata": {}, "buffers": [], "channel": "shell",
                        "content": {"code": code, "silent": False, "store_history": False,
                                    "user_expressions": {}, "allow_stdin": False, "stop_on_error": True},
                    })
                    printed, reply, idle = [], None, False
                    while not (idle and reply):
                        msg = await ws.receive_json(timeout=CELL_TIMEOUT_S)
                        if msg.get("parent_header", {}).get("msg_id") != msg_id:
                            continue
                        kind, content = msg["msg_type"], msg["content"]
                        if kind == "stream":
                            printed.append(content.get("text", ""))
                        elif kind in ("execute_result", "display_data"):
                            printed.append(content.get("data", {}).get("text/plain", "") + "\n")
                        elif kind == "error":
                            printed.append("ERROR %s: %s\n" % (content.get("ename"), content.get("evalue")))
                        elif kind == "status" and content.get("execution_state") == "idle":
                            idle = True
                        elif kind == "execute_reply":
                            reply = content.get("status")
                    outputs.append("".join(printed))
                    if reply != "ok" or _errors(outputs[-1]):
                        break
        except TimeoutError as exc:
            raise SysmlError(504, "sysml_kernel_timeout",
                             "The SysML kernel did not finish in time", {"output": "".join(outputs)}) from exc
        except (aiohttp.ClientError, OSError) as exc:
            raise SysmlError(503, "sysml_kernel_unreachable",
                             "Lost the connection to the SysML kernel at %s" % self.url,
                             {"error": str(exc), "output": "".join(outputs)}) from exc
        return outputs


async def import_sysml(text, config, client, project_name=None):
    """Parse ``text`` with the SysML kernel and publish its top-level package as a new project.

    Returns ``{"projectId", "projectName", "commitId", "package", "output"}``.
    """
    if len(text) > MAX_TEXT:
        raise SysmlError(413, "sysml_import_too_large", "The file is larger than %d characters" % MAX_TEXT)
    packages = top_level_packages(text)
    if len(packages) != 1:
        raise SysmlError(400, "sysml_import_package",
                         "The file must contain exactly one top-level package (found %s)"
                         % (", ".join(plain_name(p) for p in packages) or "none"),
                         {"packages": [plain_name(p) for p in packages]})
    package = packages[0]

    async with _lock:
        taken = [p.get("name") for p in await client.list_projects()]
        name = free_project_name((project_name or plain_name(package)).replace('"', "'").strip(), taken)
        async with _Kernel(config) as kernel:
            outputs = await kernel.run([
                "%repo " + config.kernel_target,
                text,
                '%%publish -d --project="%s" %s' % (name, package),
            ])
    output = "\n".join(o.strip() for o in outputs if o.strip())

    if len(outputs) < 3 or _errors(outputs[-1]):
        failed = outputs[-1] if outputs else ""
        syntax = len(outputs) == 2
        raise SysmlError(422 if syntax else 502,
                         "sysml_import_syntax" if syntax else "sysml_import_failed",
                         (_errors(failed) or ["The SysML kernel could not publish the model"])[0],
                         {"errors": _errors(failed), "output": output})

    published = outputs[-1]
    target = re.search(r"API base path:\s*(\S+)", published)
    if target and target.group(1).rstrip("/") != config.kernel_target.rstrip("/"):
        raise SysmlError(502, "sysml_import_wrong_target",
                         "The kernel published to %s, not to %s" % (target.group(1), config.kernel_target),
                         {"output": output})
    commit = re.search(r"Successfully posted commit:\s*([0-9a-fA-F-]{36})", published)
    project = re.search(r"Saved to Project .*\(([0-9a-fA-F-]{36})\)", published)
    project_id = project.group(1) if project else next(
        (p.get("@id") for p in await client.list_projects() if p.get("name") == name), None)
    if not commit or not project_id:
        raise SysmlError(502, "sysml_import_failed", "The SysML kernel did not report a commit",
                         {"output": output})
    return {"projectId": project_id, "projectName": name, "commitId": commit.group(1),
            "package": plain_name(package), "output": output}


async def kernel_available(config):
    """Is the Jupyter server with the SysML kernel there? (Not there is a normal state.)"""
    try:
        async with aiohttp.ClientSession(timeout=_timeout(3.0)) as session:
            async with session.get(config.kernel_url.rstrip("/") + "/api/status",
                                   headers={"Authorization": "token " + config.kernel_token}) as r:
                return r.status == 200
    except (aiohttp.ClientError, OSError, TimeoutError):
        return False
