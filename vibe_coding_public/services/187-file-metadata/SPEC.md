# 187-file-metadata

Tracks uploaded-file metadata (no actual blob storage). Each row in Postgres `file_metadata` keeps `filename`, `mime_type`, `size_bytes`, content-addressed `sha256`, `owner_id`, and `uploaded_at`. Indexes on `sha256` and `(owner_id, uploaded_at DESC)` make lookups cheap. Useful as the index sidecar for an object-storage gateway: clients hash blobs, write metadata here, then store the bytes elsewhere.

Endpoints: `GET /healthz`, `POST /files`, `GET /files/{id}`, `GET /files/owner/{owner_id}`, `GET /files/sha/{sha256}`, `GET /files/search?mime=image/jpeg`, `DELETE /files/{id}`.
