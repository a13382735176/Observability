import express from 'express';
import { Pool } from 'pg';

const SERVICE = 'quiz-engine';
const log = {
  info:  (m: string) => console.log(`INFO  ${SERVICE} :: ${m}`),
  error: (m: string, e?: unknown) => console.error(`ERROR ${SERVICE} :: ${m}`, e ?? ''),
};

const pg = new Pool({
  connectionString: process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe',
  connectionTimeoutMillis: 2000,
});

const app = express();
app.use(express.json());

pg.query(`CREATE TABLE IF NOT EXISTS quizzes(
  id SERIAL PRIMARY KEY,
  title TEXT NOT NULL,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
)`).then(() => log.info('db init ok')).catch(e => log.error('db init failed', e));

app.get('/healthz', (_req, res) => res.json({ status: 'ok', service: SERVICE }));

app.post('/quizzes', async (req, res) => {
  const { title, questions } = req.body;
  try {
    const { rows } = await pg.query(
      'INSERT INTO quizzes(title,data) VALUES($1,$2::jsonb) RETURNING id,title,data,created_at',
      [title, JSON.stringify(questions)]);
    return res.status(201).json({ id: rows[0].id, title: rows[0].title, questions: rows[0].data });
  } catch (e) { log.error('POST /quizzes', e); return res.status(500).json({ error: 'internal error' }); }
});

app.get('/quizzes/:id', async (req, res) => {
  try {
    const { rows } = await pg.query('SELECT id,title,data,created_at FROM quizzes WHERE id=$1', [req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'not found' });
    const quiz = rows[0];
    // strip answer_idx before returning
    const questions = (quiz.data as any[]).map(q => ({ q: q.q, choices: q.choices }));
    return res.json({ id: quiz.id, title: quiz.title, questions, created_at: quiz.created_at });
  } catch (e) { log.error('GET /quizzes/:id', e); return res.status(500).json({ error: 'internal error' }); }
});

app.post('/quizzes/:id/submit', async (req, res) => {
  const { answers } = req.body as { answers: number[] };
  try {
    const { rows } = await pg.query('SELECT data FROM quizzes WHERE id=$1', [req.params.id]);
    if (!rows[0]) return res.status(404).json({ error: 'not found' });
    const questions = rows[0].data as any[];
    let score = 0;
    questions.forEach((q, i) => { if (answers[i] === q.answer_idx) score++; });
    return res.json({ quiz_id: parseInt(req.params.id), score, total: questions.length });
  } catch (e) { log.error('POST /quizzes/:id/submit', e); return res.status(500).json({ error: 'internal error' }); }
});

app.listen(8080, '0.0.0.0', () => log.info('listening on :8080'));
