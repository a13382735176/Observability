FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY invoice-generator-skill.csproj ./
RUN dotnet restore invoice-generator-skill.csproj
COPY src/ .
RUN dotnet publish invoice-generator-skill.csproj -c Release -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "invoice-generator-skill.dll"]
