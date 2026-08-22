# SysML v2 → CAD: Proof of Concept

Ein durchgehender Faden von einer SysML-v2-Anforderung bis zu einer roten
CI-Pipeline. Bewusst schmal: ein Bauteil, zwei Anforderungen, hartcodiertes Mapping.

**Status:** Phase 1 abgeschlossen. Ende-zu-Ende verifiziert.

## Schnellstart

Alles läuft in Containern. Erst den Devcontainer öffnen:

```bash
code .        # dann "Reopen in Container"
```

Dann **im Devcontainer**:

```bash
make cad      # CAD-Skript ausführen, STEP nach out/
make verify   # Verifikation gegen fixtures/requirements.json
make test     # pytest, JUnit-XML nach out/
```

Diese drei brauchen weder den SysML-Server noch Jupyter. `make venv` wird im
Devcontainer **nicht** aufgerufen — das venv liegt bereits im Image unter
`/opt/venv`.

Für den vollen Stack **auf dem Host** (der Devcontainer hat keinen Docker-Zugriff):

```bash
cp .env.example .env      # PLAY_SECRET erzeugen, siehe unten
make api                  # SysML-v2-API-Server, erster Build ~6 min
make jupyter              # JupyterLab auf http://localhost:8888/?token=sysmlcad
```

Bereit ist der Server, wenn im Log `Listening for HTTP` steht:

```bash
docker logs -f sysml2-api
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9000/projects   # 200
```

## Modell veröffentlichen

Im JupyterLab `notebooks/01_publish_motor_housing.ipynb` öffnen, Kernel **SysML**
(nicht Python). Modellzelle ausführen, dann `%publish MotorHousing`. Die erste
Ausgabezeile muss `http://sysml-api:9000` zeigen — steht dort
`sysml2.intercax.com`, ginge das Modell an den öffentlichen Community-Server.

Danach im Devcontainer gegen den echten Server verifizieren:

```bash
python -m sysmlcad.verify api
python -m sysmlcad.explore              # Element-Dump nach out/elements.json
python -m sysmlcad.explore MaxLength    # Baum einer Anforderung
```

## Der Fehlerfall

```bash
sed -i 's/^LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
python -m sysmlcad.verify api ; echo "Exit: $?"
```

```
MaxLength verletzt: length = 123 mm <= 120 mm ist falsch
(Quelle: 72f3b6a1-..., Methode: bbox_size({'axis': 'X'}))
Exit: 1
```

Exit 1 → die Pipeline wird rot. Das ist der PoC-Meilenstein.

## Architektur

Vier Container, ein Compose-Projekt, ein Netzwerk:

| Container | Rolle | Port |
|---|---|---|
| `dev` | Devcontainer, Python 3.14, venv unter `/opt/venv` | — |
| `sysml2-postgres` | PostgreSQL 16, DB `sysml2` | 5432 |
| `sysml2-api` | SysML-v2-API-Services (Fork hni-ase), Play/Hibernate | 9000 |
| `sysml2-jupyter` | SysML-v2-Kernel, `%publish` | 8888 |

**Die Regel, die man vergisst:** Zwischen Containern gilt der *Servicename*
(`sysml-api:9000`, `postgres:5432`), nicht `localhost`. `src/sysmlcad/config.py`
liest `SYSML_API_URL`; das Compose-Overlay setzt sie passend. Die `ports:`-Einträge
sind nur für deinen Browser vom Host aus.

## Ordnerstruktur

```
.devcontainer/
├── devcontainer.json         referenziert beide Compose-Dateien
├── docker-compose.dev.yml    Overlay: fügt den dev-Service hinzu
└── Dockerfile                Python 3.14 (trixie) + OpenGL/X11 für OCP
docker/
├── docker-compose.yml        postgres, sysml-api, jupyter
└── jupyter.Dockerfile        conda, SysML-Kernel, Standardbibliothek
vendor/                       hni-ase/SysML-v2-API-Services (Klon, nicht im Git)
models/motor_housing.sysml    Systemmodell, textuell
notebooks/                    01_publish_motor_housing.ipynb
cad/motor_housing.py          Bauteil als build123d-Skript
fixtures/requirements.json    Stand-in + Regressionstest
mapping/mapping.yaml          Anforderung ↔ Messmethode
src/sysmlcad/
├── config.py                 SYSML_API_URL aus der Umgebung
├── units.py                  genau eine pint-Registry
├── model.py                  Requirement, Verdict
├── sysml_client.py           REST-Client, all_elements() paginiert
├── extract.py                API oder Fixture → Requirement-Liste
├── measure.py                CAD-Property → einheitenbehaftete Größe
├── verify.py                 Auswertung, Report, Exit-Code
└── explore.py                Debug-Werkzeug für Payloads
tests/                        test_extract.py, test_requirements.py
.github/workflows/verify.yml  CI, läuft gegen die Fixture
.env                          PLAY_SECRET (nicht im Git)
CLAUDE.md                     Projektkontext für Claude Code
```

## .env

Play verweigert im Produktionsmodus den Start ohne ausreichend langen
Secret-Key. Einmalig erzeugen:

```bash
echo "PLAY_SECRET=$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > .env
grep -q '^\.env$' .gitignore || echo ".env" >> .gitignore
```

Wichtig: Compose sucht die `.env` im Verzeichnis der ersten `-f`-Datei, also
`docker/`. Deshalb übergibt das Makefile `--env-file .env` explizit.

## Bekannte Stolpersteine

Die vollständige Liste mit Begründungen steht in **CLAUDE.md**, Abschnitt
„Gelöste Stolpersteine". Die drei häufigsten:

**`localhost` vs. Servicename.** Der mit Abstand häufigste Fehler. Im
Devcontainer `sysml-api:9000`, auf dem Host `localhost:9000`.

**SysML-v2-Syntax (Release 0.60.1).** Imports brauchen Sichtbarkeit
(`private import ISQ::*;`), und `satisfy` verlangt eine Requirement-*Usage*,
keine Definition.

**`export_step` ist eine Modulfunktion.** In build123d 0.11 gilt
`export_step(part, pfad)`, nicht `part.export_step(pfad)`. Ältere Beispiele im
Netz zeigen die alte Form.

## Nächste Schritte

Phase 4, in dieser Reihenfolge: Mapping-Store (SQLite mit Audit-Log) →
deterministische Gates → erst dann KI-Hypothesen. Details in CLAUDE.md.
