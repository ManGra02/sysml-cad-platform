# Roadmap

Leitprinzip: erst der dünne, durchgehende Faden, dann Breite. Jede Phase baut
auf einer verifizierten Vorgängerphase auf.

| Phase | Inhalt | Status |
|---|---|---|
| 0 | Infrastruktur, Referenzbeispiel, Namenskonventionen | **fertig** |
| 1 | Requirement-Extraktion über die API | **fertig** |
| 2 | Messkern auf dem B-Rep | **fertig** |
| 3 | Verifikations-Engine, Report, CI | **fertig** |
| 4 | Mapping-Store, deterministische Gates, KI-Hypothesen | offen |
| 5 | Rückschreiben, Merge-Assistent | offen |
| 6 | SMT auf dem Constraint-Netz | offen |

---

## Phase 4 — Mapping (nächster Schritt)

**Die Reihenfolge ist nicht verhandelbar: Gates vor KI.** Ohne Gates gibt es
keinen Maßstab, an dem sich Vorschläge messen lassen.

### 4.1 Mapping-Store

SQLite statt `mapping/mapping.yaml`. Schema mindestens:

- `mapping`: `requirement_id`, `cad_module`, `method`, `args`, `property`,
  `status`, `author`, `created_at`
- `audit`: append-only, jede Statusänderung mit Zeitstempel, Urheber und Grund

`status ∈ {proposed, confirmed, rejected}`. Nichts wird überschrieben oder
gelöscht — die Historie ist Teil der Nachvollziehbarkeit.

### 4.2 Deterministische Gates

**Der zentrale konzeptionelle Punkt:** Mapping-Gültigkeit und
Anforderungserfüllung sind zwei verschiedene Fragen. Der ursprüngliche
Projektplan hat sie vermischt und wollte ein Mapping nur dann persistieren,
wenn die Anforderung erfüllt ist. Das ist falsch:

- Ein korrekt gemapptes, aber zu langes Bauteil ist ein **Verstoß**, kein
  Fehlmapping — und genau der Fall, den das System melden soll.
- Ein falsches Mapping, das die Regel zufällig erfüllt, würde persistiert.

Gates prüfen deshalb ausschließlich die *Zuordnung*:

1. **Dimensionskompatibilität** — Länge↔Länge, Masse↔Masse (via pint)
2. **Existenz** — ist die Größe am CAD-Objekt überhaupt messbar?
3. **Eindeutigkeit** — keine 1:n-Kollisionen
4. **Plausibilität** — Größenordnung, z.B. Faktor 0,1–10 zur Anforderung
5. **Bestätigung** — beim ersten Mal durch einen Menschen

Ergebnis: *Mapping gültig / ungültig*. Davon getrennt liefert die bestehende
Verifikations-Engine *pass / fail*.

### 4.3 KI-Hypothesen

`rapidfuzz` (String-Distanz) plus `sentence-transformers` (Embeddings) über
Namen und Metadaten von SysML-Elementen und CAD-Modulen. Optional ein LLM mit
strukturiertem JSON-Output.

**Messbar machen:** Trefferquote gegen ein handgemapptes Gold-Set. Ohne diese
Zahl ist unbekannt, ob der KI-Teil überhaupt Zeit spart.

### 4.4 Vorher: Extraktor unter Last

Bevor Phase 4 beginnt, das Apollo-11-Modell von Airbus
(`airbus/apollo-11-sysml-v2`) publizieren und `explore.py` darüber laufen
lassen. Es ist ein bewusst nicht-triviales SysML-v2-Modell nach dem
CoSMA-Rahmen. Erwartung: Die Annahme „ein Vergleich pro Anforderung" fällt als
Erste. Billige, harte Evidenz dafür, welche der Vereinfachungen aus
`extract.py` zuerst nachzuziehen sind.

---

## Phase 5 — Rückrichtung und Konflikte

### 5.1 Schreiben, aber nur Metadaten

Geänderte Grenzwerte aus SysML landen als Attribut oder Kommentar im
CAD-Skript. **Keine automatische Geometrieänderung.** Das schafft
Rückverfolgbarkeit und signalisiert Änderungsbedarf, ohne dass ein Algorithmus
still ein Bauteil umbaut.

### 5.2 Authority-Regel statt Merge-Algorithmus

Der ursprüngliche Projektplan schlug Operational Transformation (OT) vor. Das
ist Over-Engineering: OT löst zeichenweise Nebenläufigkeit in
Echtzeit-Editoren; Modellsynchronisation ist zustandsbasiertes 3-Wege-Diff bei
niedriger Frequenz.

Was 90 % der Konflikte strukturell verhindert, ist eine **explizite
Zuständigkeit pro Parameter**: SysML besitzt Grenzwerte (`maxLength`), CAD
besitzt Ist-Werte (`actualLength`). Dann kollidieren beide Seiten nicht mehr —
es gibt nur noch Verletzungen.

### 5.3 Merge-Assistent

CLI-Diff über den Mapping-Store, drei Optionen pro Konflikt (SysML übernehmen /
CAD übernehmen / manuell). Mensch entscheidet, System protokolliert.

**Vor dem Entwurf lesen:** `Open-MBEE/sysmlv2_dls`, Paket `geometry_api`. Dort
existiert eine CAD-agnostische Baugruppen-Repräsentation mit Translation,
Rotation und Ownership plus ein Onshape-Connector, der aus SysML heraus
schreibt. Entgegengesetzte Designentscheidung zu unserer (dort trägt SysML die
Geometriestruktur), aber die fertige Antwort auf die Transformationsmathematik,
falls wir von Einzelteilen auf Baugruppen gehen.

---

## Phase 6 — Formale Verifikation

**Abgrenzung, die im ursprünglichen Projektplan fehlte:** Z3 kann über
B-Rep-Geometrie nichts beweisen. SMT gehört auf das *Constraint-Netz*, nicht auf
das CAD-Modell.

Sinnvolle Ziele:

- Widerspruchsfreiheit des Anforderungssatzes
- Massen- und Kostenbudgets über Baugruppenhierarchien
- Gegenbeispiele im Parameterraum

Werkzeug: `z3-solver`. Gefundene Gegenbeispiele werden automatisch zu neuen
Testfällen in der Verifikations-Engine aus Phase 3.

---

## Offene Architekturfragen

**Welches CAD-System produktiv?** Wenn CATIA oder Creo gesetzt sind, wird der
Messkern eine Adapter-Schicht über deren API statt über OCC. Die Architektur
bleibt identisch, aber der PoC sollte dann früh gegen einen Ausschnitt echter
Modelldaten laufen — dort sitzen die eigentlichen Reibungspunkte.

**Baugruppen statt Einzelteile.** Der Messkern kennt bisher ein Bauteil pro
Modul. Baugruppen brauchen Aggregation (Summe der Massen) und
Positionierung — siehe 5.3.

**Model-Management.** Falls Versionierung, Branching und Zugriffsrechte über
den PoC hinaus gebraucht werden, ist Open-MBEE (MMS) der etablierte Kandidat.
Für den aktuellen Stand bringt es gegenüber der Pilot-Implementierung nichts.

**Beitrag an den HNI-Fork.** `hibernate.hbm2ddl.auto` ist die einzige
verbliebene Lücke im Env-Konzept des Forks; wir patchen es beim Klonen. Ein PR,
der `SYSML_HBM2DDL` analog zu `SYSML_JDBC_*` ergänzt, wäre klein, sauber
abgegrenzt und ein natürlicher Gesprächsanlass mit den Betreuenden.
