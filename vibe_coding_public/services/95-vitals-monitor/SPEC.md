# 95-vitals-monitor — vitals-monitor

**语言**: Python/FastAPI  
**依赖**: redis-cache, redis-stream  
**端口**: 8080

## 功能
- `POST /vitals` — 上报体征数据(heart_rate, bp, spo2, temp_c)，Redis HSET + XADD
- `GET /vitals/:patient_id/latest` — 读取最新体征

## 故障注入
F01-pod-kill, F02-network-delay, F07-cache-down, F08-cache-slow, F09-queue-down, F10-queue-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
