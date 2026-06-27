# 99-symptom-checker — symptom-checker

**语言**: Java/Spring Boot 3.3.0  
**依赖**: redis-cache  
**端口**: 8080

## 功能
- `PUT /conditions` — 存储症状条件(Redis HSET "symptoms:name" data=json)
- `GET /conditions` — 列出所有已知条件
- `POST /assess` — 症状评估，返回匹配条件

## 故障注入
F01-pod-kill, F02-network-delay, F07-cache-down, F08-cache-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
