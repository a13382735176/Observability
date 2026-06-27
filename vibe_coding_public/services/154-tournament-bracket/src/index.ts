import Fastify from 'fastify';
import { Pool } from 'pg';

const SERVICE = 'tournament-bracket';
const PG_DSN = process.env.PG_DSN || 'postgres://vibe:vibe@postgres:5432/vibe';

const app = Fastify({ logger: false });

const pool = new Pool({
  connectionString: PG_DSN,
  connectionTimeoutMillis: 2000,
  statement_timeout: 2000,
  query_timeout: 2000,
  max: 4,
});
pool.on('error', (err: any) => console.error(`${SERVICE}: pg pool error: ${err.message || err}`));

async function init() {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS tournaments(
        id bigserial PRIMARY KEY,
        name text,
        max_players int,
        status text DEFAULT 'open',
        created_at timestamptz DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS tournament_players(
        id bigserial PRIMARY KEY,
        tournament_id bigint,
        user_id text,
        joined_at timestamptz DEFAULT now()
      )
    `);
    await pool.query(`
      CREATE TABLE IF NOT EXISTS bracket_matches(
        id bigserial PRIMARY KEY,
        tournament_id bigint,
        round int,
        player1 text,
        player2 text,
        winner text
      )
    `);
    console.log(`${SERVICE}: postgres ready`);
  } catch (e: any) {
    console.error(`${SERVICE}: postgres init failed: ${e.message || e}`);
  }
}

app.get('/healthz', async () => ({ status: 'ok', service: SERVICE }));

app.post('/tournaments', async (req: any, reply) => {
  try {
    const { name, max_players } = req.body || {};
    if (!name || typeof max_players !== 'number') {
      return reply.code(400).send({ error: 'name and max_players required' });
    }
    const r = await pool.query(
      'INSERT INTO tournaments(name, max_players) VALUES($1, $2) RETURNING id, name, max_players, status, created_at',
      [name, max_players]
    );
    return reply.code(201).send(r.rows[0]);
  } catch (e: any) {
    console.error(`${SERVICE}: POST /tournaments: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.post('/tournaments/:id/register', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const { user_id } = req.body || {};
    if (!user_id) return reply.code(400).send({ error: 'user_id required' });

    const t = await pool.query('SELECT max_players FROM tournaments WHERE id=$1', [id]);
    if (t.rowCount === 0) return reply.code(404).send({ error: 'tournament not found' });
    const maxPlayers = t.rows[0].max_players;

    const c = await pool.query('SELECT count(*)::int AS c FROM tournament_players WHERE tournament_id=$1', [id]);
    if (c.rows[0].c >= maxPlayers) {
      return reply.code(409).send({ error: 'tournament full' });
    }

    const r = await pool.query(
      'INSERT INTO tournament_players(tournament_id, user_id) VALUES($1, $2) RETURNING id, tournament_id, user_id, joined_at',
      [id, String(user_id)]
    );
    return reply.code(201).send(r.rows[0]);
  } catch (e: any) {
    console.error(`${SERVICE}: POST /tournaments/:id/register: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.post('/tournaments/:id/bracket', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const t = await pool.query('SELECT id FROM tournaments WHERE id=$1', [id]);
    if (t.rowCount === 0) return reply.code(404).send({ error: 'tournament not found' });

    const p = await pool.query(
      'SELECT user_id FROM tournament_players WHERE tournament_id=$1 ORDER BY id',
      [id]
    );
    const players: string[] = p.rows.map((r: any) => r.user_id);
    if (players.length < 2) {
      return reply.code(400).send({ error: 'not enough players' });
    }

    const matches: any[] = [];
    for (let i = 0; i + 1 < players.length; i += 2) {
      const r = await pool.query(
        'INSERT INTO bracket_matches(tournament_id, round, player1, player2) VALUES($1, 1, $2, $3) RETURNING id, tournament_id, round, player1, player2, winner',
        [id, players[i], players[i + 1]]
      );
      matches.push(r.rows[0]);
    }
    return reply.code(201).send({ tournament_id: Number(id), round: 1, matches });
  } catch (e: any) {
    console.error(`${SERVICE}: POST /tournaments/:id/bracket: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.post('/matches/:match_id/result', async (req: any, reply) => {
  try {
    const matchId = req.params.match_id;
    const { winner_user_id } = req.body || {};
    if (!winner_user_id) return reply.code(400).send({ error: 'winner_user_id required' });

    const upd = await pool.query(
      'UPDATE bracket_matches SET winner=$1 WHERE id=$2 RETURNING id, tournament_id, round, player1, player2, winner',
      [String(winner_user_id), matchId]
    );
    if (upd.rowCount === 0) return reply.code(404).send({ error: 'match not found' });
    const match = upd.rows[0];
    const tournamentId = match.tournament_id;
    const currentRound = match.round;

    const unresolved = await pool.query(
      'SELECT count(*)::int AS c FROM bracket_matches WHERE tournament_id=$1 AND round=$2 AND winner IS NULL',
      [tournamentId, currentRound]
    );

    let nextRoundMatches: any[] = [];
    if (unresolved.rows[0].c === 0) {
      const winners = await pool.query(
        'SELECT winner FROM bracket_matches WHERE tournament_id=$1 AND round=$2 ORDER BY id',
        [tournamentId, currentRound]
      );
      const ws: string[] = winners.rows.map((r: any) => r.winner);
      if (ws.length >= 2) {
        const nextRound = currentRound + 1;
        for (let i = 0; i + 1 < ws.length; i += 2) {
          const r = await pool.query(
            'INSERT INTO bracket_matches(tournament_id, round, player1, player2) VALUES($1, $2, $3, $4) RETURNING id, tournament_id, round, player1, player2, winner',
            [tournamentId, nextRound, ws[i], ws[i + 1]]
          );
          nextRoundMatches.push(r.rows[0]);
        }
      }
    }
    return reply.send({ match, next_round_matches: nextRoundMatches });
  } catch (e: any) {
    console.error(`${SERVICE}: POST /matches/:match_id/result: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

app.get('/tournaments/:id', async (req: any, reply) => {
  try {
    const id = req.params.id;
    const t = await pool.query(
      'SELECT id, name, max_players, status, created_at FROM tournaments WHERE id=$1',
      [id]
    );
    if (t.rowCount === 0) return reply.code(404).send({ error: 'not found' });

    const p = await pool.query(
      'SELECT id, user_id, joined_at FROM tournament_players WHERE tournament_id=$1 ORDER BY id',
      [id]
    );
    const m = await pool.query(
      'SELECT id, round, player1, player2, winner FROM bracket_matches WHERE tournament_id=$1 ORDER BY round, id',
      [id]
    );

    const rounds: Record<string, any[]> = {};
    for (const row of m.rows) {
      const k = String(row.round);
      if (!rounds[k]) rounds[k] = [];
      rounds[k].push(row);
    }

    return reply.send({
      tournament: t.rows[0],
      players: p.rows,
      matches: rounds,
    });
  } catch (e: any) {
    console.error(`${SERVICE}: GET /tournaments/:id: ${e.message || e}`);
    return reply.code(503).send({ error: 'internal error' });
  }
});

init().finally(() => {
  app.listen({ host: '0.0.0.0', port: 8080 }).then(() => {
    console.log(`${SERVICE}: listening on 0.0.0.0:8080`);
  }).catch((e) => {
    console.error(`${SERVICE}: listen failed: ${e.message || e}`);
    process.exit(1);
  });
});
