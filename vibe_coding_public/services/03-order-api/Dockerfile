FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /work
COPY pom.xml .
RUN mvn -q -B -DskipTests dependency:go-offline || true
COPY src/ src/
RUN mvn -q -B -DskipTests package

FROM eclipse-temurin:21-jre-alpine
COPY --from=build /work/target/*-jar-with-dependencies.jar /app.jar
EXPOSE 8080
CMD ["java", "-jar", "/app.jar"]
