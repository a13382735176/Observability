FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY refund-svc.csproj ./
RUN dotnet restore refund-svc.csproj
COPY . .
RUN dotnet publish refund-svc.csproj -c Release -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "refund-svc.dll"]
