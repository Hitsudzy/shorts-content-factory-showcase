// Слова экрана «Уведомления и напоминания» (CC-0027): виды уведомлений, каналы доставки (бэкенды
// фабрики), ответы бэкендов (`ok` / `error: …` / `skipped: …` — по договору), состояния напоминаний
// и время по Москве.
import type { NotifyReminder } from '@/api/notify';
import type { Tone } from '@/components/common/Status';
import { FACTORY_TZ, plural } from '@/pages/batches/format';

/** Вид уведомления: короткое слово и пояснение (тултип). */
export const KIND: Record<string, { label: string; tip: string }> = {
  accept: { label: 'ждёт «да»', tip: 'Ролики готовы и ждут вашего «да» на экране «Ролики»' },
  upload: {
    label: 'файл для Studio',
    tip: 'Файл ролика готов — его надо перетащить в Studio. Событие только на этой машине: в Telegram не уходит',
  },
  accepted: {
    label: 'Приёмка',
    tip: 'Итог приёмки батча: какие ролики приняты, какие нет',
  },
  uploaded: {
    label: 'Залито в Studio',
    tip: 'Ролик залит в Studio — с датой, когда он выйдет',
  },
  token: { label: 'срок токена', tip: 'Токен YouTube скоро истечёт — его надо переразрешить' },
  empty_slot: { label: 'пустой слот', tip: 'Завтра у канала нечего публиковать' },
  run_halted: { label: 'батч остановился', tip: 'Батч остановился посреди работы' },
  run_done: { label: 'батч закончен', tip: 'Батч дошёл до конца' },
  needs_human: { label: 'нужен человек', tip: 'Фабрика не может решить сама и ждёт вас' },
  batch_started: { label: 'батч начался', tip: 'Фабрика запустила батч' },
  reminder: { label: 'напоминание', tip: 'Напоминание, которое вы поставили' },
  test: { label: 'проверка', tip: 'Пробное сообщение: проверка, что уведомления доходят' },
  request_answer: {
    label: 'ответ на просьбу',
    tip: 'Оператор ответил на вашу просьбу (экран «Вопросы» → «Просьбы»)',
  },
  hold_released: {
    label: 'холд снят',
    tip: 'Фабрика сама сняла холд: флаг чувствительности стоит на сцене, которой нет в ролике (экран «Публикация» → «Холды публикации»)',
  },
};

/**
 * Многострочный текст строки журнала для Telegram (`body`, CF-0925): лишнее поле `NotifyEvent`
 * (договор разрешает лишние поля) — может не быть или быть не строкой; пустой — как нет.
 */
export function eventBody(e: Record<string, unknown>): string | null {
  const b = e.body;
  return typeof b === 'string' && b.trim() ? b : null;
}

export const kindLabel = (k: string | null | undefined) => (k && KIND[k]?.label) || k || 'без вида';

const URL_RE = /https?:\/\/\S+/g;

/**
 * Текст пробного сообщения для человека (CC-0087): вид уведомления — словами («Фабрика · батч
 * закончен»), адрес центра и подпись ссылки «пульт» убраны — вместо них `link: true` («и ссылку на
 * центр»). Текст фабрики как есть — под «подробнее».
 */
