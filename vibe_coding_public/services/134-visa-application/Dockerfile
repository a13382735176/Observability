FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /work
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src/ src/
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /work/target/visa-application.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
