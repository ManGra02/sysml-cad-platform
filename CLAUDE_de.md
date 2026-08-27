# CLAUDE.md — SysML v2 ↔ CAD Verifikations-PoC

*Deutsche Fassung. Englisch (maßgeblich für Claude Code): [CLAUDE.md](CLAUDE.md).*

## Ziel
Anforderungen aus SysML v2 automatisch gegen CAD-Geometrie prüfen. CI wird rot,
wenn das CAD-Modell eine Systemanforderung verletzt. Später: Mapping-Store,
KI-gestützte Mapping-Vorschläge, bidirektionale Sync, SMT-Verifikation.

**Status: Stufe A abgeschlossen und verifiziert.** Ende-zu-Ende läuft:
SysML-v2-API → Extraktor → CAD-Adapter → Urteil → Exit-Code. Der Serverteil
läuft auf dem Fork `hni-ase/SysML-v2-API-Services`.

Stufe A hat das Mapping auf *Bauteile* umgehängt (aufgelöst über den
`satisfy`-Link des Modells), einen `CadAdapter`-Schnitt unter die CAD-Seite
gelegt, die Urteile dreiwertig gemacht und jeden Lauf dazu gebracht, die
Modellzustände festzuhalten, aus denen er stammt.

## Architektur

4 Container, ein Compose-Projekt (`sysml-cad-poc`), ein Netzwerk:

| Container | Rolle | Port |
|---|---|---|
| `dev` | Devcontainer, Python 3.14, venv unter `/opt/venv` | — |
| `sysml2-postgres` | PostgreSQL 16, DB `sysml2` | 5432 |
| `sysml2-api` | SysML-v2-API-Services (Play/Scala/Hibernate) | 9000 |
| `sysml2-jupyter` | SysML-v2-Kernel, `%publish` ins Repository | 8888 |

Compose-Dateien: `docker/docker-compose.yml` + `.devcontainer/docker-compose.dev.yml`
(Overlay, fügt `dev` hinzu). Beide werden immer zusammen geladen.

**Netzwerkregel:** Zwischen Containern gilt der Servicename (`sysml-api:9000`,
`postgres:5432`). `localhost` nur vom Host. `src/sysmlcad/config.py` liest
`SYSML_API_URL`; das Overlay setzt sie auf `http://sysml-api:9000`.

## Befehle — wo ausführen

**Im Devcontainer:**
```bash
make cad                        # CAD-Skript, schreibt out/motor_housing.step
make verify                     # Verifikation gegen fixtures/requirements.json
python -m sysmlcad.verify api   # Verifikation gegen den echten API-Server
make test                       # pytest, JUnit-XML nach out/
python -m sysmlcad.explore      # Element-Dump nach out/elements.json
python -m sysmlcad.explore MaxLength   # Baum einer Anforderung
```

**Auf dem Host (Docker-Zugriff nötig):**
```bash
make api        # sysml-api bauen/starten
make jupyter    # Jupyter-Container, http://localhost:8888/?token=sysmlcad
make logs
make down
make up         # ACHTUNG: startet ALLES inkl. dev und jupyter -- im
                # Devcontainer-Workflow nicht noetig, `make api` genuegt
```
`make venv` NIE im Devcontainer — venv liegt bereits im Image unter `/opt/venv`.

## Dateibaum

```
.devcontainer/     devcontainer.json, docker-compose.dev.yml, Dockerfile
docker/            docker-compose.yml, jupyter.Dockerfile, .env (gitignored),
                   .env.example
                   (kein eigenes api-services.Dockerfile mehr -- Fork bringt eines mit)
vendor/            hni-ase/SysML-v2-API-Services (git clone, nicht im Repo)
.github/workflows/ verify.yml -- CI laeuft gegen die FIXTURE, nicht gegen die API
                   (bewusst: CI soll ohne laufenden Server gruen werden koennen)
models/            motor_housing.sysml
notebooks/         01_publish_motor_housing.ipynb
cad/               motor_housing.py  (build123d)
fixtures/          requirements.json  (Stand-in + Regressionstest)
mapping/           mapping.yaml       (Schema v2: Bauteile ↔ CAD-Objekte,
                                       Attribute ↔ Messmethoden)
src/sysmlcad/      config, units, model, sysml_client, extract, mapping,
                   verify, explore
src/sysmlcad/adapters/   __init__.py (CadAdapter-Protokoll),
                         build123d_adapter.py
tests/             test_extract.py, test_requirements.py, test_verify.py
pyproject.toml     Paketmetadaten + pytest-Konfiguration (pytest.ini ist weg)
out/               STEP, JUnit-XML, Dumps (gitignored)
```

