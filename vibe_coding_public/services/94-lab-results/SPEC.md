# 94-lab-results — lab-results

**语言**: Kotlin/Ktor  
**依赖**: postgres, redis-stream  
**端口**: 8080

## 功能
- `POST /results` — 新增检验结果，写入 postgres + XADD events:lab_results
- `GET /results/:patient_id` — 查询患者最近检验(每种类型最新一条)

## 表结构
```sql
CREATE TABLE IF NOT EXISTS lab_results(
  id serial PRIMARY KEY,
  patient_id text, test_type text,
  value double precision, unit text,
  reference_range text, collected_at timestamptz
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F09-queue-down, F10-queue-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
