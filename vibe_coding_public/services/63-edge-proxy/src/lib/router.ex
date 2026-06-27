defmodule Router do
  use Plug.Router
  require Logger
  plug Plug.Parsers, parsers: [:json], json_decoder: Jason
  plug :match
  plug :dispatch

  get "/healthz" do
    send_resp(conn, 200, Jason.encode!(%{status: "ok", service: "edge-proxy"}))
  end

  get "/config/:device_id" do
    key = "cfg:#{device_id}"
    case Redix.command(:cache, ["GET", key], timeout: 2000) do
      {:ok, nil} -> send_resp(conn, 404, Jason.encode!(%{error: "not found"}))
      {:ok, val} ->
        case Jason.decode(val) do
          {:ok, data} -> send_resp(conn, 200, Jason.encode!(data))
          _ -> send_resp(conn, 200, val)
        end
      {:error, e} ->
        Logger.error("edge-proxy: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "redis error"}))
    end
  end

  put "/config/:device_id" do
    key = "cfg:#{device_id}"
    body = Jason.encode!(conn.body_params)
    case Redix.command(:cache, ["SET", key, body, "EX", "300"], timeout: 2000) do
      {:ok, _} -> send_resp(conn, 200, Jason.encode!(%{ok: true}))
      {:error, e} ->
        Logger.error("edge-proxy: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "redis error"}))
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
    cache_host = System.get_env("REDIS_CACHE_HOST", "redis-cache")
    children = [
      {Redix, [name: :cache, host: cache_host, port: 6379, timeout: 2000]},
      {Plug.Cowboy, scheme: :http, plug: Router, options: [port: 8080]}
    ]
    Supervisor.start_link(children, strategy: :one_for_one)
  end
end
