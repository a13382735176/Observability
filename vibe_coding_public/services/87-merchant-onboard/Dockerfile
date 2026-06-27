FROM ruby:3.3-alpine
RUN apk add --no-cache postgresql-dev build-base
WORKDIR /app
COPY src/Gemfile src/Gemfile.lock* ./
RUN bundle install
COPY src/ .
EXPOSE 8080
CMD ["ruby", "app.rb", "-p", "8080", "-o", "0.0.0.0"]
