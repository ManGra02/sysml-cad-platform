# SysML v2 → CAD: Proof of Concept

Ein durchgehender, dünner Faden von einer SysML-v2-Anforderung bis zu einer
roten CI-Pipeline. Bewusst schmal gehalten: eine Baugruppe, zwei Anforderungen,
hartcodiertes Mapping.

## Setup

```bash
make cad           # CAD-Skript ausführen, STEP schreiben
make verify        # Verifikation gegen die Fixture-Anforderungen
make test          # dasselbe über pytest, mit JUnit-XML in out/
```

Diese vier Befehle laufen **ohne Docker und ohne SysML-Server**. Das ist Absicht:
Schritt 2 und 3 aus der Roadmap sind damit an Tag 1 fertig, während der
Java-Stack noch kompiliert.

Für Schritt 1:

```bash
make vendor        # SysML-v2-API-Services klonen
make up            # Postgres + API-Server bauen und starten (erster Build: 10-20 min)
make logs
make api-docs      # http://localhost:9000/docs/ aufrufen -- initialisiert das DB-Schema
```

## Entwicklung im Devcontainer

`.devcontainer/devcontainer.json` referenziert **beide** Compose-Dateien. Compose
merged sie zu einem Projekt, dadurch hängen `dev`, `postgres` und `sysml-api` im
selben Netzwerk.

```bash
code .        # dann "Reopen in Container"
```

Der Devcontainer startet nur `dev` und `postgres` — der sbt-Build des API-Servers
dauert 10-20 Minuten und soll dich nicht beim ersten Öffnen blockieren. Wenn du
ihn brauchst:

```bash
make api      # baut und startet sysml-api nach, im selben Netzwerk
```

**Die eine Regel, die man vergisst:** Zwischen Containern gilt der *Servicename*,
nicht `localhost`. Aus dem Devcontainer heraus erreichst du die API unter
`http://sysml-api:9000` und die Datenbank unter `postgres:5432`. `localhost` zeigt
im Container auf den Container selbst. Deshalb liest `src/sysmlcad/config.py` die
Variable `SYSML_API_URL`; das Overlay setzt sie passend, auf dem Host bleibt der
Default `http://localhost:9000`. Die `ports:`-Einträge sind ausschließlich für
deinen Browser da, für die Kommunikation zwischen Containern spielen sie keine Rolle.

Zwei Details im Dockerfile, die keine Kosmetik sind: Die apt-Pakete `libgl1`
und die X11-Bibliotheken sind Pflicht, weil OCP hart gegen `libGL.so.1` linkt
— auch headless. Und das venv liegt unter `/opt/venv`, also
außerhalb des Bind-Mounts: `cadquery-ocp` bringt ~400 MB mit, die im gemounteten
Workspace bei jedem Rebuild neu installiert würden.

## Ordnerstruktur

```
sysml-cad-poc/
├── .devcontainer/
│   ├── devcontainer.json         referenziert beide Compose-Dateien
│   ├── docker-compose.dev.yml    Overlay: fügt den dev-Service hinzu
│   └── Dockerfile                Python 3.14 (trixie) + OpenGL/X11-Libs für OCP
├── docker/                       Postgres + SysML-v2-API-Services
│   ├── docker-compose.yml
│   └── api-services.Dockerfile   selbstgebaut, es gibt kein offizielles Image
├── vendor/                       geklonte Fremd-Repos (nicht im Git)
├── models/motor_housing.sysml    Systemmodell, textuell, versionierbar
├── cad/motor_housing.py          Bauteil als build123d-Skript
├── fixtures/requirements.json    Stand-in für die API-Antwort aus Phase 1
├── mapping/mapping.yaml          Anforderung ↔ Messmethode, Phase 3 hartcodiert
├── src/sysmlcad/
│   ├── config.py                 SYSML_API_URL aus der Umgebung
│   ├── units.py                  genau eine pint-Registry für alles
│   ├── model.py                  Zwischenformat: Requirement, Verdict
│   ├── sysml_client.py           REST-Client auf Port 9000
│   ├── extract.py                API oder Fixture -> Requirement-Liste
│   ├── measure.py                CAD-Property -> einheitenbehaftete Größe
│   └── verify.py                 Auswertung, Report, Exit-Code
├── tests/test_requirements.py    pytest als Regel-Runner
└── out/                          STEP-Dateien, JUnit-XML
```

## Der Fehlerfall

Setze `LENGTH_MM = 123.0` in `cad/motor_housing.py` und führe `make verify` aus:

```
REQ001 verletzt: length = 123 mm <= 120 mm ist falsch
(Quelle: fixture-req-001, Methode: bbox_size({'axis': 'X'}))
```

Exit-Code 1 → die Pipeline wird rot. Das ist der PoC-Meilenstein aus Phase 3.

## Bekannte Stolpersteine

**Kein offizielles Docker-Image für die API-Services.** Das Pilot-Repo dokumentiert
nur `sbt run` auf JDK 11. Der Dockerfile hier baut das selbst. Der erste Build
dauert lange; die Volumes für `.ivy2`, `.sbt` und den Coursier-Cache sorgen dafür,
dass es nur einmal passiert.

**Die DB-Konfiguration ist die wackligste Stelle.** Die System-Properties
`db.default.url` / `.username` / `.password` im Dockerfile müssen gegen
`conf/application.conf` des geklonten Repos geprüft werden. Wenn der Container
mit einer Connection-Exception stirbt, liegt es fast immer hier.

**Das Schema wird lazy angelegt.** Der erste Aufruf von `/docs/` initialisiert die
Datenbank. Vorher liefern die Endpunkte Fehler — das ist kein Defekt.

**Python-Version.** Der Devcontainer nutzt 3.14 auf trixie. Einzige Einschränkung:
`ezdxf` hat (Stand 08/2026) keine cp314-Wheels und fällt auf die Pure-Python-Variante
zurück. Das betrifft nur DXF-Import/Export, nicht den STEP-Pfad dieses PoC. Wer 2D-
Ableitungen braucht, geht auf `3.13-trixie` zurück.

**`export_step` ist eine Modulfunktion, keine Methode.** In build123d 0.11 gilt
`export_step(part, pfad)`, nicht `part.export_step(pfad)`. Ältere Beispiele im Netz
zeigen die alte Form.

**`extract._to_requirement` ist bewusst `NotImplementedError`.** Die Payload-Struktur
der RequirementDefinition-Elemente wird gegen die laufende API implementiert, nicht
gegen eine Vermutung. Bis dahin trägt die Fixture.

## Nächste Schritte

1. Phase 1 abschließen: `_to_requirement` gegen echte API-Antworten schreiben,
   Fixture zum Regressionstest degradieren.
2. Mapping-Store (SQLite mit Audit-Tabelle) statt YAML.
3. Mapping-Gates: Dimension, Eindeutigkeit, Plausibilität — getrennt von der
   Anforderungsprüfung.
