# 164-backup-orchestrator

Backup and restore tracking service. Records backup operations in Postgres (resource type, resource id, storage location, size), allows operators to query backups by resource, and creates restore jobs that move through a `pending → completed` lifecycle. Each backup creation and restore request is published to Redis streams (`events:backups`, `events:restores`).

Endpoints: `GET /healthz`, `POST /backups`, `GET /backups`, `GET /backups/<resource_type>/<resource_id>`, `POST /restore`, `PUT /restore/<id>/complete`.
