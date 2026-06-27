import express, { Request, Response } from 'express';
import { Pool } from 'pg';

const SERVICE = 'file-metadata';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';

const app = express();
app.use(express.json({ limit: '1mb' }));

const pool = new Pool({
    connectionString: PG_DSN,
    connectionTimeoutMillis: 2000,
    statement_timeout: 2000,
    query_timeout: 2000,
    idleTimeoutMillis: 10000,
    max: 4,
});
pool.on('error', (err: any) => {
    console.error(`ERROR ${SERVICE}: pool error: ${err?.message || err}`);
});

async function initDb() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS file_metadata (
                id bigserial PRIMARY KEY,
                filename text,
                mime_type text,
                size_bytes bigint,
                sha256 text,
                owner_id text,
                uploaded_at timestamptz DEFAULT now()
            )
        `);
        await pool.query(`CREATE INDEX IF NOT EXISTS file_metadata_sha256_idx ON file_metadata (sha256)`);
        await pool.query(`CREATE INDEX IF NOT EXISTS file_metadata_owner_uploaded_idx ON file_metadata (owner_id, uploaded_at DESC)`);
        console.log(`${SERVICE}: db init ok`);
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: db init failed: ${err?.message || err}`);
    }
}

function rowToFile(row: any) {
    if (!row) return row;
    return {
        id: typeof row.id === 'bigint' ? row.id.toString() : row.id,
        filename: row.filename,
        mime_type: row.mime_type,
        size_bytes: typeof row.size_bytes === 'bigint' ? row.size_bytes.toString() : row.size_bytes,
        sha256: row.sha256,
        owner_id: row.owner_id,
        uploaded_at: row.uploaded_at instanceof Date ? row.uploaded_at.toISOString() : row.uploaded_at,
    };
}

app.get('/healthz', (_req: Request, res: Response) => {
    res.json({ status: 'ok', service: SERVICE });
});

app.post('/files', async (req: Request, res: Response) => {
    const { filename, mime_type, size_bytes, sha256, owner_id } = req.body || {};
    if (!filename || !mime_type || size_bytes === undefined || size_bytes === null || !sha256 || !owner_id) {
        return res.status(400).json({ error: 'filename, mime_type, size_bytes, sha256, owner_id required' });
    }
    try {
        const r = await pool.query(
            `INSERT INTO file_metadata(filename, mime_type, size_bytes, sha256, owner_id)
             VALUES($1, $2, $3, $4, $5)
             RETURNING id, filename, mime_type, size_bytes, sha256, owner_id, uploaded_at`,
            [filename, mime_type, size_bytes, sha256, owner_id]
        );
        res.status(201).json(rowToFile(r.rows[0]));
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: POST /files: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/files/search', async (req: Request, res: Response) => {
    const mime = typeof req.query.mime === 'string' ? req.query.mime : '';
    if (!mime) {
        return res.status(400).json({ error: 'mime query param required' });
    }
    try {
        const r = await pool.query(
            `SELECT id, filename, mime_type, size_bytes, sha256, owner_id, uploaded_at
             FROM file_metadata
             WHERE mime_type LIKE $1
             ORDER BY id DESC LIMIT 100`,
            [mime + '%']
        );
        res.json(r.rows.map(rowToFile));
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: GET /files/search: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/files/owner/:ownerId', async (req: Request, res: Response) => {
    const ownerId = req.params.ownerId;
    try {
        const r = await pool.query(
            `SELECT id, filename, mime_type, size_bytes, sha256, owner_id, uploaded_at
             FROM file_metadata
             WHERE owner_id = $1
             ORDER BY uploaded_at DESC LIMIT 100`,
            [ownerId]
        );
        res.json(r.rows.map(rowToFile));
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: GET /files/owner/${ownerId}: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/files/sha/:sha256', async (req: Request, res: Response) => {
    const sha = req.params.sha256;
    try {
        const r = await pool.query(
            `SELECT id, filename, mime_type, size_bytes, sha256, owner_id, uploaded_at
             FROM file_metadata
             WHERE sha256 = $1
             ORDER BY id DESC LIMIT 100`,
            [sha]
        );
        res.json(r.rows.map(rowToFile));
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: GET /files/sha/${sha}: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.get('/files/:id', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(
            `SELECT id, filename, mime_type, size_bytes, sha256, owner_id, uploaded_at
             FROM file_metadata WHERE id = $1`,
            [id]
        );
        if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
        res.json(rowToFile(r.rows[0]));
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: GET /files/${id}: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

app.delete('/files/:id', async (req: Request, res: Response) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id) || id <= 0) {
        return res.status(400).json({ error: 'invalid id' });
    }
    try {
        const r = await pool.query(`DELETE FROM file_metadata WHERE id = $1 RETURNING id`, [id]);
        if (r.rowCount === 0) return res.status(404).json({ error: 'not found' });
        res.json({ deleted: id });
    } catch (err: any) {
        console.error(`ERROR ${SERVICE}: DELETE /files/${id}: ${err?.message || err}`);
        res.status(503).json({ error: 'db error' });
    }
});

initDb().finally(() => {
    app.listen(8080, '0.0.0.0', () => {
        console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
    });
});
