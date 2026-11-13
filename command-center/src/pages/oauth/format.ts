// Слова экрана «Токены, OAuth и данные API» (CC-0029): состояния токена (`publisher_auth.py
// status`), разрешения (scope) по-человечески, срок, правила политики YouTube API для данных API
// и что из плана удаления относится к каналу — словами, без путей (пути — под «подробнее»).
import { readableSlug } from '@/api/videos';
import type { ApiDataPlan, ChannelShare, OAuthToken, TokenKind } from '@/api/oauth';
import type { Tone } from '@/components/common/Status';
import { whenText } from '@/pages/notify/format';
import { plural } from '@/pages/batches/format';

/** Состояние токена: плашка, её тон и пояснение (тултип). */
export const TOKEN_KIND: Record<TokenKind, { label: string; tone: Tone; tip: string }> = {
  ok: {
    label: 'действует',
    tone: 'ok',
    tip: 'Фабрика загружает ролики и собирает метрики этим токеном',
  },
  'expires-soon': {
    label: 'скоро истечёт',
    tone: 'warn',
    tip: 'Срок токена подходит к концу — переразрешите заранее, это ~30 секунд в браузере',
  },
  expired: {
    label: 'истёк',
    tone: 'danger',
    tip: 'Google больше не принимает токен: загрузка и сбор метрик стоят до переразрешения',
  },
  'no-auth': {
    label: 'нет токена',
    tone: 'danger',
    tip: 'Доступ к YouTube ещё не разрешали (или токен удалили): загрузки и метрик нет',
  },
  'no-scope': {
    label: 'не хватает разрешений',
    tone: 'danger',
    tip: 'При входе сняли галочку: токен есть, но части разрешений у него нет',
  },
  'unknown-expiry': {
    label: 'срок неизвестен',
    tone: 'warn',
    tip: 'Токен выдан до того, как фабрика стала записывать срок, — она не знает, когда он истечёт',
  },
};

/** Токен требует вашего входа в Google (не «ok»). */
export const needsSignIn = (kind: TokenKind) => kind !== 'ok';

/** Разрешение (scope) словами. */
export const SCOPE: Record<string, { label: string; tip: string }> = {
  'youtube.upload': {
    label: 'Загрузка роликов',
    tip: 'Загружать ролики на канал программой (загрузка через API)',
  },
  'youtube.readonly': {
    label: 'Чтение канала',
    tip: 'Читать ролики и их статистику: просмотры, лайки (videos.list)',
  },
  'yt-analytics.readonly': {
    label: 'Аналитика',
    tip: 'Читать YouTube Analytics: удержание и окна просмотров для отчётов аналитика',
  },
};

export const scopeLabel = (short: string) => SCOPE[short]?.label ?? short;

/** Режим OAuth-приложения: тестовый даёт токен на неделю, рабочий — без срока. */
export function modeText(mode: string | null | undefined, days: number): string {
  if (mode === 'production') return 'рабочий режим Google — без фиксированного срока';
  if (mode === 'testing')
    return `тестовый режим Google — токен на ${days}\u00a0${plural(days, 'день', 'дня', 'дней')}`;
  return 'не записан';
}

/** «4 дня», «20 ч», «35 мин». */
export function leftText(hours: number): string {
  if (hours >= 48) {
    const d = Math.floor(hours / 24);
    return `${d} ${plural(d, 'день', 'дня', 'дней')}`;
  }
  if (hours >= 1) {
    const h = Math.round(hours);
    return `${h} ч`;
  }
  return `${Math.max(0, Math.round(hours * 60))} мин`;
}

/** Главная строка карточки токена — что со сроком, словами. */
export function termText(t: OAuthToken): string {
  const until = whenText(t.expires_at, t.now);
  const refused = t.state?.invalid_grant_at;
  switch (t.kind) {
    case 'ok':
      if (!t.expires_at) return 'Без фиксированного срока: действует, пока доступ не отозван';
      return `Действует ещё ${leftText(t.hours_left ?? 0)} — до ${until} МСК`;
    case 'expires-soon':
      return `Истекает через ${leftText(t.hours_left ?? 0)} — ${until} МСК`;
    case 'expired':
      if (refused) return `Google отказал токену ${whenText(refused, t.now)} МСК`;
      return `Истёк ${until} МСК — загрузка и метрики стоят`;
    case 'no-auth':
      return 'Токена нет — фабрика не загружает ролики и не собирает метрики';
    case 'no-scope': {
      const miss = t.scopes.missing.map((s) => scopeLabel(t.scopes.short[s] ?? s));
      return `У токена нет разрешения: ${miss.join(', ')}`;
    }
    case 'unknown-expiry':
      return 'Срок неизвестен: фабрика не знает, когда токен истечёт';
  }
}

