# SysML v2 → CAD: Proof of Concept

*Deutsche Fassung. Englisch: [README.md](README.md).*

Ein durchgehender Faden von einer SysML-v2-Anforderung bis zu einer roten
CI-Pipeline. Bewusst schmal: ein Bauteil, zwei Anforderungen, hartcodiertes Mapping.

**Status:** Stufe A abgeschlossen. Ende-zu-Ende verifiziert.

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
make secret               # erzeugt PLAY_SECRET in docker/.env, siehe unten
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
ID         Attribute        Measured          Limit      Deviation  Status
MaxLength  length                123 mm            120 mm             +3 mm  VIOLATED
MaxMass    mass               0.7753 kg            0.9 kg        -0.1247 kg  OK
1 compliant, 0 within tolerance, 1 violated, 0 not checked

  VIOLATED MaxLength: length = 123 mm <= 120 mm is false (over by 3 mm;
  source 72f3b6a1-..., bbox_size({'axis': 'X'}) on build123d:motor_housing)
Exit: 1
```

Exit 1 → die Pipeline wird rot. Das ist der PoC-Meilenstein.

Ein Urteil ist dreiwertig, kein Boolean. Gibt man dem `MaxLength`-Eintrag im
Mapping ein `tolerance: "5 mm"`, meldet dasselbe 123-mm-Bauteil `TOLERANCE` und
endet mit Exit 0 — im Report weiterhin sichtbar, aber kein Fehlschlag. „Über
dem Grenzwert, aber innerhalb dessen, was vereinbart war" ist der Fall, über
den Ingenieure tatsächlich verhandeln, und ein Boolean kann ihn nicht
ausdrücken.

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
├── jupyter.Dockerfile        conda, SysML-Kernel, Standardbibliothek
└── .env                      PLAY_SECRET (nicht im Git), siehe unten
vendor/                       hni-ase/SysML-v2-API-Services (Klon, nicht im Git)
models/motor_housing.sysml    Systemmodell, textuell
notebooks/                    01_publish_motor_housing.ipynb
cad/motor_housing.py          Bauteil als build123d-Skript
fixtures/requirements.json    Stand-in + Regressionstest
mapping/mapping.yaml          Bauteile ↔ CAD-Objekte, Attribute ↔ Messmethoden
src/sysmlcad/
├── config.py                 SYSML_API_URL aus der Umgebung
├── units.py                  genau eine pint-Registry
├── model.py                  Requirement, Verdict, RunContext, Run
├── sysml_client.py           REST-Client, all_elements() paginiert
├── extract.py                API oder Fixture → Requirements, inkl. satisfy-Links
├── mapping.py                lädt und löst mapping.yaml auf
├── verify.py                 Auswertung, Report, Exit-Code
├── explore.py                Debug-Werkzeug für Payloads
└── adapters/
    ├── __init__.py           CadAdapter-Protokoll -- der CAD-Schnitt
    └── build123d_adapter.py  das Referenz- (und CI-) Backend
tests/                        test_extract.py, test_requirements.py, test_verify.py
.github/workflows/verify.yml  CI, läuft gegen die Fixture
CLAUDE.md                     Projektkontext für Claude Code
```

## docker/.env

Play verweigert im Produktionsmodus den Start ohne ausreichend langen
Secret-Key. Einmalig mit `make secret` erzeugen, oder von Hand:

```bash
echo "PLAY_SECRET=$(head -c 48 /dev/urandom | base64 | tr -d '\n')" > docker/.env
grep -q '^\.env$' .gitignore || echo ".env" >> .gitignore
```

**Der Ort ist entscheidend.** Compose sucht die env-Datei im Verzeichnis der
*ersten* `-f`-Datei, also `docker/` — nicht im Projektwurzelverzeichnis. Das
Makefile könnte das mit `--env-file` umgehen, die VS-Code-Dev-Containers-
Extension aber baut ihr eigenes `docker compose`-Kommando und kann das Flag
nicht mitgeben. Liegt die Datei woanders, scheitert das Öffnen des
Devcontainers bei `docker compose config` mit:

```
required variable PLAY_SECRET is missing a value
```

Und zwar auch dann, wenn der Devcontainer nur `dev` und `postgres` startet:
`compose config` interpoliert die gesamte gemergte Datei, `sysml-api` inklusive.

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

Stufe B: Change-Impact-Analyse — zu einer Änderung auf einer der beiden Seiten
die betroffenen Anforderungen und Verifikationsfälle aus den Modell-Links
ableiten statt sie zu schätzen, und zu jedem Treffer den Pfad ausweisen, der
ihn ergeben hat. Braucht keinen CAD-Schreibzugriff und keine neue
Infrastruktur.

Danach C (Evidenz-Log und Reports), D (MCP-Server), E (Gates und Bestätigung),
F (FreeCAD-Adapter), G (Schreibpfade über Zuständigkeit), H
(KI-Mapping-Vorschläge). Reihenfolge, die nicht gebrochen werden darf: **Gates
vor Schreiben, Gates vor KI, Adapter-Schnitt vor FreeCAD.** Details und
Begründungen in [ROADMAP_de.md](ROADMAP_de.md).
