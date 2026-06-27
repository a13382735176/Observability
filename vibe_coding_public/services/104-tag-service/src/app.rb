require 'roda'
require 'redis'
require 'json'

CACHE_HOST = ENV.fetch('REDIS_CACHE_HOST', 'redis-cache')
CACHE_PORT = ENV.fetch('REDIS_CACHE_PORT', '6379').to_i

def rc
  @rc ||= Redis.new(host: CACHE_HOST, port: CACHE_PORT, connect_timeout: 2, timeout: 2)
end

begin
  rc.ping
  $stderr.puts "INFO tag-service: redis-cache ready"
rescue => e
  $stderr.puts "ERROR tag-service: redis init failed: #{e.message}"
end

class App < Roda
  plugin :json
  plugin :all_verbs
  plugin :halt

  route do |r|
    r.on 'healthz' do
      r.get { { status: 'ok', service: 'tag-service' } }
    end

    r.on 'tags' do
      r.on String do |tag|
        r.on String do |entity_id|
          r.delete do
            entity_type = r.params['type'] || 'article'
            begin
              rc.srem("tag:#{tag}:#{entity_type}", entity_id)
              { ok: true }
            rescue => e
              $stderr.puts "ERROR tag-service: SREM: #{e.message}"
              r.halt(502, { error: 'redis error' }.to_json)
            end
          end
        end

        r.get do
          entity_type = r.params['type'] || 'article'
          begin
            members = rc.smembers("tag:#{tag}:#{entity_type}")
            { tag: tag, entity_type: entity_type, members: members }
          rescue => e
            $stderr.puts "ERROR tag-service: SMEMBERS: #{e.message}"
            r.halt(502, { error: 'redis error' }.to_json)
          end
        end

        r.post do
          body = JSON.parse(request.body.read)
          entity_id = body['entity_id']
          entity_type = body['entity_type'] || 'article'
          begin
            rc.sadd("tag:#{tag}:#{entity_type}", entity_id)
            { ok: true, tag: tag, entity_id: entity_id, entity_type: entity_type }
          rescue => e
            $stderr.puts "ERROR tag-service: SADD: #{e.message}"
            r.halt(502, { error: 'redis error' }.to_json)
          end
        end
      end
    end
  end
end

run App.freeze.app
