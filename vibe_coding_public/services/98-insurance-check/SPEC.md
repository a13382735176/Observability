# 98-insurance-check — insurance-check

**语言**: PHP/Slim 4  
**依赖**: postgres, mock-upstream  
**端口**: 8080

## 功能
- `POST /eligibility` — 调用 mock-upstream 校验保险资格，结果写入 postgres
- `GET /eligibility/:patient_id` — 查询历史校验记录

## 表结构
```sql
CREATE TABLE IF NOT EXISTS eligibility_records(
  id serial PRIMARY KEY, patient_id text,
  insurance_id text, eligible bool DEFAULT false,
  checked_at timestamptz DEFAULT now()
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F03-upstream-fail, F04-upstream-slow, F05-db-down, F06-db-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
