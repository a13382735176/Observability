FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /work
COPY src/pom.xml .
RUN mvn -B dependency:go-offline
COPY src/ .
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /work/target/promo-engine.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar"]
