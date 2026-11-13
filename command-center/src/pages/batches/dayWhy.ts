// Причина дня плана недели словами (CC-0146, CC-0147). Строка фабрики `why` написана для
// консоли: «лента короче 3 дн. (на 1 дн.): пусто …», «1 батч в сутки на фабрику». Здесь —
// фраза для человека из полей плана: `kind` дня (ветка `batch_schedule.plan`, CF-0785), канал,
// его порог батча (`channels[ch].batch_feed_days`, CF-0922; у старой фабрики — `min_feed_days`,
// тогда порогом был он), `first_empty_slot` и `covers_days` у дня с
// батчем, `per_day`. Строку `why` не разбираем: она как есть уходит под «Подробнее».
//
// Заметки дня `nobody_available` (`notes`, по строке на канал: «<канал>: окно … сегодня
// прошло», «<канал>: на паузе - …») пересказываем словами, каналы с одной причиной — вместе;
// незнакомую заметку — как есть.
//
// Сутки фабрики — сутки квоты поиска YouTube (CF-0787): 100 поисков на все каналы вместе,
// сброс в полночь по Тихоокеанскому времени (`plan.quota_tz`). День `quota_day_taken` — его
// окна попадают в сутки квоты, которые уже взял батч (`done`) или более ранний день плана
// (`idle`); `next_windows` — следующее окно каждого канала, каналы с одним временем — вместе.
// День под размыкателем повторов (CF-0822) — `nobody_available` с `breaker`: пересказ записи
// (./breaker), следующее окно — из `next_windows`.
//
// Перед « — » во фразах неразрывный пробел: на телефоне тире не начинает строку.
import type { PlanDay, SchedulePlan } from '@/api/schedule';

import { breakerText } from './breaker';
import { daysWord, dateTimeMsk, plural } from './format';

export type DayWhy = {
  /** Почему так — фраза для человека. */
  text: string;
  /** Первый пустой слот ленты словами (день с батчем); `null` — не известен. */
  slot: string | null;
  /** В какие слоты (дни) встанут ролики батча словами (день с батчем); `null` — не этот день. */
  covers: string | null;
  /** Следующие окна каналов словами (день `quota_day_taken`); `null` — не этот день. */
  next: string | null;
};

type Name = (id: string) => string;

/** «не больше одного батча в сутки на всю фабрику» — правило фабрики `per_day`. */
export function perDayText(n: number): string {
  const count = n === 1 ? 'одного батча' : `${n} ${plural(n, 'батча', 'батчей', 'батчей')}`;
  return `не больше ${count} в сутки на всю фабрику`;
}

/**
 * Порог батча канала, дней (CF-0922): из плана, иначе из его настроек. Фабрика без порога
 * (`batch_feed_days` нет) — `min_feed_days`: у неё порогом был он.
 */
function thresholdOf(plan: SchedulePlan, id: string | null | undefined): number | null {
  if (!id) return null;
  const c = plan.channels[id];
  return (
    c?.batch_feed_days ??
    c?.settings.batch_feed_days ??
    c?.min_feed_days ??
    c?.settings.min_feed_days ??
    null
  );
}

/** Общий порог батча каналов в расписании, если он у всех один; иначе `null`. */
function commonThreshold(plan: SchedulePlan): number | null {
  const all = Object.keys(plan.channels)
    .filter((id) => plan.channels[id]!.plannable)
    .map((id) => thresholdOf(plan, id));
  const first = all[0];
  return first != null && all.every((n) => n === first) ? first : null;
}

/** Неразрывные пробелы вместо обычных: дата и время не разъезжаются по строкам. */
const nbsp = (s: string) => s.replaceAll(' ', '\u00a0');
/** « - » и « — » строки фабрики — тире с неразрывным пробелом перед ним. */
const dashes = (s: string) => s.replace(/ +(?:-|—) /g, '\u00a0— ');

/** «A», «A и B», «A, B и C». */
const andList = (xs: readonly string[]) =>
  xs.length < 2 ? (xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} и ${xs.at(-1)}`;

/** `YYYY-MM-DD` → «18.10». */
const ddmm = (day: string) => {
  const [, m, d] = day.split('-');
  return d && m ? `${d}.${m}` : day;
};

/** День после `day` (`YYYY-MM-DD`). */
const nextDay = (day: string) => {
  const t = new Date(`${day}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + 1);
  return t.toISOString().slice(0, 10);
};

/**
 * Дни слотов коротко: от трёх дней подряд — диапазоном («18.10–20.10»), остальные —
 * списком («18.10, 20.10 и 22.10»). Пусто — `null`.
 */
