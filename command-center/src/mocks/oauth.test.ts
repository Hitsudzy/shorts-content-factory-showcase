import { createOAuthBackend, routeOAuth } from './oauth';

const at = (p: string) => new URL(`http://x${p}`);
type B = ReturnType<typeof createOAuthBackend>;
const get = (b: B, p: string) => routeOAuth(b, 'GET', at(p), null);
const post = (b: B, p: string, body: unknown) => routeOAuth(b, 'POST', at(p), body);
type Plan = {
  ok: boolean;
  confirm: string | null;
  why: string | null;
  plan: { channels: string[]; empty: boolean; lines: string[]; files: string[] };
};

describe('подставные токен, OAuth и данные API', () => {
  it('токен: шесть состояний, в ответе нет значения токена', () => {
    const b = createOAuthBackend();
    const ok = get(b, '/api/oauth/token')!.body as Record<string, unknown>;
    expect(ok).toMatchObject({ kind: 'ok', code: 0, hours_left: 96, token_present: true });
    const text = JSON.stringify(ok);
    expect(text).not.toMatch(/refresh_token|client_secret"|access_token|ya29\./);
    for (const [v, kind, code] of [
      ['expires-soon', 'expires-soon', 1],
      ['expired', 'expired', 3],
      ['no-auth', 'no-auth', 3],
      ['no-scope', 'no-scope', 3],
      ['unknown-expiry', 'unknown-expiry', 3],
      ['production', 'ok', 0],
    ] as const) {
      b.state.token = v;
      expect(get(b, '/api/oauth/token')!.body).toMatchObject({ kind, code });
    }
    b.state.token = 'no-scope';
    expect(get(b, '/api/oauth/token')!.body).toMatchObject({
      scopes: { missing: ['https://www.googleapis.com/auth/yt-analytics.readonly'] },
    });
  });

  it('данные API: что хранится, строка фабрики, авто-прогон удалил бы устаревшую строку', () => {
    const b = createOAuthBackend();
    const d = get(b, '/api/oauth/api-data')!.body as {
      kind: string;
      line: string;
      held: { channels: string[]; lines: string[] };
      due: { reason: string; rows: { slug: string }[] }[];
    };
    expect(d.kind).toBe('warn');
    expect(d.line).toMatch(/журнал - 3 строк\(и\) API-пути; 1 не обновлялись 7\+ дн/);
    expect(d.held.channels).toEqual(['example-film', 'example-tech']);
    expect(d.held.lines).toHaveLength(11);
    expect(d.due).toHaveLength(1);
    expect(d.due[0]!.reason).toBe('not refreshed for 28+ days');
    expect(d.due[0]!.rows.map((r) => r.slug)).toEqual(['delver']);
    b.markRevoked();
    expect(get(b, '/api/oauth/api-data')!.body).toMatchObject({
      kind: 'bad',
      revocation: { due_at: '2026-11-04T08:12:00Z' },
    });
  });

  it('отзыв — сухой прогон; подтверждение фабрика даёт (0.31.0), подставной его не делает', () => {
    const b = createOAuthBackend();
    const r = get(b, '/api/oauth/revoke')!.body as {
      dry_run: boolean;
      confirm_available: boolean;
      lines: string[];
    };
    expect(r.dry_run).toBe(true);
    expect(r.confirm_available).toBe(true);
    expect(r.lines[0]).toBe('revoke - dry run (add --yes):');
    expect(r.lines).toContain(
      'revoked from the client: 11 item(s) would be deleted (dry run - add --yes)',
    );
  });

  it('удаление: план с токеном → «да» удаляет, токен YouTube остаётся', () => {
    const b = createOAuthBackend();
    const p = post(b, '/api/oauth/api-data/purge/plan', {
      scope: 'channels',
      channels: ['example-tech'],
    })!.body as Plan;
    expect(p.ok).toBe(true);
    expect(p.plan.channels).toEqual(['example-tech']);
    expect(p.plan.lines).toHaveLength(3);
    const done = post(b, '/api/oauth/api-data/purge', { confirm: p.confirm });
    expect(done?.status).toBe(200);
    expect(done?.body).toMatchObject({ written: true, by: 'user', via: 'center' });
    expect(b.state.written).toHaveLength(1);
    const again = post(b, '/api/oauth/api-data/purge', { confirm: p.confirm });
    expect(again?.body).toMatchObject({ code: 'confirm_unknown' });
    const d = get(b, '/api/oauth/api-data')!.body as { held: { channels: string[] } };
    expect(d.held.channels).toEqual(['example-film']);
    expect(get(b, '/api/oauth/token')!.body).toMatchObject({ token_present: true });
  });

  it('удалять нечего — ok:false без токена; отказы плана', () => {
    const b = createOAuthBackend();
    const none = post(b, '/api/oauth/api-data/purge/plan', {
      scope: 'channels',
      channels: ['example-science'],
    })!.body as Plan;
    expect(none.ok).toBe(false);
    expect(none.confirm).toBeNull();
    expect(none.why).toMatch(/Удалять нечего/);
    expect(
      post(b, '/api/oauth/api-data/purge/plan', { scope: 'channels', channels: ['nope'] }),
    ).toMatchObject({ status: 404, body: { code: 'unknown_channel' } });
    expect(
      post(b, '/api/oauth/api-data/purge/plan', { scope: 'channels', channels: [] }),
    ).toMatchObject({ status: 422, body: { code: 'no_channels' } });
    b.state.readOnly = true;
    expect(post(b, '/api/oauth/api-data/purge/plan', { scope: 'all' })).toMatchObject({
      status: 409,
      body: { code: 'not_working_factory' },
    });
  });

  it('исходы «да»: изменилось, опустело, занято (токен цел), сломалось, устарело', () => {
    const b = createOAuthBackend();
    const plan = () =>
      (post(b, '/api/oauth/api-data/purge/plan', { scope: 'all' })!.body as Plan).confirm;
    const yes = (confirm: string | null) => post(b, '/api/oauth/api-data/purge', { confirm });

    b.state.next = 'check_changed';
    expect(yes(plan())).toMatchObject({ status: 409, body: { code: 'check_changed' } });

    b.state.next = 'busy';
    const kept = plan();
    expect(yes(kept)).toMatchObject({ status: 409, body: { code: 'busy' } });
    b.state.next = 'factory_broken';
    expect(yes(kept)).toMatchObject({ status: 500, body: { code: 'factory_broken' } });

    const old = plan();
    b.expireTokens();
    expect(yes(old)).toMatchObject({ status: 409, body: { code: 'confirm_expired' } });

    b.state.next = 'refused';
    expect(yes(plan())).toMatchObject({ status: 409, body: { code: 'refused' } });
    expect(b.state.written).toHaveLength(0);
  });

  it('сломанные чтения и настройки', () => {
    const b = createOAuthBackend();
    b.state.refuse = { token: true };
    expect(get(b, '/api/oauth/token')).toMatchObject({
      status: 500,
      body: { code: 'factory_broken' },
    });
    b.state.refuse = {};
    b.state.configBroken = true;
    expect(get(b, '/api/oauth/token')).toMatchObject({
      status: 409,
      body: { code: 'config_broken' },
    });
    expect(get(b, '/api/oauth/revoke')).toMatchObject({ status: 409 });
    expect((get(b, '/api/oauth/api-data')!.body as { config_error: string }).config_error).toMatch(
      /не читается/,
    );
    expect(routeOAuth(b, 'GET', at('/api/notify/check'), null)).toBeNull();
  });
});