## Datenfluss

1. `extract.load_with_context("api")` → `SysMLClient.all_elements()`
   (paginiert) → `elements_to_requirements()`, das zuerst `resolve_satisfies()`
   ausführt, um zu erfahren, um welche PartUsage es jeder Anforderung geht →
   `Requirement(id, subject, operator, limit: pint.Quantity)` plus Projekt- und
   Commit-ID
2. `mapping.load_mapping()` → `parts:` (SysML-Bauteil ↔ Adapter + CAD-Objekt)
   und `attributes:` (SysML-Attribut ↔ Messmethode, Einheit, Richtung,
   Toleranz, Status)
3. `verify.AdapterPool` instanziiert den im Bauteil-Eintrag genannten Adapter;
   `adapter.measure(obj, method, args)` liefert eine pint-Größe
4. `Requirement.evaluate()` vergleicht dimensionsgeprüft →
   `(status, deviation)` → `Verdict`
5. `verify.run()` → `Run(context, verdicts, gaps)`; `report()` → Tabelle,
   Exit 0/1

Eine nicht auswertbare Anforderung wird zur **Lücke**, nicht zu einem
Bestanden: kein bestätigtes Mapping, oder ein `Unsupported` vom Adapter. Lücken
werden gemeldet und lassen den Lauf nicht scheitern. FREQ-2: die Lücke melden,
nie einen Wert einsetzen.

## Gelöste Stolpersteine — NICHT rückgängig machen

**SysML-v2-API-Services**
- Kein offizielles Image. Selbst gebaut auf `sbtscala/scala-sbt` mit JDK 11.
- JDBC-URL ist in `conf/META-INF/persistence.xml` **fest verdrahtet** auf
  `localhost:5432`, nicht per System-Property überschreibbar. Dockerfile
  patcht sie per `sed` auf `postgres:5432`.
- `hbm2ddl.auto` per `sed` von `create-drop` auf `update` — sonst wird das
  Schema bei jedem Stop gelöscht.
- `sbt run` (Dev-Modus) stirbt an EOF auf stdin, auch mit `stdin_open`/`tty`.
  Lösung: `sbt stage`, CMD startet `/app/target/universal/stage/bin/sysml-v2-api-services`
  (Glob matcht sonst auch die `.bat`).
- Play `AllowedHostsFilter` blockt `Host: sysml-api:9000` mit 400.
  Flag: `-Dplay.filters.hosts.allowed.0='.'`
- Erster Start dauert Minuten (Schema, ~8200 Tabellen). Bereit, wenn
  `Listening for HTTP` im Log steht und `curl localhost:9000/projects` 200 liefert.

**Devcontainer**
- Basis `mcr.microsoft.com/devcontainers/python:3.14-trixie`.
- OCP linkt hart gegen `libGL.so.1`, `libGLX`, `libX11` — auch headless.
  apt: `libgl1 libx11-6 libxau6 libxdmcp6 libxext6 libxrender1`.
  Kein Mesa nötig (nur Symbolauflösung).
- venv unter `/opt/venv`, außerhalb des Bind-Mounts (cadquery-ocp ist groß).
- `ENV PATH` reicht nicht: VS Code probt per Login-Shell, Default ist **zsh**.
  PATH steht deshalb zusätzlich in `/etc/profile.d/10-venv.sh`, `.bashrc`,
  `.zshrc` und `remoteEnv` der devcontainer.json.
