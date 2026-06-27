FROM sbtscala/scala-sbt:eclipse-temurin-alpine-21.0.2_13_1.10.0_3.3.3 AS build
WORKDIR /app
COPY src/ .
RUN sbt assembly -J-Xmx2g
FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /app/target/scala-3.3.3/transaction-log-skill.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
