# Roadmap

*Englische Fassung: [ROADMAP.md](ROADMAP.md).*

Leitprinzip: erst der dünne, durchgehende Faden, dann Breite. Jede Stufe baut
auf einer verifizierten Vorgängerstufe auf.

Das Zielsystem beschreiben `goal_spec.txt` (SRS v0.1, „Bi-Directional
Synchronization") und die HNI/IEM-Use-Case-Folien. Diese Roadmap weicht an
einigen Stellen bewusst davon ab; wo sie das tut, steht die Begründung dabei.

| Stufe | Inhalt | Status |
|---|---|---|
| 0–3 | Infrastruktur, Extraktion, Messkern, Verifikations-Engine, CI | **fertig** |
| A | Mapping auf Bauteile umhängen; CAD-Adapter-Schnitt; drei Urteile; Provenienz | **fertig** |
| B | Change-Impact-Analyse | offen |
| C | Evidenz-Log und Reports | offen |
| D | MCP-Server | offen |
| E | Gates und menschliche Bestätigung | offen |
| F | FreeCAD-Adapter | offen |
| G | Schreibpfade, über Zuständigkeit geregelt | offen |
| H | KI-Mapping-Vorschläge | offen |

Reihenfolgen, die nicht verhandelbar sind: **Gates vor Schreiben**, **Gates vor
KI**, **Adapter-Schnitt vor FreeCAD**.

---

## Drei Prinzipien, die über alle Stufen gelten

**1. KI schlägt vor, sie bewertet nie.** Die Folien lesen sich so, als führe
die KI die Verifikation durch („AI can read both systems and then do the
Automated Target/Actual Verification"). Das darf sie nicht. Eine KI-Komponente
schlägt Mappings vor und spricht natürliche Sprache; sobald ein Mapping
bestätigt ist, ist es eine gewöhnliche deterministische Regel, und ihre
Herkunft beeinflusst kein Ergebnis mehr. Genau das verlangen SRS FREQ-5 und
NFREQ-1 — und Folie 9 räumt es mit ihrer eigenen Formulierung „concrete adapter
per attribute … deterministic for auditability" bereits ein.

**2. Mapping-Gültigkeit und Anforderungserfüllung sind zwei Fragen.** Fehlt im
SRS, und ist das, was hier am leichtesten falsch gemacht wird. Gates prüfen die
*Zuordnung* (Dimension, Existenz, Eindeutigkeit, Plausibilität), die
Verifikations-Engine prüft die *Erfüllung*. Ein korrekt gemapptes, aber zu
langes Bauteil ist ein Verstoß, kein Fehlmapping — und genau der Fall, den das
System melden soll. Der ursprüngliche Plan wollte ein Mapping nur dann
persistieren, wenn die Anforderung erfüllt ist. Das würde echte Verstöße
verstecken und falsche Mappings persistieren, die zufällig durchgehen.

**3. „Nicht geprüft" ist nicht „bestanden".** Lücken — kein bestätigtes
Mapping, oder eine Größe, die die CAD-Seite nicht liefern kann — werden durch
den Lauf getragen und gemeldet, nie durch einen Wert ersetzt (SRS FREQ-2) und
nie stillschweigend als Abdeckung gezählt.

---

## Stufe A — Umhängen und Schnitt ✅

Keine neuen sichtbaren Funktionen; der Umbau, der alles Folgende erst trägt.

**A.1 Das Mapping hängt an Bauteilen, nicht an Anforderungen.** Bisher bildete
`mapping.yaml` `requirement_id → cad_module + method` ab. Beide Quelldokumente
verlangen etwas anderes: Die Tabelle auf Folie 9 lautet `partdef → Component`,
`Attribute → Parameter`, und FREQ-3 definiert einen Eintrag als „the identifier
of the system model element and the name of its attribute, the CAD object and
its parameter".

Die dafür nötige Verknüpfung stand längst im Modell und wurde weggeworfen.
`satisfy maxLengthCheck by motorHousing;` serialisiert als:

```
SatisfyRequirementUsage
 ├─ ReferenceSubsetting.general → RequirementUsage → FeatureTyping.general → RequirementDefinition
 └─ SubjectMembership.memberElement → ReferenceUsage → FeatureValue
                                    → FeatureReferenceExpression
                                    → Membership.memberElement → PartUsage
```

`extract.resolve_satisfies()` läuft diesen Pfad jetzt ab. Der Extraktor meldete
früher den Subjekt-*Parameter* der Definition (`housing`); er meldet nun das
Bauteil, das das Modell tatsächlich als eingeschränkt bezeichnet
(`motorHousing`), samt Element-ID und dem Pfad, der die Beziehung belegt.
Folgen: deutlich weniger Mapping-Einträge, eine neue Anforderung an ein bereits
gemapptes Bauteil braucht gar keinen neuen Eintrag, und die
Change-Impact-Analyse hat den Pfad, den sie belegen können muss.

**A.2 Das Mapping bleibt YAML. Das Evidenz-Log wird es nicht.** Die Roadmap
sagte bisher, SQLite ersetze `mapping.yaml`. FREQ-3 widerspricht und hat recht:
Das Mapping muss „human-readable and … placed under version control" sein. Es
ist Entwurfsabsicht und gehört ins Review. Das append-only-*Evidenz*-Log ist
das, was eine Datenbank braucht. Zwei Speicher, zwei Aufgaben.

**A.3 Ein CAD-Adapter-Schnitt.** `sysmlcad/adapters/` definiert `CadAdapter`;
nichts oberhalb importiert einen Geometriekern. `Build123dAdapter` ist die
Referenzimplementierung und bleibt das Offline-Backend für die CI. Die Namen
der Messmethoden (`bbox_size`, `volume`, `mass`, `face_count`) sind
adapterunabhängiges Vokabular; ein Adapter wirft `Unsupported` für das, was er
nicht kann, statt einen ersetzten Wert zu liefern.

**A.4 Drei Urteile und Provenienz.** `compliant` / `within_tolerance` /
`violated` nach FREQ-7, mit der Abweichung, und die Toleranz steht am
Mapping-Eintrag. `RunContext` hält die SysML-Commit-ID, die CAD-`state_id`, den
Mapping-Digest und einen Zeitstempel fest — FREQ-1 verlangt, dass Ergebnisse
einem exakten Modellzustand zuzuordnen sind, und die Commit-ID wurde bisher
geholt und weggeworfen.

**A.5 Ein `direction`-Feld existiert, aber nichts schreibt.** `sysml_owns` /
`cad_owns` / `both`, damit das Freischalten der Schreibpfade in Stufe G eine
Verhaltensänderung ist und keine Schemamigration.

**Aus Stufe A noch offen** (beides braucht einen laufenden API-Server):
- Das Referenzmodell auf eine zweiteilige Baugruppe erweitern, mit einem
  Schnittstellenmaß und einem Massenbudget über die Baugruppe. Ein einzelnes
  Bauteil kann bauteilbasiertes Mapping nicht wirklich ausreizen.
- `airbus/apollo-11-sysml-v2` publizieren und `explore.py` darüber laufen
  lassen. Erwartung: Die Annahme „ein Vergleich pro Anforderung" fällt als
  Erste. Billige, harte Evidenz dafür, welche Vereinfachung im Extraktor als
  Nächstes fällig ist.

---

## Stufe B — Change-Impact-Analyse

Im SRS mit User-Priorität 5/5 (FREQ-8), eine eigene Fähigkeitsgruppe auf den
Folien, ein eigenes Szenario (SCN-3) — und in dieser Roadmap bisher gar nicht
vorhanden. Sie braucht keinen CAD-Schreibzugriff: Es ist Graphtraversierung
über Daten, die wir ohnehin holen, plus das Mapping. Die API des Forks
unterstützt das direkt:

- `GET /projects/:p/commits/:c/elements/:id/relationships?direction=…`
- `GET /projects/:p/commits/:c/changes`

`impact.py`: Zu einer Änderung auf einer der beiden Seiten den
Mapping-Einträgen und den SysML-Traceability-Links folgen und die betroffenen
Anforderungen und Verifikationsfälle zurückgeben — **jeweils mit dem Pfad, der
sie ergeben hat**. Ergebnisse aus einer unvollständigen Linkstruktur werden als
solche markiert: Die Analyse kann nur so vollständig sein wie das Modell, das
sie durchläuft.

Demo: das Beispiel aus dem SRS selbst. Ein Gehäuse von Aluminium auf Kunststoff
umzustellen sieht lokal aus, berührt aber Massenbudget, thermischen Pfad und
Materialzertifizierung.

## Stufe C — Evidenz-Log und Reports

Append-only-SQLite: `run` (ein `RunContext`) plus `result` (eine Zeile je
ausgewerteter Constraint). Nichts wird überschrieben, nichts gelöscht — die
Historie ist die Nachvollziehbarkeit. `report.py` erzeugt HTML (für Menschen)
und JSON (für Maschinen), beide mit der Aussage, welcher Entwurfszustand gegen
welchen Anforderungszustand geprüft wurde. JUnit-XML bleibt für die CI.

## Stufe D — MCP-Server

Ein dünner FastMCP-Wrapper über die Stufen A–C: `list_requirements`, `verify`,
`analyze_impact`, `generate_report`, `explain_mapping`. Keine eigene Logik. Das
ist die Integrationsgeschichte der Folien 8–9 und der Punkt, an dem ein
Assistent gefragt werden kann „was bricht, wenn dieses Gehäuse aus Kunststoff
wird?" — und eine deterministische Antwort bekommt.

## Stufe E — Gates und menschliche Bestätigung

1. **Dimensionskompatibilität** — Länge↔Länge, Masse↔Masse, via pint
2. **Existenz** — ist die Größe am CAD-Objekt überhaupt messbar?
3. **Eindeutigkeit** — keine 1:n-Kollisionen
4. **Plausibilität** — Größenordnung, z. B. Faktor 0,1–10
5. **Bestätigung** — beim ersten Mal durch einen Menschen, protokolliert mit
   Urheber und Zeitstempel (FREQ-5)

Ergebnis: *Mapping gültig / ungültig*, getrennt von *pass / fail*. Vor jedem
Schreibpfad und vor jedem KI-Vorschlag erforderlich.

## Stufe F — FreeCAD-Adapter

Der zweite `CadAdapter`: Dokumentmodell, benannte Parameter und Spreadsheet,
Baugruppenbaum, zugewiesene Materialien. FREQ-2 beschreibt ein lebendes
CAD-Dokument, und das ist build123d strukturell nicht — kein Dokument, keine
Baugruppenzwangsbedingungen, keine Materialeigenschaft. FreeCAD basiert auf
OCCT (passend zu SRS §4.2), ist frei und headless skriptbar.

Schaltet drei der vier operativen Fälle der Folien frei: Budgetverfolgung
(Masse über eine Baugruppe summiert), Schnittstellenkontrolle (vereinbartes Maß
gegen konstruierte Geometrie), Stoffkonformität (Material- und Massendaten).

`Build123dAdapter` bleibt, damit die CI nie FreeCAD braucht.

## Stufe G — Schreibpfade, über Zuständigkeit geregelt

Die Zuständigkeitsregel statt eines Merge-Algorithmus. Der ursprüngliche Plan
schlug Operational Transformation vor; das ist Over-Engineering — OT löst
zeichenweise Nebenläufigkeit in Echtzeit-Editoren, Modellsynchronisation ist
zustandsbasiertes 3-Wege-Diff bei niedriger Frequenz. Was die meisten Konflikte
strukturell verhindert, ist explizite Zuständigkeit pro Parameter — und genau
das ist FREQ-3s `direction`-Feld bereits.

- Geschrieben wird nur dort, wo der Mapping-Eintrag die Befugnis erteilt: SysML
  besitzt Grenzwerte, CAD besitzt Ist-Werte. Dann kollidieren die beiden Seiten
  nicht mehr; es bleiben nur Verletzungen.
- **Aufwärts:** Ist-Werte und Urteile nach SysML via
  `POST /projects/:id/commits`.
- **Abwärts:** Grenzwerte ins CAD als Parameter oder Annotationen. **Keine
  automatischen Geometrieänderungen** — das schafft Rückverfolgbarkeit und
  signalisiert Änderungsbedarf, ohne dass ein Algorithmus still ein Bauteil
  umbaut.
- Jeder Lauf bietet eine Vorschau der Wertänderungen, die er vornehmen würde
  (SRS §4.1, Synchronisationsansicht). Jeder Schreibvorgang landet im
  Evidenz-Log.

**FREQ-6 (strukturelle Instanziierung)** — ein CAD-Skelett aus der
SysML-Bauteilstruktur erzeugen — wird zurückgestellt, bis das hier stabil ist.
Es ist der teuerste Posten im SRS und bringt am wenigsten, solange Baugruppen
nicht funktionieren.

**Vor dem Entwurf lesen:** `Open-MBEE/sysmlv2_dls`, Paket `geometry_api`. Dort
existiert eine CAD-agnostische Baugruppen-Repräsentation mit Translation,
Rotation und Ownership plus ein Onshape-Connector, der aus SysML heraus
schreibt. Entgegengesetzte Designentscheidung zu unserer (dort trägt SysML die
Geometriestruktur), aber die fertige Antwort auf die Transformationsmathematik,
falls wir von Einzelteilen auf Baugruppen gehen.

## Stufe H — KI-Mapping-Vorschläge

`rapidfuzz` (String-Distanz) plus `sentence-transformers` (Embeddings) über
Namen und Metadaten; optional ein LLM mit strukturiertem JSON-Output.
Kandidaten laufen mit `status: proposed`, einem Konfidenzwert und einer
Begründung ein und werden nie automatisch angewendet (FREQ-4, FREQ-5).

**Messbar machen:** Trefferquote gegen ein handgemapptes Gold-Set. Ohne diese
Zahl gibt es keinen Beleg, dass der KI-Teil überhaupt Zeit spart.

---

## Bewusst zurückgestellt

**SMT auf dem Constraint-Netz.** Eine Abgrenzung, die im ursprünglichen Plan
fehlte: Z3 kann über B-Rep-Geometrie nichts beweisen. SMT gehört auf das
*Constraint-Netz*, nicht auf das CAD-Modell. Sinnvolle Ziele sind
Widerspruchsfreiheit des Anforderungssatzes, Massen- und Kostenbudgets über
Baugruppenhierarchien und Gegenbeispiele im Parameterraum — die dann
automatisch zu neuen Testfällen in der Verifikations-Engine werden. Werkzeug:
`z3-solver`.

**Web-Frontend, OAuth2, Multi-Projekt-Dashboard.** Steht im SRS (§4.1, §4.3),
aber nicht in den nächsten Stufen. Der Kern wird als Bibliothek gebaut, damit
die spätere Oberfläche ein zweiter Konsument neben CLI und MCP ist und kein
Neuschrieb.

---

## Offene Architekturfragen

**Welches CAD-System produktiv?** Sind CATIA oder Creo gesetzt, trägt der
Adapter-Schnitt das bereits — der Messkern wird eine Adapterschicht über deren
API statt über OCC, und oberhalb von `CadAdapter` ändert sich nichts. Der PoC
sollte dann früh gegen einen Ausschnitt echter Modelldaten laufen; dort sitzen
die eigentlichen Reibungspunkte.

**Baugruppen statt Einzelteile.** Der Messkern kennt ein Bauteil pro Objekt.
Baugruppen brauchen Aggregation (Summe der Massen) und Positionierung — siehe
Stufe F und den `geometry_api`-Hinweis oben.

**Model-Management.** Falls Versionierung, Branching und Zugriffsrechte über
den PoC hinaus gebraucht werden, ist Open-MBEE (MMS) der etablierte Kandidat.
Für den aktuellen Stand bringt es gegenüber der Pilot-Implementierung nichts.

**Beitrag an den HNI-Fork.** `hibernate.hbm2ddl.auto` ist die einzige
verbliebene Lücke im Env-Konzept des Forks; wir patchen es beim Klonen. Ein PR,
der `SYSML_HBM2DDL` analog zu `SYSML_JDBC_*` ergänzt, wäre klein, sauber
abgegrenzt und ein natürlicher Gesprächsanlass mit den Betreuenden.
