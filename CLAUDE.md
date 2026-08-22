# CLAUDE.md — SysML v2 ↔ CAD Verifikations-PoC

## Ziel
Anforderungen aus SysML v2 automatisch gegen CAD-Geometrie prüfen. CI wird rot,
wenn das CAD-Modell eine Systemanforderung verletzt. Später: Mapping-Store,
KI-gestützte Mapping-Vorschläge, bidirektionale Sync, SMT-Verifikation.

**Status: Phase 1 abgeschlossen und verifiziert.** Ende-zu-Ende läuft:
SysML-v2-API → Extraktor → build123d-Messung → Urteil → Exit-Code.

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
```
`make venv` NIE im Devcontainer — venv liegt bereits im Image unter `/opt/venv`.

## Dateibaum

```
.devcontainer/     devcontainer.json, docker-compose.dev.yml, Dockerfile
docker/            docker-compose.yml, api-services.Dockerfile, jupyter.Dockerfile
vendor/            SysML-v2-API-Services (git clone, nicht im Repo)
models/            motor_housing.sysml
notebooks/         01_publish_motor_housing.ipynb
cad/               motor_housing.py  (build123d)
fixtures/          requirements.json  (Stand-in + Regressionstest)
mapping/           mapping.yaml       (Anforderung ↔ Messmethode)
src/sysmlcad/      config, units, model, sysml_client, extract, measure, verify, explore
tests/             test_extract.py, test_requirements.py
out/               STEP, JUnit-XML, Dumps (gitignored)
```

## Datenfluss

1. `extract.load("api")` → `SysMLClient.all_elements()` (paginiert) →
   `elements_to_requirements()` → `Requirement(id, operator, limit: pint.Quantity)`
2. `mapping.yaml` liefert pro `requirement_id`: `cad_module`, `method`, `args`, `property`
3. `measure.load_part()` importiert das CAD-Modul, ruft `build()`, misst
4. `Requirement.check()` vergleicht dimensionsgeprüft → `Verdict`
5. `verify.report()` → Tabelle, Exit 0/1

## Gelöste Stolpersteine — NICHT rückgängig machen

**SysML-v2-API-Services**
- Fork `hni-ase/SysML-v2-API-Services` (HNI Paderborn) statt Upstream.
  Bringt eigenes Dockerfile (sbt stage, .bat-sicherer Symlink, Layer-Caching)
  und JDBC-Konfiguration per SYSML_JDBC_URL/_USER/_PASSWORD mit.
- `hbm2ddl.auto` ist dort NICHT per Env setzbar und steht auf create-drop.
  Das Makefile-Ziel `vendor` patcht es nach dem Klonen auf `update`.
- Der AllowedHostsFilter fehlt im CMD des Forks; Compose überschreibt das
  CMD und ergänzt `-Dplay.filters.hosts.allowed.0=.`

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
- Python 3.14: `ezdxf` hat keine cp314-Wheels, läuft pure-python. Betrifft nur
  DXF, nicht STEP. `lib3mf`-DeprecationWarnings sind erwartet und harmlos.

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

## Bewusste Vereinfachungen (dokumentiert im Kopf von extract.py)

1. **Die gemessene Größe kommt aus `mapping.yaml`, nicht aus dem Constraint-
   Ausdruck.** `housing.length <= maxLength` wird nicht geparst.
   Kosten: Ändert jemand die Constraint auf ein anderes Attribut, bleibt es
   unbemerkt. → Phase 4.
2. Nur ein Vergleich pro Anforderung; zusammengesetzte Constraints werden auf
   den ersten reduziert (mit Warnung).
3. Ausdrücke werden nicht ausgewertet, nur Bestandteile gelesen
   (`länge + breite <= 200` wäre falsch). → Phase 6 (SMT).
4. Extraktion sucht in der von der `RequirementDefinition` erreichbaren Teilmenge
   nach: erstem Vergleichsoperator, erstem Literal, erstem Bibliothekselement mit
   `declaredShortName`. `_UPWARD_FIELDS` verhindert das Abdriften in Nachbar-
   anforderungen — abgesichert durch `test_mehrere_anforderungen_bleiben_getrennt`.
5. `requirement_id` = `declaredShortName` oder `declaredName` der Definition.
   `mapping.yaml` und Fixture nutzen dieselben Schlüssel (`MaxLength`, `MaxMass`).

## Konventionen

- **Stabile Identität:** CAD-Mappings zeigen auf benannte Modulparameter
  (`LENGTH_MM`) oder benannte Messmethoden, NIE auf Flächen-/Kantenindizes
  (topologisches Namensproblem).
- **Einheiten:** genau eine `pint`-Registry in `units.py`. Zwei Registries
  erzeugen unvergleichbare Quantities.
- **Messsemantik explizit:** `bbox_size(axis="X")` ist etwas anderes als ein
  benanntes Feature-Maß. Steht in `mapping.yaml` unter `note`.
- `Requirement` ist frozen; Ergänzungen via `dataclasses.replace`.

## Verifizierter Referenzlauf

```
$ python -m sysmlcad.verify api            # LENGTH_MM = 118.0
MaxLength length  118 mm  <= 120 mm  OK
MaxMass   mass   0.7429 kg <= 0.9 kg  OK    → Exit 0

$ sed -i 's/LENGTH_MM = 118.0/LENGTH_MM = 123.0/' cad/motor_housing.py
$ python -m sysmlcad.verify api
MaxLength verletzt: length = 123 mm <= 120 mm ist falsch  → Exit 1
```

## Nächste Schritte (Roadmap-Phase 4)

Reihenfolge ist wichtig: Gates vor KI, sonst fehlt der Maßstab.

1. **Mapping-Store**: SQLite statt YAML, append-only Audit-Tabelle,
   Status `proposed | confirmed | rejected` mit Zeitstempel und Urheber.
2. **Deterministische Gates** (getrennt von der Anforderungsprüfung!):
   - Dimensionskompatibilität (Länge↔Länge via pint)
   - Existenz einer messbaren Größe am CAD-Objekt
   - Eindeutigkeit (keine 1:n-Kollisionen)
   - Plausibilität (Größenordnung, z.B. Faktor 0.1–10 zur Anforderung)
   **Wichtig:** Mapping-Gültigkeit ≠ Anforderungserfüllung. Ein korrekt
   gemapptes, aber zu langes Bauteil ist ein *Verstoß*, kein Fehlmapping.
3. **KI-Hypothesen**: `rapidfuzz` + `sentence-transformers` über Namen/Metadaten.
   Trefferquote gegen ein handgemapptes Gold-Set messen.

Später: Phase 5 (Rückschreiben als Metadaten, Merge-Assistent),
Phase 6 (z3 auf dem Constraint-Netz, nicht auf der Geometrie).
