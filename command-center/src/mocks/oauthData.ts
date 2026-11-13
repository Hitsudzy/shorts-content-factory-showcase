// Подставные данные «Токенов, OAuth и данных API» (CC-0028 фабрики, договор 0.28.0): шесть
// состояний токена, как их печатает `publisher_auth.py status` (строки — дословно по шаблонам
// фабрики; значения токена нет нигде, как и у API), и данные API фабрики по каналам: у Reel —
// метрики Analytics (три файла и сводка), две строки журнала с API-полями и id ролика в двух
// текстах; у Tech — два файла и одна строка; у Science — ничего. Одна строка Reel не обновлялась
// 30 дней — её удалил бы авто-прогон. Часы фабрики — `OAUTH_NOW` (12 октября 2026, 18:40 МСК).
// Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export const OAUTH_NOW = '2026-10-12T15:40:00Z';

export const CHANNELS = ['example-film', 'example-tech', 'example-science'] as const;

export const AUTHORIZE_COMMAND =
  'agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize';
const FIX = `\`${AUTHORIZE_COMMAND}\``;
// С договора 0.35.0 (CC-0097/0098 фабрики) абсолютных путей в ответах нет: домашний каталог — `~`,
// путь вне корня фабрики в полях — `.../<имя>`.
export const TOKEN_FILE = '~/.config/content-factory/publisher/youtube.oauth-token.json';
export const STATE_FILE = '~/.config/content-factory/publisher/youtube.oauth-token.state.json';

export const SCOPES = [
  'https://www.googleapis.com/auth/youtube.upload',
  'https://www.googleapis.com/auth/youtube.readonly',
  'https://www.googleapis.com/auth/yt-analytics.readonly',
] as const;
const SHORT = Object.fromEntries(SCOPES.map((s) => [s, s.split('/').pop()!]));
const SCOPE_LINE = SCOPES.map((s) => SHORT[s]).join(', ');

export const RULES: S['ApiDataRules'] = {
  retention_days: 30,
  purge_after_days: 25,
  refresh_days: 7,
  stale_days: 28,
};

export type TokenVariant =
  'ok' | 'production' | 'expires-soon' | 'expired' | 'no-auth' | 'no-scope' | 'unknown-expiry';

const AUTHORIZED = '2026-10-09T15:40:00Z';

const state = (over: Partial<S['OAuthState']> = {}): S['OAuthState'] => ({
  authorized_at: AUTHORIZED,
  expires_at: '2026-10-16T15:40:00Z',
  oauth_mode: 'testing',
  lifetime_days: 7,
  scopes: [...SCOPES],
  invalid_grant_at: null,
  revoked_from_client_at: null,
  revoked_from_client_google: null,
  api_data_deleted: null,
  ...over,
});

const base = (over: Partial<S['OAuthToken']>): S['OAuthToken'] => ({
  kind: 'ok',
  code: 0,
  line: '',
  now: OAUTH_NOW,
  expires_at: null,
  hours_left: null,
  oauth_mode: 'testing',
  token_mode: 'testing',
  lifetime_days: 7,
  remind_hours: 24,
  scopes: { required: [...SCOPES], granted: [...SCOPES], missing: [], short: { ...SHORT } },
  token_present: true,
  client_secret_present: true,
  state_present: true,
  state: state(),
  authorize_command: AUTHORIZE_COMMAND,
  ...over,
});

