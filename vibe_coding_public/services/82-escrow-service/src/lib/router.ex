defmodule Router do
  use Plug.Router
  require Logger
  plug Plug.Parsers, parsers: [:json], json_decoder: Jason
  plug :match
  plug :dispatch

  get "/healthz" do
    send_resp(conn, 200, Jason.encode!(%{status: "ok", service: "escrow-service"}))
  end

  post "/escrows" do
    %{"payer_id" => payer, "payee_id" => payee, "amount_cents" => amount, "condition" => condition} = conn.body_params
    sql = "INSERT INTO escrows(payer_id,payee_id,amount_cents,condition) VALUES($1,$2,$3,$4) RETURNING id,payer_id,payee_id,amount_cents,condition,status,created_at::text"
    case Postgrex.query(:db, sql, [payer, payee, amount, condition], timeout: 2000) do
      {:ok, %{rows: [[id | rest]]}} ->
        cache_key = "escrow:#{id}"
        fields = %{"payer_id" => payer, "payee_id" => payee,
                   "amount_cents" => to_string(amount), "condition" => condition, "status" => "held"}
        case Redix.command(:redis, ["HSET", cache_key | Enum.flat_map(fields, fn {k,v} -> [k,v] end)]) do
          {:ok, _} -> :ok
          {:error, e} -> Logger.error("escrow-service: #{inspect(e)}")
        end
        result = %{id: id, payer_id: payer, payee_id: payee, amount_cents: amount,
                   condition: condition, status: "held"}
        send_resp(conn, 201, Jason.encode!(result))
      {:error, e} ->
        Logger.error("escrow-service: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "db error"}))
    end
  end

  get "/escrows/:id" do
    eid = String.to_integer(id)
    cache_key = "escrow:#{eid}"
    case Redix.command(:redis, ["HGETALL", cache_key]) do
      {:ok, []} ->
        sql = "SELECT id,payer_id,payee_id,amount_cents,condition,status,created_at::text FROM escrows WHERE id=$1"
        case Postgrex.query(:db, sql, [eid], timeout: 2000) do
          {:ok, %{rows: [row], columns: cols}} ->
            data = Enum.zip(cols, row) |> Map.new()
            send_resp(conn, 200, Jason.encode!(data))
          {:ok, %{rows: []}} ->
            send_resp(conn, 404, Jason.encode!(%{error: "not found"}))
          {:error, e} ->
            Logger.error("escrow-service: #{inspect(e)}")
            send_resp(conn, 503, Jason.encode!(%{error: "db error"}))
        end
      {:ok, pairs} ->
        data = pairs |> Enum.chunk_every(2) |> Enum.map(fn [k,v] -> {k,v} end) |> Map.new()
        send_resp(conn, 200, Jason.encode!(data))
      {:error, e} ->
        Logger.error("escrow-service: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "cache error"}))
    end
  end

  post "/escrows/:id/release" do
    eid = String.to_integer(id)
    sql = "UPDATE escrows SET status='released' WHERE id=$1 RETURNING id,status"
    case Postgrex.query(:db, sql, [eid], timeout: 2000) do
      {:ok, %{rows: [[rid, status]]}} ->
        Redix.command(:redis, ["DEL", "escrow:#{eid}"])
        send_resp(conn, 200, Jason.encode!(%{id: rid, status: status}))
      {:ok, %{rows: []}} ->
        send_resp(conn, 404, Jason.encode!(%{error: "not found"}))
      {:error, e} ->
        Logger.error("escrow-service: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "db error"}))
    end
  end

  match _ do
    send_resp(conn, 404, "not found")
  end
end

defmodule App do
  use Application
  require Logger
  def start(_type, _args) do
    dsn = System.get_env("PG_DSN", "postgres://vibe:vibe@postgres:5432/vibe")
    cache_host = System.get_env("REDIS_CACHE_HOST", "redis-cache")
    uri = URI.parse(dsn)
    [user, pass] = String.split(uri.userinfo, ":")
    [_, db] = String.split(uri.path, "/")
    pg_opts = [hostname: uri.host, port: uri.port || 5432, username: user,
               password: pass, database: db, name: :db, timeout: 2000, connect_timeout: 2000]
    redis_url = "redis://#{cache_host}:6379"
    children = [
      {Postgrex, pg_opts},
      {Redix, {redis_url, [name: :redis, timeout: 2000]}},
      {Plug.Cowboy, scheme: :http, plug: Router, options: [port: 8080]}
    ]
    {:ok, sup} = Supervisor.start_link(children, strategy: :one_for_one)
    ensure_table()
    {:ok, sup}
  end
  defp ensure_table do
    sql = "CREATE TABLE IF NOT EXISTS escrows(id serial PRIMARY KEY,payer_id text,payee_id text,amount_cents bigint,condition text,status text DEFAULT 'held',created_at timestamptz DEFAULT now())"
    case Postgrex.query(:db, sql, [], timeout: 5000) do
      {:ok, _} -> Logger.info("escrow-service: db ready")
      {:error, e} -> Logger.error("escrow-service: #{inspect(e)}")
    end
  end
end
