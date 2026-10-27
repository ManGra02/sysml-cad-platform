#!/bin/sh
# One-shot start helper for the persistent quad store (service quad-store-init).
#
# Fuseki keeps its data on disk (TDB2 in the docker volume flexo-quad-store), so the
# starting graphs of Flexo -- users, access policies, schema: mount/cluster.trig --
# are loaded ONCE, into an empty database. On every later start the data is there
# already and is left alone.
set -eu

FUSEKI="${FUSEKI:-http://quad-server:3030/ds}"
TRIG="${TRIG:-/init/cluster.trig}"
ASK='query=ASK { GRAPH ?g { ?s ?p ?o } }'

has_data() {
    curl -sf -H "Accept: application/sparql-results+json" --data-urlencode "$ASK" "$FUSEKI/sparql"
}

echo "waiting for the quad store ..."
i=0
until answer=$(has_data); do
    i=$((i + 1))
    if [ "$i" -ge 90 ]; then
        echo "quad store did not answer within 3 minutes" >&2
        exit 1
    fi
    sleep 2
done

if echo "$answer" | grep -q '"boolean" *: *true'; then
    echo "quad store has data -- keeping it (projects survive restarts)"
    exit 0
fi

echo "empty quad store -- loading $TRIG (once)"
# quads (TriG) posted to the dataset: Fuseki adds them graph by graph
curl -sf -X POST -H "Content-Type: application/trig" --data-binary "@$TRIG" "$FUSEKI" \
    || curl -sf -X POST -H "Content-Type: application/trig" --data-binary "@$TRIG" "$FUSEKI/data"

if has_data | grep -q '"boolean" *: *true'; then
    echo "loaded -- now run setup-org once (cd backend && uv run python -m app.sysml setup-org)"
else
    echo "loading $TRIG failed" >&2
    exit 1
fi