- `forwardPorts` wurde **entfernt** — VS Code belegte sonst Host-Port 9000
  und `sysml2-api` konnte nicht binden.
- Die Compose-env-Datei liegt unter `docker/.env`, **nicht** im Projektwurzel-
  verzeichnis. Compose sucht sie im Verzeichnis der ERSTEN `-f`-Datei, und die
  Dev-Containers-Extension baut ihr eigenes compose-Kommando ohne Moeglichkeit,
  `--env-file` mitzugeben. Liegt sie woanders, stirbt das Oeffnen des
  Devcontainers bei `docker compose config` mit `required variable PLAY_SECRET
  is missing a value` — auch wenn `runServices` nur `dev` + `postgres` enthaelt,
  denn `config` interpoliert die gesamte gemergte Datei inklusive `sysml-api`.
- Python 3.14: `ezdxf` hat keine cp314-Wheels, läuft pure-python. Betrifft nur
  DXF, nicht STEP. `lib3mf`-DeprecationWarnings sind erwartet und harmlos.
- **build123d 0.11:** `export_step(part, pfad)` ist eine MODULFUNKTION, keine
  Methode am Part. Ältere Beispiele im Netz zeigen `part.export_step(...)`.
- Messungen: `part.volume` (mm³), `part.bounding_box().size.X`,
  `part.center(CenterOf.MASS)`, `len(part.faces())`. Die liegen jetzt in
  `adapters/build123d_adapter.py`; `measure.py` gibt es nicht mehr.