/** Токен выдан в Testing, а приложение уже в Production: новый вход снимет срок. */
export const modeMismatch = (t: OAuthToken) =>
  t.oauth_mode === 'production' && t.token_mode === 'testing';

// ---------------------------------------------------------------- данные API
/** Что из метрик Analytics лежит в файле (по имени файла). */
const FILE_WORD: Record<string, string> = {
  'daily.jsonl': 'по дням',
  'windows.jsonl': 'по окнам после публикации',
  'runs.jsonl': 'журнал загрузок',
};

const base = (p: string) => p.split('/').pop() ?? p;

const filesWord = (n: number) => `${n}\u00a0${plural(n, 'файл', 'файла', 'файлов')}`;
const rowsWord = (n: number) => `${n}\u00a0${plural(n, 'записи', 'записях', 'записях')}`;
const textsWord = (n: number) => `${n}\u00a0${plural(n, 'тексте', 'текстах', 'текстах')}`;
// Число и слово не разрываются переносом (неразрывный пробел, CC-0087).
export const itemsWord = (n: number) => `${n}\u00a0${plural(n, 'объект', 'объекта', 'объектов')}`;
export const channelsWord = (n: number) => `${n}\u00a0${plural(n, 'канал', 'канала', 'каналов')}`;

/** Сколько файлов в папке — из строки `describe` («dir   …/ (6 file(s))»). */
function dirFiles(plan: ApiDataPlan, dir: string): number | null {
  const l = plan.lines.find((x) => x.includes(`${dir}/ (`));
  const m = l ? /\((\d+) file\(s\)\)/.exec(l) : null;
  return m ? Number(m[1]) : null;
}

/** Строки «что удалится» у одного канала — словами, без путей. */
export function shareLines(s: ChannelShare, plan: ApiDataPlan): string[] {
  const out: string[] = [];
  if (s.files.length)
    out.push(
      `Статистика просмотров из YouTube Analytics: ${s.files.map((f) => FILE_WORD[base(f)] ?? 'другое').join(', ')}`,
    );
  for (const d of s.dirs) {
    const n = dirFiles(plan, d);
    out.push(`Сводка аналитика по этой статистике${n !== null ? ` (${filesWord(n)})` : ''}`);
  }
  if (s.rows.length)
    out.push(
      `Данные, полученные через API YouTube, в ${rowsWord(s.rows.length)} публикаций: ${s.rows.map((r) => (r.slug ? `«${readableSlug(r.slug)}»` : '—')).join(', ')} — остальное в записях остаётся`,
    );
  if (s.texts.length)
    out.push(`Ссылки на ролики в ${textsWord(s.texts.length)} заменятся пометкой`);
  return out;
}

/** Причина плана авто-прогона словами. */
export function dueReason(reason: string, staleDays: number): string {
  if (reason.startsWith('not refreshed'))
    return `Записи журнала, не обновлявшиеся ${staleDays}+ дней`;
  if (reason.startsWith('revoked'))
    return 'После отзыва доступа вышел срок — удаляется всё из YouTube API';
  return reason;
}

/** Дата по Москве: «4 ноября». */
export const dayText = (iso: string | null | undefined, now?: string | null) =>
  whenText(iso, now)?.replace(/, \d{2}:\d{2}$/, '') ?? null;

/** Почему «Отозвать доступ» погашено, когда фабрика не отзывает из центра (`confirm_available: false`). */
export const REVOKE_OFF =
  'Эта фабрика не отзывает доступ из центра — отзовите на странице разрешений Google или командой фабрики в терминале';

/** Ответ Google на отзыв словами; `null` — сухой прогон, Google не спрашивали. */
export function googleText(answer: string | null | undefined): string {
  switch (answer) {
    case 'revoked':
      return 'Google отозвал разрешение фабрики';
    case 'invalid_token':
      return 'Google ответил, что токен уже недействителен — разрешения и так не было';
    case 'unreachable':
      return 'Google не ответил';
    case 'no token':
      return 'Отзывать у Google было нечего — токена нет';
    default:
      return 'Google не спрашивали';
  }
}
