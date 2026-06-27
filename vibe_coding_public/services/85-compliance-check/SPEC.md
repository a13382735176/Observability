# 85-compliance-check

**Language**: Java/Spring Boot  **Deps**: postgres

## Endpoints
- `GET  /healthz`
- `POST /check` body: `{entity_id, check_type}` → saves result (passed=random>0.1)
- `GET  /results/:entity_id` → list results for entity
- `POST /rules` body: `{rule_name, description, threshold}` → save rule

## Tables
`compliance_rules(id serial PK, rule_name text UNIQUE, description text, threshold_value double precision)`
`compliance_results(id serial PK, entity_id text, rule_name text, passed bool, checked_at timestamptz)`
