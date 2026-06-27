# 91-appointment-svc — appointment-svc

**语言**: TypeScript/Express  
**依赖**: postgres, redis-cache  
**端口**: 8080

## 功能
- `POST /appointments` — 创建预约(patient_id, doctor_id, datetime_iso, reason)，写入 postgres 并 Redis SADD
- `GET /appointments/:patient_id` — 查询患者预约，Redis ids → postgres 详情
- `PUT /appointments/:id/cancel` — 取消预约

## 表结构
```sql
CREATE TABLE IF NOT EXISTS appointments(
  id serial PRIMARY KEY,
  patient_id text,
  doctor_id text,
  appointment_time timestamptz,
  reason text,
  status text DEFAULT 'booked'
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F07-cache-down, F08-cache-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