export function daysText(days: readonly string[]): string | null {
  const sorted = [...new Set(days)].sort();
  const runs: [string, string][] = [];
  for (const d of sorted) {
    const last = runs.at(-1);
    if (last && nextDay(last[1]) === d) last[1] = d;
    else runs.push([d, d]);
  }
  // Диапазон — от трёх дней подряд; два дня — просто двумя датами.
  const parts = runs.flatMap(([a, b]) =>
    a === b ? [ddmm(a)] : nextDay(a) === b ? [ddmm(a), ddmm(b)] : [`${ddmm(a)}–${ddmm(b)}`],
  );
  return parts.length ? andList(parts) : null;
}

/**
 * Заметки дня «некого планировать» словами (CC-0147): каналы с одной причиной — вместе, каждая
 * причина один раз. «у ExampleFilm и ExampleTech окна на сегодня уже прошли», «ExampleFilm и
 * ExampleTech на паузе до 17.10 (заметка: …)»; незнакомая заметка — как есть, с именем канала.
 */
export function notesWords(notes: readonly string[], name: Name = (id) => id): string[] {
  const groups = new Map<string, { chs: string[]; say: (who: string, n: number) => string }>();
  const add = (key: string, ch: string, say: (who: string, n: number) => string) => {
    const g = groups.get(key);
    if (g) {
      if (!g.chs.includes(ch)) g.chs.push(ch);
    } else groups.set(key, { chs: [ch], say });
  };
  for (const raw of notes) {
    const note = raw.trim();
    const m = /^([\w.-]+): (.*)$/.exec(note);
    if (!m) {
      add(`raw:${note}`, '', () => dashes(note));
      continue;
    }
    const [, ch, body] = m as unknown as [string, string, string];
    const passed = /^окно (?:\d\d\.\d\d )?(\d\d:\d\d) МСК сегодня прошло$/.exec(body);
    if (passed) {
      const time = nbsp(`${passed[1]} МСК`);
      add('passed', ch, (who, n) =>
        n === 1 ? `у ${who} окно в ${time} уже прошло` : `у ${who} окна на сегодня уже прошли`,
      );
      continue;
    }
    const paused = /^на паузе(?: - |: )(.+)$/.exec(body);
    if (paused) {
      const why = dashes(paused[1]!.trim());
      // «на паузе - пауза до 17.10 …» — слово «пауза» второй раз не повторяем.
      const rest = why.replace(/^пауза(?: публикаций)?\s+/, '');
      add(`paused:${why}`, ch, (who) =>
        rest !== why ? `${who} на паузе ${rest}` : `${who} на паузе: ${why}`,
      );
      continue;
    }
    add(`other:${body}`, ch, (who) => `${who}: ${dashes(body)}`);
  }
  return [...groups.values()].map((g) => g.say(andList(g.chs.map(name)), g.chs.length));
}

const NONE = { slot: null, covers: null, next: null } as const;

/** Часовой пояс суток квоты, если план его не назвал. */
const QUOTA_TZ = 'America/Los_Angeles';

/**
 * Когда кончаются сутки квоты `day` (YYYY-MM-DD в `tz`): ISO полночи следующего дня там.
 * Тихоокеанская полночь — 07:00Z летом и 08:00Z зимой; час ищем перебором, без таблиц.
 */
export function quotaResetAt(day: string, tz: string = QUOTA_TZ): string | null {
  if (!/^\d{4}-\d\d-\d\d$/.test(day) || Number.isNaN(Date.parse(day))) return null;
  const next = nextDay(day);
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const base = new Date(`${next}T00:00:00Z`).getTime();
  for (let h = -14; h <= 14; h++) {
    const t = new Date(base + h * 3_600_000);
    if (fmt.format(t) === `${next}, 00:00`) return t.toISOString().replace('.000Z', 'Z');
  }
  return null;
}

/**
 * Следующие окна каналов (`next_windows` дня `quota_day_taken`) словами: «Следующее окно:
 * ExampleFilm 12.10, 02:00 МСК»; каналы с одним временем — вместе («ExampleFilm и ExampleTech
 * 19.10, 11:30 МСК»), по времени; канал без окна — «у ExampleTech в ближайшие дни окна нет».
 */
