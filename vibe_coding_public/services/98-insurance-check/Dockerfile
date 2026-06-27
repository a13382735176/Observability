FROM composer:2 AS deps
WORKDIR /app
COPY src/composer.json ./
RUN composer install --no-dev --no-interaction --optimize-autoloader

FROM php:8.3-cli-alpine
RUN apk add --no-cache postgresql-dev libpq && docker-php-ext-install pdo pdo_pgsql
WORKDIR /app
COPY --from=deps /app/vendor vendor/
COPY src/ .
EXPOSE 8080
CMD ["php", "-S", "0.0.0.0:8080", "-t", "public/"]
