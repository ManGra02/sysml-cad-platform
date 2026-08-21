# Es gibt kein offizielles Image der SysML-v2-API-Services.
# Basis: sbt + Temurin JDK 11 (das Pilot-Projekt verlangt ausdruecklich JDK 11).
FROM sbtscala/scala-sbt:eclipse-temurin-jammy-11.0.22_7_1.9.9_2.13.13

ARG DB_HOST=postgres

WORKDIR /app
COPY vendor/SysML-v2-API-Services/ /app/

# Die JDBC-URL steht FEST in conf/META-INF/persistence.xml und laesst sich
# nicht per System-Property ueberschreiben -- Hibernate liest sie von dort.
# Deshalb wird sie beim Build auf den Compose-Servicenamen umgeschrieben.
# JDBC-URL steht fest in persistence.xml; zusaetzlich hbm2ddl auf "update",
# damit das Schema Neustarts ueberlebt statt bei jedem Stop geloescht zu werden.
RUN sed -i "s|//localhost:5432|//${DB_HOST}:5432|g" conf/META-INF/persistence.xml \
 && sed -i 's|"hibernate.hbm2ddl.auto" value="create-drop"|"hibernate.hbm2ddl.auto" value="update"|' conf/META-INF/persistence.xml \
 && grep -n "jdbc.url\|hbm2ddl" conf/META-INF/persistence.xml

# Produktionsmodus statt "sbt run": erzeugt ein eigenstaendiges Startskript,
# das kein interaktives Terminal braucht.
RUN sbt -batch clean stage

EXPOSE 9000

CMD ["/bin/sh", "-c", "exec /app/target/universal/stage/bin/sysml-v2-api-services -Dhttp.address=0.0.0.0 -Dhttp.port=9000 -Dplay.filters.hosts.allowed.0='.' -Dplay.http.secret.key=$(head -c 48 /dev/urandom | base64 | tr -d '\\n')"]