FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /work
COPY *.csproj .
RUN dotnet restore
COPY . .
RUN dotnet publish -c Release -o /app /p:UseAppHost=false /p:GenerateDocumentationFile=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine
WORKDIR /app
COPY --from=build /app .
EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENTRYPOINT ["dotnet", "app.dll"]
