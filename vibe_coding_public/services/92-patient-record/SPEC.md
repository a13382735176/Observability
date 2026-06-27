# 92-patient-record — patient-record

**语言**: Java/Spring Boot 3.3.0  
**依赖**: postgres  
**端口**: 8080

## 功能
- `POST /patients` — 创建患者记录(name, dob_str, blood_type, allergies:[str])
- `GET /patients/:id` — 查询患者
- `PUT /patients/:id/allergies` — 更新过敏信息

## 表结构
```sql
CREATE TABLE patients(
  id serial PRIMARY KEY,
  name text,
  dob date,
  blood_type text,
  allergies jsonb DEFAULT '[]',
  created_at timestamptz
);
```

## 故障注入
F01-pod-kill, F02-network-delay, F05-db-down, F06-db-slow, F11-cpu-stress, F12-net-corrupt, F13-time-skew
