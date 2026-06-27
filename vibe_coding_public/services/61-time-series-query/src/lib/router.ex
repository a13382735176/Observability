defmodule Router do
  use Plug.Router
  require Logger
  plug Plug.Parsers, parsers: [:json], json_decoder: Jason
  plug :match
  plug :dispatch

  get "/healthz" do
    send_resp(conn, 200, Jason.encode!(%{status: "ok", service: "time-series-query"}))
  end

  post "/datapoints" do
    %{"device_id" => did, "metric" => metric, "value" => value, "ts_iso" => ts} = conn.body_params
    sql = "INSERT INTO datapoints(device_id,metric,value,ts) VALUES(,,,::timestamptz)"
    case Postgrex.query(:db, sql, [did, metric, value/1, ts], timeout: 2000) do
      {:ok, _} -> send_resp(conn, 201, Jason.encode!(%{ok: true}))
      {:error, e} ->
        Logger.error("time-series-query: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "db error"}))
    end
  end

  get "/series/:device_id" do
    metric = conn.query_params["metric"] || ""
    sql = "SELECT id,device_id,metric,value,ts FROM datapoints WHERE device_id= AND metric= ORDER BY ts DESC LIMIT 100"
    case Postgrex.query(:db, sql, [device_id, metric], timeout: 2000) do
      {:ok, %{rows: rows, columns: cols}} ->
        data = Enum.map(rows, fn r -> Enum.zip(cols, r) |> Map.new() end)
        send_resp(conn, 200, Jason.encode!(data))
      {:error, e} ->
        Logger.error("time-series-query: #{inspect(e)}")
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
    uri = URI.parse(dsn)
    [user, pass] = String.split(uri.userinfo, ":")
    [_, db] = String.split(uri.path, "/")
    pg_opts = [hostname: uri.host, port: uri.port || 5432, username: user,
               password: pass, database: db, name: :db, timeout: 2000, connect_timeout: 2000]
    children = [{Postgrex, pg_opts}, {Plug.Cowboy, scheme: :http, plug: Router, options: [port: 8080]}]
    {:ok, sup} = Supervisor.start_link(children, strategy: :one_for_one)
    ensure_table()
    {:ok, sup}
  end
  defp ensure_table do
    sql = "CREATE TABLE IF NOT EXISTS datapoints(id serial PRIMARY KEY, device_id text, metric text, value real, ts timestamptz DEFAULT now())"
    case Postgrex.query(:db, sql, [], timeout: 5000) do
      {:ok, _} -> :ok
      {:error, e} -> Logger.error("time-series-query: ensure_table: #{inspect(e)}")
    end
  end
end
