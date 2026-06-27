require 'sinatra'
require 'json'
require 'pg'
require 'redis'

set :port, 8080
set :bind, '0.0.0.0'
set :logging, false

PG_DSN = ENV.fetch('PG_DSN', 'postgres://vibe:vibe@postgres:5432/vibe')
CACHE_HOST = ENV.fetch('REDIS_CACHE_HOST', 'redis-cache')
CACHE_PORT = ENV.fetch('REDIS_CACHE_PORT', '6379').to_i

def pg
  @pg ||= begin
    uri = URI.parse(PG_DSN)
    PG.connect(host: uri.host, port: uri.port, dbname: uri.path.delete('/'),
               user: uri.user, password: uri.password, connect_timeout: 2)
  end
end

def rc
  @rc ||= Redis.new(host: CACHE_HOST, port: CACHE_PORT, connect_timeout: 2)
end

begin
  pg.exec("CREATE TABLE IF NOT EXISTS polls(id SERIAL PRIMARY KEY, question TEXT NOT NULL, options JSONB NOT NULL, creator_id TEXT NOT NULL)")
  pg.exec("CREATE TABLE IF NOT EXISTS votes(id SERIAL PRIMARY KEY, poll_id INT NOT NULL, user_id TEXT NOT NULL, option_idx INT NOT NULL, UNIQUE(poll_id, user_id))")
  $stderr.puts "INFO poll-service: db init ok"
rescue => e
  $stderr.puts "ERROR poll-service: db init failed: #{e.message}"
end

before { content_type :json }

get '/healthz' do
  { status: 'ok', service: 'poll-service' }.to_json
end

post '/polls' do
  data = JSON.parse(request.body.read)
  question = data['question']
  options = data['options'] || []
  creator_id = data['creator_id'] || 'anon'
  begin
    result = pg.exec_params("INSERT INTO polls(question,options,creator_id) VALUES($1,$2::jsonb,$3) RETURNING id,question,options,creator_id",
      [question, options.to_json, creator_id])
    row = result.first
    halt 201, { id: row['id'].to_i, question: row['question'], options: JSON.parse(row['options']), creator_id: row['creator_id'] }.to_json
  rescue => e
    $stderr.puts "ERROR poll-service: POST /polls: #{e.message}"
    halt 500, { error: 'internal error' }.to_json
  end
end

post '/vote' do
  data = JSON.parse(request.body.read)
  poll_id = data['poll_id'].to_i
  user_id = data['user_id']
  option_idx = data['option_idx'].to_i
  begin
    pg.exec_params("INSERT INTO votes(poll_id,user_id,option_idx) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
      [poll_id, user_id, option_idx])
    rc.del("poll:#{poll_id}:results")
    { poll_id: poll_id, user_id: user_id, option_idx: option_idx, status: 'voted' }.to_json
  rescue => e
    $stderr.puts "ERROR poll-service: POST /vote: #{e.message}"
    halt 500, { error: 'internal error' }.to_json
  end
end

get '/polls/:id/results' do
  poll_id = params['id'].to_i
  cache_key = "poll:#{poll_id}:results"
  begin
    cached = rc.get(cache_key)
    return cached if cached
    poll_row = pg.exec_params("SELECT id,question,options FROM polls WHERE id=$1", [poll_id]).first
    halt 404, { error: 'not found' }.to_json unless poll_row
    options = JSON.parse(poll_row['options'])
    tally = options.map.with_index { |opt, i| { option: opt, idx: i, votes: 0 } }
    pg.exec_params("SELECT option_idx, COUNT(*) FROM votes WHERE poll_id=$1 GROUP BY option_idx", [poll_id]).each do |r|
      idx = r['option_idx'].to_i
      tally[idx][:votes] = r['count'].to_i if idx < tally.size
    end
    result = { poll_id: poll_id, question: poll_row['question'], results: tally }.to_json
    rc.setex(cache_key, 30, result)
    result
  rescue => e
    $stderr.puts "ERROR poll-service: GET /polls/#{poll_id}/results: #{e.message}"
    halt 500, { error: 'internal error' }.to_json
  end
end
