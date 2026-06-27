# 93-prescription-svc — prescription-svc

**语言**: Go/gin  
**依赖**: postgres  
**端口**: 8080

## 功能
- `POST /prescriptions` — 创建处方
- `GET /prescriptions/:patient_id/active` — 获取有效处方
- `GET /prescriptions/id/:id` — 按 ID 查询

## 表结构
```sql
CREATE TABLE IF NOT EXISTS prescriptions(
  id serial PRIMARY KEY,
  patient_id text, doctor_id text,
  medication text, dosage text,
  duration_days int, issued_at timestamptz, active bool DEFAULT true
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
