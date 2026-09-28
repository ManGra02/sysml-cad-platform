"""Ist die gebaute Oberflaeche aktuell?

Vergleicht den juengsten Zeitstempel der Frontend-Quellen mit dem Build in
backend/app/static/. Genutzt von scripts/start.* (baut bei Bedarf neu) und
scripts/doctor.py.

    python scripts/build_status.py      -> Ausgabe fresh|stale|missing, Exit 0|1|2
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(REPO, "frontend")
BUILT_INDEX = os.path.join(REPO, "backend", "app", "static", "index.html")

#: Was den Build beeinflusst. routeTree.gen.ts wird vom Build selbst erzeugt
#: und zaehlt deshalb nicht -- sonst waere jeder Build sofort wieder "veraltet".
SOURCES = ("src", "index.html", "package.json", "pnpm-lock.yaml", "vite.config.ts",
           "tsconfig.json", "tsconfig.app.json", "components.json")
IGNORED = ("routeTree.gen.ts",)


def newest_source():
    newest, newest_path = 0.0, None
    for entry in SOURCES:
        path = os.path.join(FRONTEND, entry)
        if os.path.isfile(path):
            candidates = [path]
        elif os.path.isdir(path):
            candidates = [
                os.path.join(root, name)
                for root, _dirs, files in os.walk(path)
                for name in files
                if name not in IGNORED
            ]
        else:
            continue
        for candidate in candidates:
            mtime = os.path.getmtime(candidate)
            if mtime > newest:
                newest, newest_path = mtime, candidate
    return newest, newest_path


def status():
    """('fresh'|'stale'|'missing', juengste Quelldatei)."""
    if not os.path.isfile(BUILT_INDEX):
        return "missing", None
    newest, path = newest_source()
    if newest > os.path.getmtime(BUILT_INDEX):
        return "stale", path
    return "fresh", None


def main():
    state, path = status()
    print(state if path is None else "%s (%s)" % (state, os.path.relpath(path, REPO)))
    return {"fresh": 0, "stale": 1, "missing": 2}[state]


if __name__ == "__main__":
    sys.exit(main())
