# 96-medication-remind — medication-remind

**语言**: Rust/Axum  
**依赖**: postgres, redis-stream  
**端口**: 8080

## 功能
- `POST /reminders` — 创建用药提醒
- `POST /taken` — 记录服药事件(XADD events:medication_taken)
- `GET /reminders/:patient_id/active` — 查询有效提醒

## 表结构
```sql
CREATE TABLE IF NOT EXISTS medication_reminders(
  id serial PRIMARY KEY, patient_id text,
  medication text, times_per_day int,
  start_date date, end_date date, active bool DEFAULT true
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F09-queue-down, F10-queue-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
