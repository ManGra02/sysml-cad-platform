# Es gibt kein offizielles Image der SysML-v2-API-Services.
# Basis: sbt + Temurin JDK 11 (das Pilot-Projekt verlangt ausdruecklich JDK 11).
FROM sbtscala/scala-sbt:eclipse-temurin-jammy-11.0.22_7_1.9.9_2.13.13

WORKDIR /app
COPY vendor/SysML-v2-API-Services/ /app/

# Abhaengigkeiten und Scala-Compilat vorwaermen, damit der erste Start
# nicht zehn Minuten am Netz haengt.
RUN sbt -batch clean compile

EXPOSE 9000

# ACHTUNG: Die Property-Namen unten muessen gegen conf/application.conf
# des geklonten Repos geprueft werden -- das ist die eine Stelle,
# die zwischen Releases wandert. Siehe README, Abschnitt "Bekannte Stolpersteine".
CMD sbt -batch \
      -Ddb.default.url="${DB_URL}" \
      -Ddb.default.username="${DB_USER}" \
      -Ddb.default.password="${DB_PASSWORD}" \
      -Dhttp.address=0.0.0.0 \
      -Dhttp.port=9000 \
      run