export function nextWindowsText(
  next: Readonly<Record<string, string | null>>,
  name: Name = (id) => id,
): string | null {
  const byTime = new Map<string, string[]>();
  const none: string[] = [];
  for (const [chId, at] of Object.entries(next)) {
    const when = dateTimeMsk(at);
    if (!at || !when) none.push(chId);
    else byTime.set(at, [...(byTime.get(at) ?? []), chId]);
  }
  const times = [...byTime.entries()].sort(([a], [b]) => Date.parse(a) - Date.parse(b));
  const parts = times.map(
    ([at, chs]) => `${andList(chs.map(name))} ${nbsp(`${dateTimeMsk(at)!} МСК`)}`,
  );
  if (!parts.length && !none.length) return null;
  if (!parts.length) return 'Следующего окна в ближайшие дни нет';
  const head = parts.length === 1 ? 'Следующее окно' : 'Следующие окна';
  const tail = none.length ? `; у ${andList(none.map(name))} в ближайшие дни окна нет` : '';
  return `${head}: ${parts.join('; ')}${tail}`;
}

/** День плана раньше `d`, чей батч берёт те же сутки квоты (день `quota_day_taken`, `idle`). */
function holderOf(d: PlanDay, plan: SchedulePlan): PlanDay | null {
  if (!d.quota_day) return null;
  return (
    plan.days.find(
      (x) => x.day < d.day && x.kind === 'needs_batch' && x.quota_day === d.quota_day,
    ) ?? null
  );
}

export function dayWhy(d: PlanDay, plan: SchedulePlan, name: Name = (id) => id): DayWhy {
  switch (d.kind) {
    case 'needs_batch': {
      const n = thresholdOf(plan, d.channel);
      const first = dateTimeMsk(d.first_empty_slot);
      const days = daysText(d.covers_days ?? []);
      const one = d.est_videos === 1;
      return {
        text:
          n != null
            ? `Публикаций на ${daysWord(n)} вперёд не хватает\u00a0— нужен батч`
            : 'Публикаций в ленте не хватает\u00a0— нужен батч',
        next: null,
        slot: first ? `Первый пустой слот: ${nbsp(`${first} МСК`)}` : null,
        covers: days
          ? `${one ? 'Ролик встанет в слот' : 'Ролики встанут в слоты'} ${days}`
          : 'Свободных слотов после конца батча нет',
      };
    }
    case 'done_today': {
      // Сутки квоты (CF-0787): батч уже был в текущих сутках квоты — до их сброса второго нет.
      const reset = dateTimeMsk(quotaResetAt(d.quota_day ?? plan.quota_day, plan.quota_tz));
      return {
        text: reset
          ? `Батч в эти сутки квоты уже был\u00a0— следующие начнутся ${nbsp(`${reset} МСК`)}`
          : `Батч в эти сутки квоты уже был\u00a0— ${perDayText(plan.per_day)}`,
        ...NONE,
      };
    }
    case 'quota_day_taken': {
      const holder = d.status === 'done' ? null : holderOf(d, plan);
      return {
        text:
          d.status === 'done'
            ? 'Эти сутки квоты поиска YouTube уже занял прошлый батч\u00a0— второй не запускается'
            : holder
              ? `Эти сутки квоты поиска YouTube займёт батч ${ddmm(holder.day)}\u00a0— в этот день батча не будет`
              : 'Эти сутки квоты поиска YouTube займёт батч дня раньше\u00a0— в этот день батча не будет',
        slot: null,
        covers: null,
        next: nextWindowsText(d.next_windows ?? {}, name),
      };
    }
    case 'running':
      return { text: 'Идёт батч\u00a0— второй в этот день не запускается', ...NONE };
    case 'fed': {
      const n = commonThreshold(plan);
      return {
        text:
          n != null
            ? `Публикаций хватает на ${daysWord(n)} вперёд\u00a0— батч не нужен`
            : 'Публикаций у всех каналов хватает\u00a0— батч не нужен',
        ...NONE,
      };
    }
    case 'nobody_plannable':
      return {
        text: 'Некого планировать: ни у одного канала нет слота и плана запуска',
        ...NONE,
      };
    case 'nobody_available': {
      // CF-0822: день под размыкателем повторов — `nobody_available` с записью `breaker`.
      if (d.breaker)
        return {
          text: breakerText(d.breaker, name),
          slot: null,
          covers: null,
          next: nextWindowsText(d.next_windows ?? {}, name),
        };
      const why = notesWords(d.notes ?? [], name);
      return {
        text: why.length
          ? `Некого планировать: ${why.join('; ')}`
          : 'Некого планировать в этот день',
        ...NONE,
      };
    }
    default:
      // Ветка, которой центр ещё не знает: нейтральная фраза, строка фабрики — под «Подробнее».
      return { text: 'В этот день батча не будет', ...NONE };
  }
}