export function previewText(text: string): { lines: string[]; link: boolean } {
  let link = false;
  const lines: string[] = [];
  for (const raw of text.split('\n')) {
    let l = raw;
    if (/https?:\/\//.test(l)) link = true;
    l = l
      .replace(URL_RE, '')
      .replace(/\s*->\s*$/, '')
      .trim();
    if (/^пульт$/i.test(l)) {
      link = true;
      continue;
    }
    l = l.replace(/(·\s*)([a-z_]+)\b/g, (m, dot: string, k: string) =>
      KIND[k] ? `${dot}${KIND[k].label}` : m,
    );
    if (l) lines.push(l);
  }
  return { lines, link };
}

/** Канал доставки уведомлений (бэкенд фабрики). */
export const BACKEND: Record<string, { label: string; tip: string }> = {
  log: { label: 'Журнал', tip: 'Строка в журнале уведомлений фабрики на этой машине' },
  macos: { label: 'Баннер Mac', tip: 'Баннер в углу экрана этого Mac' },
  ntfy: { label: 'ntfy', tip: 'Пуш на телефон через сервис ntfy — текст уходит с этой машины' },
  telegram: { label: 'Telegram', tip: 'Сообщение в Telegram — текст уходит с этой машины' },
  webhook: { label: 'Вебхук', tip: 'Запрос на ваш адрес вебхука — текст уходит с этой машины' },
};

export const backendLabel = (b: string) => BACKEND[b]?.label ?? b;

/** Ответ бэкенда на одно уведомление: `ok`, `error: …`, `skipped: …` (строка — в тултипе). */
export function backendResult(v: unknown): { tone: Tone; label: string } {
  const s = String(v ?? '');
  if (s === 'ok') return { tone: 'ok', label: 'дошло' };
  if (s.startsWith('error')) return { tone: 'danger', label: 'ошибка' };
  if (s.startsWith('skipped')) return { tone: 'idle', label: 'пропущено' };
  return { tone: 'idle', label: s || '—' };
}

export const REMINDER_STATUS: Record<
  NotifyReminder['status'],
  { label: string; tone: Tone; tip: string }
> = {
  pending: {
    label: 'ждёт',
    tone: 'live',
    tip: 'Уйдёт в своё время на все включённые каналы уведомлений',
  },
  failed: {
    label: 'не дошло — будет ещё попытка',
    tone: 'warn',
    tip: 'Ни один внешний канал не принял напоминание — фабрика попробует снова со следующей проверкой',
  },
  exhausted: {
    label: 'не дошло — попытки кончились',
    tone: 'danger',
    tip: 'Фабрика больше не пробует. Напоминание висит здесь, пока его не отменят',
  },
  sent: { label: 'отправлено', tone: 'ok', tip: 'Напоминание ушло' },
  cancelled: { label: 'отменено', tone: 'idle', tip: 'Напоминание отменили — оно не уйдёт' },
};

/** Кто и откуда отменил: «Отменено из центра, вами»; без имени — «Отменено не из центра». */
export function cancelledText(
  by: string | null | undefined,
  via: string | null | undefined,
): string {
  const who = by === 'user' ? 'вами' : by ? by : null;
  const where = via === 'center' ? 'из центра' : via ? `через ${via}` : 'не из центра';
  return `Отменено ${where}${who ? `, ${who}` : ''}`;
}

const valid = (iso: string | null | undefined): Date | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
};

const yearOf = (d: Date) =>
  new Intl.DateTimeFormat('ru-RU', { timeZone: FACTORY_TZ, year: 'numeric' }).format(d);

/** «12 октября, 21:00» по Москве (с годом — если не тот, что у `now`); null — времени нет. */
export function whenText(iso: string | null | undefined, now?: string | null): string | null {
  const d = valid(iso);
  if (!d) return null;
  const ref = valid(now) ?? new Date();
  const day = new Intl.DateTimeFormat('ru-RU', {
    timeZone: FACTORY_TZ,
    day: 'numeric',
    month: 'long',
    ...(yearOf(d) !== yearOf(ref) ? { year: 'numeric' } : {}),
  })
    .format(d)
    .replace(/\s*г\.$/, '');
  const time = new Intl.DateTimeFormat('ru-RU', {
    timeZone: FACTORY_TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(d);
  return `${day}, ${time}`;
}

/** «через 2 ч 20 мин», «через 3 дня»; прошло — null. */
export function untilText(due: string, now: string): string | null {
  const a = valid(due);
  const b = valid(now);
  if (!a || !b) return null;
  const min = Math.round((a.getTime() - b.getTime()) / 60_000);
  if (min < 0) return null;
  if (min < 60) return `через ${min} мин`;
  const h = Math.floor(min / 60);
  if (h < 48) {
    const m = min % 60;
    return m ? `через ${h} ч ${m} мин` : `через ${h} ч`;
  }
  const days = Math.round(h / 24);
  return `через ${days} ${plural(days, 'день', 'дня', 'дней')}`;
}

/** «2 из 8 попыток». */
export const attemptsText = (n: number, max: number) =>
  `${n} из ${max} ${plural(max, 'попытки', 'попыток', 'попыток')}`;
