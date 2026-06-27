# 97-doctor-schedule — doctor-schedule

**语言**: C#/.NET8  
**依赖**: postgres, redis-cache  
**端口**: 8080

## 功能
- `POST /schedules` — 创建可预约时段
- `GET /schedules/:doctor_id/available` — 查询可用时段(Redis 缓存)
- `POST /book` — 预约时段

## 表结构
```sql
CREATE TABLE IF NOT EXISTS schedule_slots(
  id serial PRIMARY KEY, doctor_id text,
  slot_datetime timestamptz, patient_id text,
  booked bool DEFAULT false
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F07-cache-down, F08-cache-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
