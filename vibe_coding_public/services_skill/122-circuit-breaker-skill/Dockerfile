FROM gradle:8.7-jdk21 AS build
WORKDIR /work
COPY src/ ./
RUN gradle --no-daemon shadowJar

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /work/build/libs/app.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar"]
