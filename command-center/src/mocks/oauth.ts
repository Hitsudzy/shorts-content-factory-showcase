// Подставные «Токены, OAuth и данные API» (CC-0028 фабрики, договор 0.28.0, 0.42.0; экран — CC-0029).
// Общий для Vitest (MSW, src/mocks/handlers.ts), Playwright (tests/e2e/fixtures.ts) и тренировки
// (src/training/demo.ts). Данные — ./oauthData. Чтения: токен (`state.token` — вариант из
// `tokenOf`; значения токена нет нигде), данные API (`held` — всё, что хранится, `due` — что удалил
// бы авто-прогон: отметка отзыва старше `purge_after_days` и строки, не обновлявшиеся
// `stale_days`), сухой прогон отзыва (строки `api_data.py revoke` без `--yes`,
// `result` — тот же прогон данными; `confirm_available` — `revokeOff` выключает с причиной). Записи
// (CC-0087): отозвать — `…/revoke/plan` (нечего отзывать или `revokeOff` — `ok: false` без токена) и
// `…/revoke {confirm}` (`googleAnswer` — что ответит Google: `unreachable` — `ok: false`, ничего не
// изменилось; иначе файл токена удалён, данные API удалены, строка в журнале удалений); удалить по
// сроку — `…/api-data/auto/plan` (что подлежит авто-удалению: `due`) и `…/api-data/auto {confirm}`.
// И удалить данные API: `…/purge/plan {scope, channels}` (неизвестный канал — 404, пустой список —
// 422, удалять нечего — `ok: false` без токена), `…/purge {confirm}` — токен сгорает при любом
// исходе, кроме `busy`; план считается заново (`check_changed`, опустело — `refused`), удалённое
// уходит из `held`, токен YouTube остаётся. Ручки теста: `refuse` (чтение → 500
// `factory_broken`), `configBroken` (токен и отзыв → 409 `config_broken`, у данных API —
// `config_error`), `next` (исход следующего «да»), `readOnly` (каждый POST — 409
// `not_working_factory`), `life`, `calls`, `written`. Импорты — относительные.
import type { components } from '../api/schema.gen';
import {
  CHANNELS,
  HELD,
  OAUTH_NOW,
  REVOCATION,
  RULES,
  STALE,
  STATE_FILE,
  TOKEN_FILE,
  tokenOf,
  UNREFRESHED,
  type Held,
  type TokenVariant,
} from './oauthData';

type S = components['schemas'];
type Code = S['OAuthProblem']['code'] | 'not_working_factory';

export type OAuthReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: Code; details: string[] } };

export type OAuthPart = 'token' | 'api-data' | 'revoke';
export type PurgeOutcome = 'check_changed' | 'refused' | 'busy' | 'factory_broken';

