FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY loyalty-mileage.csproj ./
RUN dotnet restore loyalty-mileage.csproj
COPY . .
RUN dotnet publish loyalty-mileage.csproj -c Release -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "loyalty-mileage.dll"]