/** Состояние токена, как его отдаёт `GET /api/oauth/token` в этом варианте. */
export function tokenOf(v: TokenVariant): S['OAuthToken'] {
  switch (v) {
    case 'ok':
      return base({
        expires_at: '2026-10-16T15:40:00Z',
        hours_left: 96,
        line: `ok   oauth: токен YouTube действует ещё 96 ч, до 2026-10-16 18:40 МСК (scope: ${SCOPE_LINE}; режим Testing)`,
      });
    case 'production':
      return base({
        oauth_mode: 'production',
        token_mode: 'production',
        line:
          'ok   oauth: токен YouTube (приложение в Production) - без фиксированного срока: ' +
          'действует, пока доступ не отозван и пока токен используется (6 месяцев без ' +
          `использования - истекает) (scope: ${SCOPE_LINE})`,
        state: state({ expires_at: null, oauth_mode: 'production', lifetime_days: null }),
      });
    case 'expires-soon':
      return base({
        kind: 'expires-soon',
        code: 1,
        expires_at: '2026-10-13T11:40:00Z',
        hours_left: 20,
        line: `OAUTH EXPIRES SOON: токен YouTube истекает завтра 2026-10-13 14:40 МСК (через 20 ч) - переразрешите заранее (~30 с): ${FIX}`,
        state: state({ authorized_at: '2026-10-06T11:40:00Z', expires_at: '2026-10-13T11:40:00Z' }),
      });
    case 'expired':
      return base({
        kind: 'expired',
        code: 3,
        expires_at: '2026-10-11T09:00:00Z',
        hours_left: 0,
        line: `OAUTH EXPIRED: токен YouTube истёк 2026-10-11 12:00 МСК - загрузка и метрики стоят до переразрешения (~30 с): ${FIX}`,
        state: state({ authorized_at: '2026-10-04T09:00:00Z', expires_at: '2026-10-11T09:00:00Z' }),
      });
    case 'no-auth':
      return base({
        kind: 'no-auth',
        code: 3,
        token_mode: null,
        line: `OAUTH NO AUTH: нет токена YouTube (${TOKEN_FILE}) - разрешите доступ (~30 с, браузер): ${FIX}`,
        scopes: { required: [...SCOPES], granted: null, missing: [], short: { ...SHORT } },
        token_present: false,
        state_present: false,
        state: null,
      });
    case 'no-scope': {
      const granted = SCOPES.slice(0, 2);
      return base({
        kind: 'no-scope',
        code: 3,
        expires_at: '2026-10-16T15:40:00Z',
        line: `OAUTH NO SCOPE: у токена YouTube нет scope yt-analytics.readonly - переразрешите (одно разрешение выдаёт все scope, все галочки оставить): ${FIX}`,
        scopes: {
          required: [...SCOPES],
          granted: [...granted],
          missing: [SCOPES[2]],
          short: { ...SHORT },
        },
        state: state({ scopes: [...granted] }),
      });
    }
    case 'unknown-expiry':
      return base({
        kind: 'unknown-expiry',
        code: 3,
        token_mode: null,
        line: `OAUTH UNKNOWN EXPIRY: срок токена YouTube неизвестен (выдан до CF-0589, нет youtube.oauth-token.state.json) - переразрешите, чтобы фабрика знала срок: ${FIX}`,
        state_present: false,
        state: null,
      });
  }
}

/** Данные API одного канала, которые хранит фабрика. */
export type Held = {
  files: string[];
  /** Папки метрик и сколько в каждой файлов. */
  dirs: { path: string; n: number }[];
  rows: S['ApiDataRow'][];
  texts: S['ApiDataText'][];
};

const row = (
  channel: string,
  slug: string,
  batch: string,
  publish_day: string,
  video_id: string,
): S['ApiDataRow'] => ({
  entry_id: `${channel}/${slug}`,
  channel,
  slug,
  batch,
  publish_day,
  video_id,
});

export const HELD: Record<string, Held> = {
  'example-film': {
    files: [
      'analytics/example-film/daily.jsonl',
      'analytics/example-film/windows.jsonl',
      'analytics/example-film/runs.jsonl',
    ],
    dirs: [{ path: 'analytics/example-film/summary', n: 6 }],
    rows: [
      row('example-film', 'rink-rivals', '2026-10-03T0200Z', '2026-10-05', 'hR7xQ2mK9aB'),
      row('example-film', 'delver', '2026-09-08T0200Z', '2026-09-10', 'dG4pL8nV2cX'),
    ],
    texts: [
      { file: 'publish/README.md', video_id: 'hR7xQ2mK9aB' },
      { file: 'publish/notes/example-film/delver.md', video_id: 'dG4pL8nV2cX' },
    ],
  },
  'example-tech': {
    files: ['analytics/example-tech/daily.jsonl', 'analytics/example-tech/runs.jsonl'],
    dirs: [],
    rows: [row('example-tech', 'quantum-chip', '2026-10-06T0200Z', '2026-10-08', 'qC1mT5rW8yZ')],
    texts: [],
  },
  'example-science': { files: [], dirs: [], rows: [], texts: [] },
};

/** Строки журнала, не обновлявшиеся `stale_days`+ дней (их удалил бы авто-прогон). */
export const STALE = ['example-film/delver'];
/** Строки, не обновлявшиеся `refresh_days`+ дней (строка статуса фабрики их считает). */
export const UNREFRESHED = ['example-film/delver'];

/** Отметка отзыва для варианта «Google отказал токену». */
export const REVOCATION: S['ApiDataRevocation'] = {
  revoked_at: '2026-10-10T08:12:00Z',
  due_at: '2026-11-04T08:12:00Z',
  deadline: '2026-11-09T08:12:00Z',
  deleted: null,
};
