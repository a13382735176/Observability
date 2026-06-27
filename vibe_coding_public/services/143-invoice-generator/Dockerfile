FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY invoice-generator.csproj ./
RUN dotnet restore invoice-generator.csproj
COPY . .
RUN dotnet publish invoice-generator.csproj -c Release -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "invoice-generator.dll"]
