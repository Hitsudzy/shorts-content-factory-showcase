// Слова и числа экрана «Батчи» для человека: дни и время по Москве (у фабрики один день —
// московский), длительности, оценки «по N прогонам», рубильник и таймер. Общие для (а)…(в).
import type { PlanDay, Switch } from '@/api/schedule';
import type { Tone } from '@/components/common/Status';

export const FACTORY_TZ = 'Europe/Moscow';

export function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return one;
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return few;
  return many;
}

export const runsWord = (n: number) => `${n} ${plural(n, 'прогону', 'прогонам', 'прогонам')}`;
export const videosWord = (n: number) => `${n} ${plural(n, 'ролик', 'ролика', 'роликов')}`;
export const daysWord = (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`;

const valid = (iso: string | null | undefined): Date | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
};

/** «02:00» по Москве; null — времени нет. */
export function timeMsk(iso: string | null | undefined): string | null {
  const d = valid(iso);
  if (!d) return null;
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: FACTORY_TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(d);
}

/** «10.10, 02:00» по Москве. */
export function dateTimeMsk(iso: string | null | undefined): string | null {
  const d = valid(iso);
  if (!d) return null;
  const date = new Intl.DateTimeFormat('ru-RU', {
    timeZone: FACTORY_TZ,
    day: '2-digit',
    month: '2-digit',
  }).format(d);
  return `${date}, ${timeMsk(iso)}`;
}

const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'] as const;

/** День плана (`YYYY-MM-DD`, московский): `{ weekday: 'сб', date: '10.10', rel: 'сегодня' }`. */
export function dayLabel(day: string, today: string) {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  const at = Date.UTC(y, m - 1, d);
  const [ty, tm, td] = today.split('-').map(Number) as [number, number, number];
  const diff = Math.round((at - Date.UTC(ty, tm - 1, td)) / 86_400_000);
  const rel = diff === 0 ? 'сегодня' : diff === 1 ? 'завтра' : null;
  return {
    weekday: WEEKDAYS[new Date(at).getUTCDay()]!,
    date: `${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}`,
    rel,
  };
}

/** «≈ 4 ч 12 мин», «≈ 45 мин». */
export function durationText(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const min = Math.max(0, Math.round(seconds / 60));
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `≈ ${m} мин`;
  return m ? `≈ ${h} ч ${m} мин` : `≈ ${h} ч`;
}

/**
 * Откуда оценка (для тултипа): «Оценка по 5 прогонам: …» или «По умолчанию: …».
 * null — фабрика не сказала.
 */
export function estimateBasis(n: number | null | undefined): string | null {
  if (n == null) return null;
  if (n <= 0) return 'По умолчанию: прогонов канала ещё нет, фабрика взяла своё значение';
  return `Оценка по ${runsWord(n)}: среднее последних прогонов канала, не обещание`;
}

/**
 * Что такое «сутки» фабрики (CF-0787) — один раз, в подсказке меток «батч был» (done_today) и «квота
 * занята»: сутки квоты поиска YouTube, сброс в тихоокеанскую полночь.
 */
export const QUOTA_TIP =
  'Квота поиска YouTube — 100 поисков в сутки на все каналы вместе, обычно её хватает на один батч. ' +
  'Второй батч в те же сутки — только у канала с несколькими окнами и только если хватает бюджета поиска. ' +
  'Сутки квоты начинаются в полночь по тихоокеанскому времени\u00a0— в 10:00\u00a0МСК, а с 1\u00a0ноября до марта\u00a0— в 11:00\u00a0МСК';

/** Метка дня плана. */
export const DAY_STATUS: Record<PlanDay['status'], { label: string; tone: Tone; tip: string }> = {
  planned: {
    label: 'по плану',
    tone: 'ok',
    tip: 'Батч этого дня по плану фабрики: расписание запустит его в окне канала, если рубильник включён',
  },
  busy: {
    label: 'идёт батч',
    tone: 'live',
    tip: 'День занят: идёт батч, второй в этот день не запускается',
  },
  done: {
    label: 'батч был',
    tone: 'idle',
    tip: `Батч в эти сутки квоты уже был: обычно фабрика делает один батч в сутки на все каналы. ${QUOTA_TIP}`,
  },
  idle: {
    label: 'без батча',
    tone: 'idle',
    tip: 'В этот день батча не будет — почему, написано рядом',
  },
};

/** Метка дня «некого планировать» (CC-0147): отличить от «без батча» (ленты хватает) на глаз. */
const NOBODY_PILL = {
  label: 'некого',
  tone: 'warn' as Tone,
  tip: 'Батча не будет: ни один канал не может взять этот день — почему, написано рядом',
};

/**
 * Метка дня «сутки квоты заняты» (`quota_day_taken`, CC-0147): не «без батча» (ленты хватает),
 * не «некого» (каналы не могут) и не «батч был» — в этот день батча не было, квоту потратил
 * батч раньше (`done`) или потратит батч более раннего дня плана (`idle`).
 */
const QUOTA_PILL = {
  done: {
    label: 'квота занята',
    tone: 'idle' as Tone,
    tip: `Батч не запустится: квоту этих суток уже потратил прошлый батч. ${QUOTA_TIP}`,
  },
  idle: {
    label: 'квота занята',
    tone: 'idle' as Tone,
    tip: `Батч не запустится: квоту этих суток потратит батч более раннего дня плана. ${QUOTA_TIP}`,
  },
};

/** Правило защиты от повтора (размыкатель CF-0822) — подсказка метки дня и плашки канала. */
export const BREAKER_TIP =
  'Защита от повтора: если батч упал, не потратив квоту поиска, фабрика не запускает его снова в те ' +
  'же сутки квоты, пока код не изменится. После нового кода разрешён один повтор. Ручной запуск ' +
  'защита не останавливает';

/** Метка дня и плашка канала под размыкателем повторов (CF-0822, CC-0152). */
export function breakerBadge(b: { held: boolean }): { label: string; tone: Tone; tip: string } {
  return b.held
    ? { label: 'повтор придержан', tone: 'warn', tip: BREAKER_TIP }
    : { label: 'повтор разрешён', tone: 'idle', tip: BREAKER_TIP };
}

/**
 * Метка дня плана: по `status`, а дни «некого планировать» и «квота занята» (`kind`) — своей;
 * день под размыкателем повторов (`breaker`, CF-0822) — «повтор придержан».
 */
export function dayPill(d: Pick<PlanDay, 'status' | 'kind'> & Partial<Pick<PlanDay, 'breaker'>>) {
  if (d.breaker) return breakerBadge(d.breaker);
  if (d.kind === 'nobody_plannable' || d.kind === 'nobody_available') return NOBODY_PILL;
  if (d.kind === 'quota_day_taken') return d.status === 'done' ? QUOTA_PILL.done : QUOTA_PILL.idle;
  return DAY_STATUS[d.status];
}

/** Кто переключил рубильник: `user` — вы. */
export function whoText(by: string | null | undefined): string | null {
  if (!by) return null;
  if (by === 'user' || by.startsWith('user ')) return 'вы';
  return by;
}

/** Заметка рубильника/настроек без служебного «центр: » — его ставит API. */
export function noteText(note: string | null | undefined): string | null {
  if (!note) return null;
  const t = note.replace(/^центр(:\s*|$)/, '').trim();
  return t || null;
}

/** Рубильник одним словом и смыслом. */
export function switchState(sw: Switch): { label: string; tone: Tone; text: string } {
  if (sw.error)
    return {
      label: 'не читается',
      tone: 'danger',
      text: 'Файл рубильника не читается — фабрика считает расписание выключенным.',
    };
  if (sw.on)
    return {
      label: 'включено',
      tone: 'ok',
      text: 'Фабрика сама запускает батч дня по плану, в окне канала.',
    };
  return {
    label: 'выключено',
    tone: 'idle',
    text: 'Батчи по расписанию не запускаются — только запуском вручную.',
  };
}

/** Таймер расписания (launchd) одним словом: строку фабрики целиком — под «подробнее». */
export function timerState(line: string): { label: string; tone: Tone } {
  if (/не проверяется/i.test(line)) return { label: 'не проверяется на этой ОС', tone: 'idle' };
  if (/НЕ установлен/.test(line)) return { label: 'не установлен', tone: 'warn' };
  if (/установлен/i.test(line)) return { label: 'установлен', tone: 'ok' };
  return { label: 'неизвестно', tone: 'warn' };
}

/** Подпись поля настроек расписания — для «что поменялось». */
export const SETTING_LABEL: Record<string, string> = {
  enabled: 'участие в расписании',
  window: 'начало окна',
  window_hours: 'длительность окна',
  min_feed_days: 'горизонт ленты',
  batch_feed_days: 'порог батча',
  windows: 'окна',
};

function valueText(key: string, v: unknown): string {
  if (v == null || (Array.isArray(v) && !v.length)) return '—';
  if (Array.isArray(v)) return v.join(', ');
  if (key === 'enabled') return v ? 'да' : 'нет';
  if (key === 'window_hours') return `${String(v)} ч`;
  if (key === 'min_feed_days' || key === 'batch_feed_days') return `${String(v)} дн.`;
  return String(v);
}

/** `{window: ['02:00','03:30']}` → «начало окна: 02:00 → 03:30». */
export function changesText(changes: Record<string, unknown[]>): string[] {
  return Object.entries(changes).map(
    ([k, [a, b]]) => `${SETTING_LABEL[k] ?? k}: ${valueText(k, a)} → ${valueText(k, b)}`,
  );
}