- Der Adapter liest `MATERIAL` und `DENSITY_G_PER_CM3` aus dem CAD-Modul, die
  Dichte ist damit nicht mehr in `mapping.yaml` dupliziert. Ein `args`-Override
  bleibt, für Ersatzteil-Studien („was, wenn das Kunststoff wäre?").
- `Build123dAdapter.state_id()` hasht den Quelltext der geladenen CAD-Module.
  Bei Code-CAD *ist* das Skript der Entwurfszustand, der Digest ist also exakt
  und keine Näherung.

**Jupyter / SysML-Kernel**
- conda-forge `jupyter-sysml-kernel=0.60.1`, `openjdk>=21`.
- JupyterLab-Extension bewusst NICHT installiert (alter `labextension install`-Pfad,
  scheitert unter Lab 4; liefert nur Syntax-Highlighting).
- Standardbibliothek aus `SysML-v2-Release` geklont nach `/opt/sysml.library`,
  `ISYSML_LIBRARY_PATH` gesetzt. Ohne sie scheitert jedes `import ISQ::*`.
- **Kritisch:** Der Kernel liest `ISYSML_API_BASE_PATH` NICHT aus der Prozess-
  umgebung, sondern aus dem `env`-Block seiner `kernel.json`
  (`/opt/conda/share/jupyter/kernels/sysml/kernel.json`). Ohne Patch publiziert
  `%publish` auf den öffentlichen Server `sysml2.intercax.com`. Dockerfile
  patcht die kernel.json.

**SysML-v2-Syntax (Release 0.60.1)**
- Sichtbarkeit bei Imports ist Pflicht: `private import ISQ::*;`, nicht `import`.
- `satisfy` braucht eine Requirement-**Usage**, keine Definition:
  ```
  requirement maxLengthCheck : MaxLength;
  satisfy maxLengthCheck by motorHousing;
  ```
- Einheiten sind keine Felder: `120 [mm]` wird zu einer `OperatorExpression`
  mit `operator: "["`, Operand 0 = `LiteralInteger`, Operand 1 → Bibliotheks-
  `AttributeUsage` mit `declaredShortName: "mm"`.

**API-Details**
- `/projects/{id}/commits/{cid}/elements` paginiert bei 100. Nächste Seite im
  Link-Header. `SysMLClient.all_elements()` blättert; `elements()` nicht.
- `explore.py` hat ein `depth > 8`-Limit im `walk()` — schneidet den Pfad zur
  Einheit ab. Beim Debuggen ggf. erhöhen.

**Testdesign**
- `tests/test_verify.py` fixiert die Auswertungssemantik (drei Urteile,
  Toleranz, Einheitenumrechnung, Dimensionsfehler) ohne Geometrie und ohne
  Server. Ein falsches Urteil ist der eine Fehler, den dieses System nicht
  verkraftet.
- `tests/test_requirements.py` ruft `run()` auf MODULEBENE (`RESULT = run()`),
  also schon beim Einsammeln der Tests. Bewusst gegen die Fixture — würde man
  hier auf `"api"` umstellen, bräuchte jeder pytest-Lauf einen laufenden Server.
- `tests/test_extract.py` baut den Elementgraphen synthetisch nach, aus einem
  echten `%publish`-Dump. Läuft ohne Netz.
- `make clean` nutzt `**/__pycache__`; unter `sh` expandiert das nicht.
  Zum Aufräumen stattdessen:
  `find . -name __pycache__ -type d -exec rm -rf {} +`

## Bewusste Vereinfachungen (dokumentiert im Kopf von extract.py)

1. **Die gemessene Größe kommt aus `mapping.yaml`, nicht aus dem Constraint-
   Ausdruck.** `housing.length <= maxLength` wird nicht geparst; die Schlüssel
   `attribute:` und `requirement:` im Mapping tragen diese Verknüpfung.
   Kosten: Ändert jemand die Constraint auf ein anderes Attribut, bleibt es
   unbemerkt. Das zu schließen heißt, die `FeatureChainExpression` aufzulösen —
   der nächste Schritt im Extraktor.
2. Nur ein Vergleich pro Anforderung; zusammengesetzte Constraints werden auf
   den ersten reduziert (mit Warnung).
3. Ausdrücke werden nicht ausgewertet, nur Bestandteile gelesen
   (`länge + breite <= 200` wäre falsch). → Phase 6 (SMT).
4. Extraktion sucht in der von der `RequirementDefinition` erreichbaren Teilmenge
   nach: erstem Vergleichsoperator, erstem Literal, erstem Bibliothekselement mit
   `declaredShortName`. `_UPWARD_FIELDS` verhindert das Abdriften in Nachbar-
   anforderungen — abgesichert durch `test_requirements_stay_separate`.
5. `requirement_id` = `declaredShortName` oder `declaredName` der Definition.
   `mapping.yaml` und Fixture nutzen dieselben Schlüssel (`MaxLength`, `MaxMass`).
   `models/motor_housing.sysml` trägt bewusst **keine** Kurznamen: `<'REQ001'>`
   würde die ID zu `REQ001` machen und im Mapping auf nichts passen.

**Keine Vereinfachung mehr:** Das *Subjekt* einer Anforderung wird jetzt über
den `satisfy`-Link des Modells aufgelöst statt aus der ersten `ReferenceUsage`
im Teilbaum geraten. Siehe `extract.resolve_satisfies`.

## Konventionen

- **Stabile Identität:** CAD-Mappings zeigen auf benannte Modulparameter
  (`LENGTH_MM`) oder benannte Messmethoden, NIE auf Flächen-/Kantenindizes
  (topologisches Namensproblem).
- **Einheiten:** genau eine `pint`-Registry in `units.py`. Zwei Registries
  erzeugen unvergleichbare Quantities.
- **Messsemantik explizit:** `bbox_size(axis="X")` ist etwas anderes als ein
  benanntes Feature-Maß. Steht in `mapping.yaml` unter `note`.
- `Requirement` ist frozen; Ergänzungen via `dataclasses.replace`.
- **Ein CAD-Schnitt:** Nichts außerhalb von `src/sysmlcad/adapters/` darf
  build123d, FreeCAD oder einen anderen Geometriekern importieren. Alles
  oberhalb spricht `CadAdapter` und pint-Größen.
- **Adapter melden Lücken, sie setzen nie Werte ein.** `Unsupported` ist die
  Antwort auf „dieses Backend kann das nicht messen", und der Lauf hält das als
  Lücke fest (SRS FREQ-2).
- **Zuständigkeit statt Merge:** Das `direction`-Feld des Mappings
  (`sysml_owns` / `cad_owns` / `both`) entscheidet, wer einen Wert schreiben
  darf. SysML besitzt Grenzwerte, CAD besitzt Ist-Werte. Es schreibt noch
  nichts; das Feld existiert, damit das Freischalten eine Verhaltensänderung
  ist und keine Schemamigration.
- **KI schlägt vor, sie bewertet nie.** Eine KI-Komponente darf Mappings
  vorschlagen und natürliche Sprache sprechen. Sobald ein Mapping bestätigt
  ist, ist es eine gewöhnliche deterministische Regel und ihre Herkunft
  beeinflusst kein Ergebnis mehr (SRS FREQ-5, NFREQ-1). Die Folien lesen sich
  so, als führe die KI die Verifikation durch — das darf sie nicht.
- **Das Mapping ist YAML und liegt in git; das Evidenz-Log wird SQLite.** Das
  Mapping ist Entwurfsabsicht und gehört ins Review (FREQ-3 verlangt
  menschenlesbar und versionierbar). Das append-only-Lauf-Log ist das, was eine
  Datenbank braucht. Zwei Speicher, zwei Aufgaben.

## Verifizierter Referenzlauf

```
$ python -m sysmlcad.verify                # LENGTH_MM = 118.0
source       : fixture
cad state    : build123d:bdaee4cff5d3ddfa
mapping      : a4b11cc20a9634e8

ID         Attribute        Measured          Limit      Deviation  Status
MaxLength  length                118 mm            120 mm             -2 mm  OK
MaxMass    mass               0.7429 kg            0.9 kg        -0.1571 kg  OK
2 compliant, 0 within tolerance, 0 violated, 0 not checked   → Exit 0

$ sed -i 's/LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
$ python -m sysmlcad.verify
MaxLength  length                123 mm            120 mm             +3 mm  VIOLATED
  VIOLATED MaxLength: length = 123 mm <= 120 mm is false (over by 3 mm; ...)
                                                             → Exit 1

# dasselbe 123-mm-Bauteil, mit `tolerance: "5 mm"` am MaxLength-Eintrag
MaxLength  length                123 mm            120 mm             +3 mm  TOLERANCE
  TOLERANCE MaxLength: ... inside the agreed tolerance of 5 mm   → Exit 0
```

Die Digests `cad state` und `mapping` ändern sich, wenn sich Geometrie oder
Mapping ändern. Genau das macht ein Urteil zitierfähig statt nur ausgedruckt.

## Roadmap

Stufen, Begründungen und offene Architekturfragen stehen in
**[ROADMAP_de.md](ROADMAP_de.md)**. Kurz: Phasen 0–3 und Stufe A sind fertig;
Stufe B (Change-Impact-Analyse) ist der nächste Schritt, danach C (Evidenz-Log
und Reports), D (MCP-Server), E (Gates und Bestätigung), F (FreeCAD-Adapter),
G (Schreibpfade über Zuständigkeit), H (KI-Mapping-Vorschläge).

Reihenfolge, die nicht gebrochen werden darf: **Gates vor Schreiben, Gates vor
KI, Adapter-Schnitt vor FreeCAD.**

**Der wichtigste Punkt daraus, weil er leicht falsch gemacht wird:**
Mapping-Gültigkeit und Anforderungserfüllung sind zwei getrennte Fragen. Gates
prüfen die Zuordnung (Dimension, Existenz, Eindeutigkeit, Plausibilität), die
Verifikations-Engine prüft die Erfüllung. Ein korrekt gemapptes, aber zu langes
Bauteil ist ein Verstoß, kein Fehlmapping.

Das Zielsystem beschreiben `goal_spec.txt` (SRS v0.1) und die
HNI/IEM-Use-Case-Folien; ROADMAP_de.md hält fest, wo dieses Projekt bewusst
davon abweicht und warum.
