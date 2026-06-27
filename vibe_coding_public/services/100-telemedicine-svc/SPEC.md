# 100-telemedicine-svc — telemedicine-svc

**语言**: Elixir/Plug+Cowboy  
**依赖**: redis-cache, redis-stream  
**端口**: 8080

## 功能
- `POST /sessions` — 创建远程问诊会话(UUID token, Redis HSET + XADD events:telemedicine)
- `GET /sessions/:token/status` — 查询会话状态
- `DELETE /sessions/:token` — 结束会话

## 故障注入
F01-pod-kill, F02-network-delay, F07-cache-down, F08-cache-slow, F09-queue-down, F10-queue-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
