# Notificaciones: backend Spring Boot + PostgreSQL en el mismo contenedor (supervisord).
# Ver docs/arquitectura.md, sección 8.

# --- Etapa 1: compilar con Maven ---
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package -DskipTests

# --- Etapa 2: PostgreSQL + JRE 21 copiado de eclipse-temurin ---
FROM postgres:16

# curl: lo usa el healthcheck del docker-compose
RUN apt-get update \
 && apt-get install -y --no-install-recommends supervisor curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

WORKDIR /app
COPY --from=build /build/target/notificaciones.jar /app/notificaciones.jar
COPY supervisord.conf /etc/supervisor/conf.d/app.conf

EXPOSE 8080
ENTRYPOINT []
CMD ["supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
