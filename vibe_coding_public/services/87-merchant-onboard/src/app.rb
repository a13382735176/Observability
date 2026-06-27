require 'sinatra'
require 'json'
require 'pg'
require 'uri'

set :port, 8080
set :bind, '0.0.0.0'
set :logging, false

PG_DSN = ENV.fetch('PG_DSN', 'postgres://vibe:vibe@postgres:5432/vibe')

def pg
  @pg ||= begin
    uri = URI.parse(PG_DSN)
    PG.connect(host: uri.host, port: uri.port, dbname: uri.path.delete('/'),
               user: uri.user, password: uri.password, connect_timeout: 2)
  end
end

begin
  pg.exec("CREATE TABLE IF NOT EXISTS merchants(id SERIAL PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,business_type TEXT,status TEXT DEFAULT 'pending',created_at TIMESTAMPTZ DEFAULT now())")
  $stderr.puts "INFO merchant-onboard: db init ok"
rescue => e
  $stderr.puts "ERROR merchant-onboard: #{e.message}"
end

before { content_type :json }

get '/healthz' do
  { status: 'ok', service: 'merchant-onboard' }.to_json
end

post '/merchants' do
  data = JSON.parse(request.body.read)
  begin
    r = pg.exec_params(
      "INSERT INTO merchants(name,email,business_type) VALUES($1,$2,$3) RETURNING id,name,email,business_type,status,created_at::text",
      [data['name'], data['email'], data['business_type']]
    ).first
    halt 201, r.to_json
  rescue => e
    $stderr.puts "ERROR merchant-onboard: #{e.message}"
    halt 503, { error: 'db error' }.to_json
  end
end

get '/merchants/:id' do
  begin
    r = pg.exec_params(
      "SELECT id,name,email,business_type,status,created_at::text FROM merchants WHERE id=$1",
      [params['id'].to_i]
    ).first
    halt 404, { error: 'not found' }.to_json unless r
    r.to_json
  rescue => e
    $stderr.puts "ERROR merchant-onboard: #{e.message}"
    halt 503, { error: 'db error' }.to_json
  end
end

put '/merchants/:id/approve' do
  begin
    r = pg.exec_params(
      "UPDATE merchants SET status='approved' WHERE id=$1 RETURNING id,status",
      [params['id'].to_i]
    ).first
    halt 404, { error: 'not found' }.to_json unless r
    r.to_json
  rescue => e
    $stderr.puts "ERROR merchant-onboard: #{e.message}"
    halt 503, { error: 'db error' }.to_json
  end
end

get '/pending' do
  begin
    rows = pg.exec("SELECT id,name,email,business_type,created_at::text FROM merchants WHERE status='pending'").to_a
    rows.to_json
  rescue => e
    $stderr.puts "ERROR merchant-onboard: #{e.message}"
    halt 503, { error: 'db error' }.to_json
  end
end
