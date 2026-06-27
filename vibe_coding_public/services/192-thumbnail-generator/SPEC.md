# 192-thumbnail-generator

Java/Spring Boot 3.3 thumbnail generation service. Accepts an image URL and a list of sizes, fans out to the mock upstream (`POST /thumbnail`) to render each variant, persists job state in postgres, and caches results in redis (`thumb:<url>:<size>`, TTL 3600s).

Endpoints: `GET /healthz`, `POST /thumbnails`, `GET /thumbnails/by-source?url=`, `GET /thumbnails/cached/{size}?url=`, `DELETE /thumbnails/{id}`.

Dependencies: postgres (table `thumbnail_jobs` auto-created via JPA `ddl-auto=update`), redis-cache, mock-upstream. Faults: F01–F08, F11, F12, F13.
