defmodule Router do
  use Plug.Router
  require Logger
  plug Plug.Parsers, parsers: [:json], json_decoder: Jason
  plug :match
  plug :dispatch

  get "/healthz" do
    send_resp(conn, 200, Jason.encode!(%{status: "ok", service: "telemedicine-svc"}))
  end

  post "/sessions" do
    %{"patient_id" => patient_id, "doctor_id" => doctor_id} = conn.body_params
    token = :crypto.strong_rand_bytes(16) |> Base.encode16(case: :lower)
    fields = %{"patient_id" => patient_id, "doctor_id" => doctor_id,
               "status" => "active", "token" => token}
    try do
      Redix.command(:redis_cache, ["HSET", "session:#{token}" | Enum.flat_map(fields, fn {k, v} -> [k, v] end)])
      Redix.command(:redis_stream, ["XADD", "events:telemedicine", "*",
        "token", token, "patient_id", patient_id, "doctor_id", doctor_id])
      send_resp(conn, 201, Jason.encode!(%{token: token, patient_id: patient_id, doctor_id: doctor_id}))
    rescue
      e ->
        Logger.error("telemedicine-svc: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "error"}))
    end
  end

  get "/sessions/:token/status" do
    case Redix.command(:redis_cache, ["HGETALL", "session:#{token}"]) do
      {:ok, []} ->
        send_resp(conn, 404, Jason.encode!(%{error: "not found"}))
      {:ok, pairs} ->
        data = pairs |> Enum.chunk_every(2) |> Enum.map(fn [k, v] -> {k, v} end) |> Map.new()
        send_resp(conn, 200, Jason.encode!(data))
      {:error, e} ->
        Logger.error("telemedicine-svc: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "cache error"}))
    end
  end

  delete "/sessions/:token" do
    case Redix.command(:redis_cache, ["DEL", "session:#{token}"]) do
      {:ok, _} ->
        send_resp(conn, 200, Jason.encode!(%{ok: true}))
      {:error, e} ->
        Logger.error("telemedicine-svc: #{inspect(e)}")
        send_resp(conn, 503, Jason.encode!(%{error: "error"}))
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
    stream_host = System.get_env("REDIS_STREAM_HOST", "redis-stream")
    children = [
      Supervisor.child_spec(
        {Redix, [name: :redis_cache, host: cache_host, port: 6379, timeout: 2000]},
        id: :redis_cache
      ),
      Supervisor.child_spec(
        {Redix, [name: :redis_stream, host: stream_host, port: 6379, timeout: 2000]},
        id: :redis_stream
      ),
      {Plug.Cowboy, scheme: :http, plug: Router, options: [port: 8080]}
    ]
    {:ok, sup} = Supervisor.start_link(children, strategy: :one_for_one)
    Logger.info("telemedicine-svc: started on port 8080")
    {:ok, sup}
  end
end
