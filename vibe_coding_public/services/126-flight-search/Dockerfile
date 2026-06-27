FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY src/pom.xml .
RUN mvn dependency:go-offline -q
COPY src/ .
RUN mvn package -DskipTests -q

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