class Fault extends Error {
  readonly status: 404 | 409 | 422 | 500;
  readonly code: Code;
  readonly details: string[];
  constructor(status: 404 | 409 | 422 | 500, code: Code, message: string, details: string[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const fault = (e: Fault): OAuthReply => ({
  status: e.status,
  body: { message: e.message, code: e.code, details: e.details },
});

const deep = <T>(x: T): T => structuredClone(x);
const PURGE_REASON = "owner's request (III.E.4.g)";
const REVOKED_REASON = 'revoked from the client';
const GOOGLE_PAGE = 'https://myaccount.google.com/permissions';
const STALE_REASON = `not refreshed for ${RULES.stale_days}+ days`;
const JOURNAL = 'publish/uploads.json';
const LOG = 'publish/api-data-deletions.jsonl';
const SCRUBBED = '[id удалён по политике YouTube API, CF-0618]';

/** `api_data.describe`: строки, которые читает человек. */
function describe(p: Omit<S['ApiDataPlan'], 'lines'>, dirs: Held['dirs']): string[] {
  const n = new Map(dirs.map((d) => [d.path, d.n]));
  return [
    ...p.files.map((f) => `  file  ${f}`),
    ...p.dirs.map((d) => `  dir   ${d}/ (${n.get(d) ?? 0} file(s))`),
    ...p.rows.map(
      (r) =>
        `  row   ${JOURNAL}: ${r.channel} ${r.slug} ${r.video_id} (source api) -> API fields deleted, the rest kept in \`api_data_deleted\``,
    ),
    ...p.texts.map((t) => `  text  ${t.file}: ${t.video_id} -> ${SCRUBBED}`),
  ];
}

const dayOf = (iso: string) => iso.slice(0, 10);

export function createOAuthBackend() {
  const tokens = new Map<string, { channels: string[] | null; fp: string; expires: number }>();
  let n = 0;
  const state = {
    now: OAUTH_NOW,
    /** Вариант токена (`tokenOf`). */
    token: 'ok' as TokenVariant,
    held: deep(HELD),
    stale: [...STALE],
    unrefreshed: [...UNREFRESHED],
    /** Отметка отзыва (Google отказал токену); `null` — отзыва нет. */
    revocation: null as S['ApiDataRevocation'] | null,
    /** Настройки публикатора не читаются. */
    configBroken: false,
    /** Сломанные чтения: часть → 500 `factory_broken`. */
    refuse: {} as Partial<Record<OAuthPart, true>>,
    /** Исход следующего «да» (одноразово). */
    next: null as PurgeOutcome | null,
    /** API не на рабочей фабрике: каждый POST — 409 `not_working_factory`. */
    readOnly: false,
    /** Срок жизни токена подтверждения, секунд (у фабрики — 120). */
    life: 120,
    /** Каждый запрос: «МЕТОД путь». */
    calls: [] as string[],
    /** Строки журнала удалений, записанные из центра. */
    written: [] as Record<string, unknown>[],
    /** Фабрика не отзывает из центра: причина (`confirm_available: false`, план — `ok: false`). */
    revokeOff: null as string | null,
    /** Что ответит Google на следующий отзыв. */
    googleAnswer: 'revoked' as 'revoked' | 'invalid_token' | 'unreachable',
  };
  const revokes = new Map<string, { fp: string; expires: number; kind: 'revoke' | 'auto' }>();

  const allDirs = () => Object.values(state.held).flatMap((h) => h.dirs);

  /** `api_data.plan`: каналы (`null` — все), или явные строки журнала (правило «устарело»). */
  function planOf(
    channels: readonly string[] | null,
    reason: string,
    onlyRows?: readonly string[],
  ): S['ApiDataPlan'] {
    const chans = channels ?? Object.keys(state.held);
    const files: string[] = [];
    const dirs: string[] = [];
    const rows: S['ApiDataRow'][] = [];
    const texts: S['ApiDataText'][] = [];
    for (const ch of chans) {
      const h = state.held[ch];
      if (!h) continue;
      const take = onlyRows ? h.rows.filter((r) => onlyRows.includes(r.entry_id ?? '')) : h.rows;
      if (!onlyRows) {
        files.push(...h.files);
        dirs.push(...h.dirs.map((d) => d.path));
      }
      rows.push(...take);
      const ids = new Set(take.map((r) => r.video_id));
      texts.push(...h.texts.filter((t) => ids.has(t.video_id)));
    }
    const named = new Set([
      ...rows.map((r) => r.channel ?? ''),
      ...[...files, ...dirs].map((p) => p.split('/')[1] ?? ''),
    ]);
    const p = {
      reason,
      channels: [...named].filter(Boolean).sort(),
      empty: !(files.length || dirs.length || rows.length || texts.length),
      files,
      dirs,
      rows,
      texts,
      journal: JOURNAL,
    };
    return { ...p, lines: describe(p, allDirs()) };
  }

  const broken = (part: OAuthPart) => {
    if (!state.refuse[part]) return;
    const what = {
      token: 'состояние токена не прочитано',
      'api-data': 'API Data не прочитаны',
      revoke: 'план отзыва не составлен',
    }[part];
    throw new Fault(500, 'factory_broken', `Фабрика ответила ошибкой: ${what}.`, [
      `PermissionError: [Errno 13] Permission denied: '${STATE_FILE}'`,
    ]);
  };

  const CONFIG = 'PUBLISHER_OAUTH_MODE=prod: one of testing, production';
  const config = () => {
    if (state.configBroken)
      throw new Fault(409, 'config_broken', `Конфигурация публикатора не читается: ${CONFIG}`, [
        `ConfigError: ${CONFIG}`,
      ]);
  };

  function token(): OAuthReply {
    broken('token');
    config();
    const t = tokenOf(state.token);
    if (state.revocation && t.state)
      t.state = { ...t.state, invalid_grant_at: state.revocation.revoked_at };
    return { status: 200, body: { ...t, now: state.now } satisfies S['OAuthToken'] };
  }

  const apiRows = () => Object.values(state.held).flatMap((h) => h.rows);

  function line(): { kind: S['ApiDataState']['kind']; line: string } {
    const rev = state.configBroken ? null : state.revocation;
    if (rev) {
      if (rev.deleted)
        return {
          kind: 'warn',
          line: `API Data удалены ${String(rev.deleted.at ?? '').slice(0, 10)} после отзыва доступа ${dayOf(rev.revoked_at)} (III.D.2.b); сбор метрик стоит до переразрешения`,
        };
      return {
        kind: 'bad',
        line: `API Data: Google отказал токену ${dayOf(rev.revoked_at)} (invalid_grant: отозван или истёк) - метрики Analytics и API-поля журнала будут удалены ${dayOf(rev.due_at)} (предел политики ${dayOf(rev.deadline)}); переразрешение снимает отметку`,
      };
    }
    const rows = apiRows();
    const stale = rows.filter((r) => state.unrefreshed.includes(r.entry_id ?? '')).length;
    const tail = stale
      ? `; ${stale} не обновлялись ${RULES.refresh_days}+ дн. (videos.list в metrics.py collect, удаление на ${RULES.stale_days}-й день)`
      : '';
    return {
      kind: stale ? 'warn' : 'ok',
      line: `API Data: отзыва доступа нет; журнал - ${rows.length} строк(и) API-пути${tail}`,
    };
  }

  function due(): S['ApiDataPlan'][] {
    const out: S['ApiDataPlan'][] = [];
    const rev = state.configBroken ? null : state.revocation;
    if (rev && Date.parse(state.now) >= Date.parse(rev.due_at)) {
      const p = planOf(null, `revoked ${rev.revoked_at}`);
      if (!p.empty) out.push(p);
    }
    const stale = apiRows().filter((r) => state.stale.includes(r.entry_id ?? ''));
    if (stale.length)
      out.push(
        planOf(
          null,
          STALE_REASON,
          stale.map((r) => r.entry_id ?? ''),
        ),
      );
    return out;
  }

  function apiData(): OAuthReply {
    broken('api-data');
    return {
      status: 200,
      body: {
        ...line(),
        now: state.now,
        config_error: state.configBroken ? `Конфигурация публикатора не читается: ${CONFIG}` : null,
        revocation: state.configBroken ? null : deep(state.revocation),
        rules: { ...RULES },
        held: planOf(null, PURGE_REASON),
        due: due(),
        log: LOG,
      } satisfies S['ApiDataState'],
    };
  }

  function revoke(): OAuthReply {
    broken('revoke');
    config();
    const t = tokenOf(state.token);
    const p = planOf(null, REVOKED_REASON);
    const lines = [
      'revoke - dry run (add --yes):',
      t.token_present
        ? `  google  POST https://oauth2.googleapis.com/revoke (refresh token of ${TOKEN_FILE})`
        : `  google  nothing to revoke: no token file (${TOKEN_FILE}) - the API Data is deleted all the same`,
      ...(t.token_present ? [`  token   ${TOKEN_FILE} -> deleted`] : []),
      `  state   ${STATE_FILE}: the revocation mark (revoked_from_client_at), api_data_deleted`,
      `  log     ${LOG}: reason \`${REVOKED_REASON}\``,
      p.lines.length
        ? `${REVOKED_REASON}: ${p.lines.length} item(s) would be deleted (dry run - add --yes)`
        : `${REVOKED_REASON}: nothing to delete`,
      ...p.lines,
    ];
    return {
      status: 200,
      body: {
        dry_run: true,
        lines,
        token_present: t.token_present,
        result: outcome(p, null),
        plan: p,
        google_page: GOOGLE_PAGE,
        // `revokeOff` — фабрика без отзыва из центра (контракт знает только `true`).
        confirm_available: (state.revokeOff === null) as true,
      } satisfies S['OAuthRevokePreview'],
    };
  }

  const guard = () => {
    if (state.readOnly)
      throw new Fault(
        409,
        'not_working_factory',
        'Только смотреть: рабочая копия на ветке cc-api, а не main',
        ['CC_API_WRITES is off'],
      );
  };

  const fingerprint = (p: S['ApiDataPlan']) => JSON.stringify([p.channels, p.reason, p.lines]);

  /** `_channels`: `null` — все; иначе известные каналы без повторов. */
  function channelsOf(scope: unknown, names: unknown): string[] | null {
    if (scope === 'all') return null;
    const got: string[] = [];
    for (const raw of Array.isArray(names) ? names : []) {
      const name = String(raw);
      if (!(CHANNELS as readonly string[]).includes(name))
        throw new Fault(404, 'unknown_channel', `Канала «${name}» нет в фабрике.`, [
          `no channels/${name}.json under /factory`,
        ]);
      if (!got.includes(name)) got.push(name);
    }
    if (!got.length)
      throw new Fault(
        422,
        'no_channels',
        'Назовите каналы, API Data которых удалить, или выберите «все каналы».',
        ['scope channels with an empty list'],
      );
    return got;
  }

  function purgePlan(raw: unknown): OAuthReply {
    guard();
    const b = (raw ?? {}) as { scope?: unknown; channels?: unknown };
    const scope = b.scope === 'channels' ? 'channels' : 'all';
    const chans = channelsOf(scope, b.channels);
    const p = planOf(chans, PURGE_REASON);
    const ok = !p.empty;
    let confirm: string | null = null;
    const fp = fingerprint(p);
    if (ok) {
      confirm = `oauth-${++n}`;
      tokens.set(confirm, { channels: chans, fp, expires: Date.now() + state.life * 1000 });
    }
    return {
      status: 200,
      body: {
        action: 'api_data_purge',
        ok,
        why: ok ? null : 'Удалять нечего: API Data этих каналов нет.',
        scope,
        asked: chans,
        plan: p,
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: ok ? state.life : null,
      } satisfies S['ApiDataPurgePlan'],
    };
  }

  function purge(raw: unknown): OAuthReply {
    guard();
    const next = state.next;
    state.next = null;
    if (next === 'busy')
      throw new Fault(
        409,
        'busy',
        'Идёт другая запись публикации - подождите и запросите план заново.',
        ['the publication write lock was not free in 5 s; the token is not spent'],
      );
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = tokens.get(token);
    tokens.delete(token);
    if (!got)
      throw new Fault(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план удаления API Data заново.',
        ['no such confirm token in this API process (used, unknown, or the server restarted)'],
      );
    if (got.expires <= Date.now())
      throw new Fault(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план удаления API Data заново.',
        ['expired'],
      );
    if (next === 'refused')
      for (const ch of got.channels ?? Object.keys(state.held))
        if (state.held[ch]) state.held[ch] = { files: [], dirs: [], rows: [], texts: [] };
    const p = planOf(got.channels, PURGE_REASON);
    if (next === 'check_changed' || next === 'refused' || fingerprint(p) !== got.fp) {
      if (p.empty)
        throw new Fault(409, 'refused', 'Удалять уже нечего: API Data этих каналов нет.', [
          'the plan is empty now',
        ]);
      throw new Fault(
        409,
        'check_changed',
        'API Data изменились с момента плана - ничего не удалено; посмотрите план заново.',
        ["the fingerprint of the api_data_purge plan differs from the plan's"],
      );
    }
    if (next === 'factory_broken')
      throw new Fault(
        500,
        'factory_broken',
        'Фабрика ответила ошибкой посреди удаления - посмотрите publish/ и analytics/, прежде чем повторять.',
        ['OSError: [Errno 28] No space left on device'],
      );
    for (const ch of p.channels)
      if (state.held[ch]) state.held[ch] = { files: [], dirs: [], rows: [], texts: [] };
    const record = {
      at: state.now,
      reason: p.reason,
      channels: p.channels,
      files: p.files,
      dirs: p.dirs,
      entries: p.rows.map((r) => r.entry_id),
      texts: p.texts.map((t) => t.file),
      by: 'user',
      via: 'center',
    };
    state.written.push(record);
    return {
      status: 200,
      body: {
        action: 'api_data_purge',
        written: true,
        by: 'user',
        via: 'center',
        plan: p,
        record,
        log: LOG,
      } satisfies S['ApiDataPurgeResult'],
    };
  }

  /** `revoke_result`: сухой (`answer === null`) или после ответа Google. */
  function outcome(
    p: S['ApiDataPlan'],
    answer: 'revoked' | 'invalid_token' | 'unreachable' | 'no token' | null,
    deletion: Record<string, unknown> | null = null,
  ): S['OAuthRevokeOutcome'] {
    const t = tokenOf(state.token);
    const dry = answer === null;
    const ok = answer !== 'unreachable';
    return {
      dry_run: dry,
      ok,
      exit: ok ? 0 : 1,
      by: 'user',
      via: 'center',
      google: {
        answer,
        detail:
          answer === 'unreachable'
            ? 'URLError: <urlopen error [Errno 8] nodename nor servname provided>'
            : answer === 'revoked'
              ? 'HTTP 200'
              : answer === 'invalid_token'
                ? 'HTTP 400 invalid_token'
                : null,
        url: 'https://oauth2.googleapis.com/revoke',
      },
      token: {
        file: '.../youtube.oauth-token.json',
        kind: t.token_present ? 'refresh token' : null,
        missing: t.token_present ? null : 'no token file',
        existed: t.token_present,
        deleted: !dry && ok && t.token_present,
      },
      state_file: '.../youtube.oauth-token.state.json',
      log: LOG,
      reason: REVOKED_REASON,
      channels: [...p.channels],
      items: [...p.lines],
      deletion,
    };
  }

  const revokeFp = (p: S['ApiDataPlan']) =>
    JSON.stringify([tokenOf(state.token).token_present, fingerprint(p)]);

  function revokePlan(): OAuthReply {
    guard();
    broken('revoke');
    config();
    const t = tokenOf(state.token);
    const p = planOf(null, REVOKED_REASON);
    const why =
      state.revokeOff ??
      (!t.token_present && p.empty ? 'Отзывать нечего: токена нет и данных API нет.' : null);
    const ok = why === null;
    const fp = revokeFp(p);
    let confirm: string | null = null;
    if (ok) {
      confirm = `oauth-${++n}`;
      revokes.set(confirm, { fp, expires: Date.now() + state.life * 1000, kind: 'revoke' });
    }
    return {
      status: 200,
      body: {
        action: 'oauth_revoke',
        ok,
        why,
        result: outcome(p, null),
        plan: p,
        google_page: GOOGLE_PAGE,
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: ok ? state.life : null,
      } satisfies S['OAuthRevokePlan'],
    };
  }

  /** Токен подтверждения отзыва / «по сроку» или отказ. */
  function spend(raw: unknown, kind: 'revoke' | 'auto') {
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = revokes.get(token);
    revokes.delete(token);
    if (!got)
      throw new Fault(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план заново.',
        ['no such confirm token in this API process (used, unknown, or the server restarted)'],
      );
    if (got.kind !== kind)
      throw new Fault(409, 'confirm_mismatch', 'Подтверждение выдано другому действию.', [
        `the token is of ${got.kind}`,
      ]);
    if (got.expires <= Date.now())
      throw new Fault(409, 'confirm_expired', 'Подтверждение устарело (живёт 120 с).', ['expired']);
    return got;
  }

  function revokeDo(raw: unknown): OAuthReply {
    guard();
    const got = spend(raw, 'revoke');
    const p = planOf(null, REVOKED_REASON);
    if (revokeFp(p) !== got.fp)
      throw new Fault(
        409,
        'check_changed',
        'Токен или данные API изменились с момента плана — ничего не отозвано; посмотрите план заново.',
        ["the fingerprint of the oauth_revoke plan differs from the plan's"],
      );
    const t = tokenOf(state.token);
    const answer = !t.token_present ? 'no token' : state.googleAnswer;
    if (answer === 'unreachable')
      return {
        status: 200,
        body: {
          action: 'oauth_revoke',
          ok: false,
          written: false,
          why: 'Google не ответил — ничего не изменилось, токен на месте.',
          by: 'user',
          via: 'center',
          result: outcome(p, 'unreachable'),
          plan: p,
          google_page: GOOGLE_PAGE,
          log: LOG,
        } satisfies S['OAuthRevokeResult'],
      };
    const deletion = {
      at: state.now,
      reason: REVOKED_REASON,
      google: answer,
      channels: p.channels,
      items: p.lines.length,
      by: 'user',
      via: 'center',
    };
    const res = outcome(p, answer, deletion);
    for (const ch of Object.keys(state.held))
      state.held[ch] = { files: [], dirs: [], rows: [], texts: [] };
    state.token = 'no-auth';
    state.written.push(deletion);
    return {
      status: 200,
      body: {
        action: 'oauth_revoke',
        ok: true,
        written: true,
        why: null,
        by: 'user',
        via: 'center',
        result: res,
        plan: p,
        google_page: GOOGLE_PAGE,
        log: LOG,
      } satisfies S['OAuthRevokeResult'],
    };
  }

  const autoFp = (d: S['ApiDataPlan'][]) => JSON.stringify(d.map(fingerprint));

  function autoPlan(): OAuthReply {
    guard();
    const d = due();
    const ok = d.length > 0;
    const fp = autoFp(d);
    let confirm: string | null = null;
    if (ok) {
      confirm = `oauth-${++n}`;
      revokes.set(confirm, { fp, expires: Date.now() + state.life * 1000, kind: 'auto' });
    }
    return {
      status: 200,
      body: {
        action: 'api_data_auto',
        ok,
        why: ok ? null : 'По сроку удалять нечего: срок ничего не вышел.',
        due: d,
        revocation: state.configBroken ? null : deep(state.revocation),
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: ok ? state.life : null,
      } satisfies S['ApiDataAutoPlan'],
    };
  }

  function autoDo(raw: unknown): OAuthReply {
    guard();
    const got = spend(raw, 'auto');
    const d = due();
    if (autoFp(d) !== got.fp)
      throw new Fault(
        409,
        'check_changed',
        'Что подлежит удалению по сроку, изменилось с момента плана — ничего не удалено; посмотрите план заново.',
        ["the fingerprint of the api_data_auto plan differs from the plan's"],
      );
    const done = d.map((p) => {
      const record = {
        at: state.now,
        reason: p.reason,
        channels: p.channels,
        entries: p.rows.map((r) => r.entry_id),
        by: 'user',
        via: 'center',
      };
      state.written.push(record);
      return { plan: p, record };
    });
    for (const p of d) {
      const whole = p.reason.startsWith('revoked');
      const gone = new Set(p.rows.map((r) => r.entry_id));
      for (const ch of Object.keys(state.held)) {
        const h = state.held[ch]!;
        if (whole) state.held[ch] = { files: [], dirs: [], rows: [], texts: [] };
        else h.rows = h.rows.filter((r) => !gone.has(r.entry_id));
      }
      if (!whole) state.stale = state.stale.filter((x) => !gone.has(x));
    }
    if (state.revocation && d.some((p) => p.reason.startsWith('revoked')))
      state.revocation = {
        ...state.revocation,
        deleted: { at: state.now, by: 'user', via: 'center' },
      };
    return {
      status: 200,
      body: {
        action: 'api_data_auto',
        written: true,
        by: 'user',
        via: 'center',
        done,
        revocation: deep(state.revocation),
        log: LOG,
      } satisfies S['ApiDataAutoResult'],
    };
  }

  /** Все выданные токены устарели (как будто прошло 120 с) — «да» получит `confirm_expired`. */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
    for (const t of revokes.values()) t.expires = 0;
  };

  /** Отметка отзыва (Google отказал токену) — данные API станут «к удалению». */
  const markRevoked = (r: S['ApiDataRevocation'] = REVOCATION) => {
    state.revocation = deep(r);
  };

  /** Данных API нет вовсе. */
  const empty = () => {
    for (const ch of Object.keys(state.held))
      state.held[ch] = { files: [], dirs: [], rows: [], texts: [] };
  };

  return {
    state,
    token,
    apiData,
    revoke,
    purgePlan,
    purge,
    revokePlan,
    revokeDo,
    autoPlan,
    autoDo,
    expireTokens,
    markRevoked,
    empty,
  };
}

export type OAuthBackend = ReturnType<typeof createOAuthBackend>;

/** Ответ на запрос к API токенов или `null`, если запрос не к нему. */
export function routeOAuth(
  backend: OAuthBackend,
  method: string,
  url: URL,
  body: unknown,
): OAuthReply | null {
  const m = url.pathname.match(
    /\/api\/oauth\/(token|api-data|revoke|revoke\/plan|api-data\/(?:purge|auto)(?:\/plan)?)$/,
  );
  if (!m) return null;
  backend.state.calls.push(`${method} ${url.pathname}`);
  try {
    const what = m[1];
    if (method === 'GET') {
      if (what === 'token') return backend.token();
      if (what === 'api-data') return backend.apiData();
      if (what === 'revoke') return backend.revoke();
      return null;
    }
    if (method === 'POST') {
      if (what === 'api-data/purge/plan') return backend.purgePlan(body);
      if (what === 'api-data/purge') return backend.purge(body);
      if (what === 'revoke/plan') return backend.revokePlan();
      if (what === 'revoke') return backend.revokeDo(body);
      if (what === 'api-data/auto/plan') return backend.autoPlan();
      if (what === 'api-data/auto') return backend.autoDo(body);
    }
    return null;
  } catch (e) {
    if (e instanceof Fault) return fault(e);
    throw e;
  }
}
