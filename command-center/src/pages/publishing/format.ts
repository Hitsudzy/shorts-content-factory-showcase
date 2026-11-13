// Слова экрана «Публикация» для человека: время слота, состояние «завтра», пауза, переключатель
// API-загрузки. Строки фабрики показываются как есть только под «подробнее».
import type {
  ApiSwitchState,
  ChannelPause,
  HoldRow,
  QueueLine,
  QueueSlot,
  SlotRule,
} from '@/api/publish';
import type { Tone } from '@/components/common/Status';
import { dateTimeMsk, dayLabel, FACTORY_TZ } from '@/pages/batches/format';

/** Московский день (`YYYY-MM-DD`) момента `iso`; фабрика считает дни по Москве. */
export function mskDay(iso: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: FACTORY_TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso));
}

/** «01:00» и «МСК» слота: время — из местного ISO, пояс — хвост подписи фабрики. */
export function slotTime(s: Pick<QueueSlot, 'local' | 'label'>): { time: string; zone: string } {
  const time = /T(\d{2}:\d{2})/.exec(s.local)?.[1] ?? s.label;
  const zone = s.label.split(' ').slice(2).join(' ');
  return { time, zone };
}

/** «сб 11.10» или «завтра» — день слота относительно сегодняшнего московского. */
export function slotDay(day: string, today: string): string {
  const d = dayLabel(day, today);
  return d.rel ?? `${d.weekday} ${d.date}`;
}

/** Правило слота словами: «01:00 МСК · 1 в день · не раньше чем через 12 ч». */
export function slotRuleText(rule: SlotRule): string {
  const zone = rule.tz === 'Europe/Moscow' ? 'МСК' : rule.tz;
  const lead = Number.isInteger(rule.lead_hours) ? rule.lead_hours : rule.lead_hours.toFixed(1);
  return `${rule.times.join(', ')} ${zone} · ${rule.per_day} в день · не раньше чем через ${lead} ч`;
}

/** Состояние канала одной меткой — по завтрашнему слоту фабрики (`tomorrow`). */
export function lineState(l: QueueLine): { label: string; tone: Tone; tip: string } {
  if (l.error)
    return { label: 'не читается', tone: 'danger', tip: 'Очередь канала не читается фабрикой' };
  if (!l.slot)
    return {
      label: 'нет слота',
      tone: 'idle',
      tip: 'У канала не задан слот публикации — очереди нет',
    };
  if (l.paused)
    return {
      label: 'на паузе',
      tone: 'warn',
      tip: 'Публикации канала на паузе: ролики в слоты не ставятся',
    };
  switch (l.tomorrow?.state) {
    case 'ok':
      return { label: 'завтра занято', tone: 'ok', tip: 'Завтрашний слот занят роликом' };
    case 'empty':
      return {
        label: 'завтра пусто',
        tone: 'warn',
        tip: 'Завтрашний слот пуст: поставьте принятый ролик',
      };
    default:
      return {
        label: 'ошибка',
        tone: 'danger',
        tip: 'Фабрика не смогла проверить завтрашний слот',
      };
  }
}

export function pauseState(p: ChannelPause): { label: string; tone: Tone; text: string } {
  if (p.state === 'paused')
    return {
      label: 'на паузе',
      tone: 'warn',
      text: p.row?.reason ?? 'Публикации канала на паузе.',
    };
  if (p.state === 'expired')
    return {
      label: 'пауза истекла',
      tone: 'idle',
      text: 'Срок паузы прошёл — она больше не держит публикации.',
    };
  return { label: 'идут', tone: 'ok', text: 'Паузы нет: ролики встают в слоты.' };
}

export function switchState(s: ApiSwitchState): { label: string; tone: Tone; text: string } {
  if (s.error)
    return {
      label: 'не читается',
      tone: 'danger',
      text: 'Состояние переключателя не читается — фабрика считает его выключенным.',
    };
  return s.on
    ? {
        label: 'включена',
        tone: 'ok',
        text: 'Ролики грузит программа после вашего «да»; Studio — запасной путь.',
      }
    : {
        label: 'выключена',
        tone: 'idle',
        text: 'Ролики загружаются вручную через YouTube Studio.',
      };
}

/** Когда и кем поставлен холд: «09.10, 07:00». */
export const holdWhen = (h: HoldRow) => dateTimeMsk(h.raised_at) ?? '—';

/** Ключ занятого слота в адресе (`?slot=`): «<день>/<имя ролика>». */
export function slotKey(s: Pick<QueueSlot, 'day' | 'taken_by'>) {
  return `${s.day}/${s.taken_by ?? ''}`;
}

/**
 * Предупреждение API-загрузки (`api_switch.warnings`) по-русски (CC-0131): без имён настроек и
 * команд — они под «Подробнее». Незнакомая строка — как есть, с тире вместо « - ».
 */
export function apiWarningText(w: string): string {
  if (/PUBLISHER_OAUTH_MODE=testing|режиме Testing/i.test(w))
    return 'Приложение YouTube ещё не прошло аудит: загруженные ролики видны только владельцу канала';
  const m = /refresh-токен истекает (\d{4})-(\d\d)-(\d\d)(?: \(([^)]*)\))?/.exec(w);
  if (m)
    return `Доступ к YouTube истекает ${m[3]}.${m[2]}${m[4] ? ` (${m[4]})` : ''} — токен нужно обновить, команда — в «Подробнее»`;
  return w.replace(/ - /g, ' — ');
}

const VERDICT_WORD: Record<string, string> = {
  hold: 'холд',
  pass: 'пропустить',
  block: 'не публиковать',
};

/** Строка «что отметила проверка» холда (CC-0131): «вердикт compliance-checker: hold» — словами, как стадия «Проверка на риски». */
export function flaggedText(f: string): string {
  const v = /^вердикт compliance-checker:\s*(\S+)/.exec(f);
  if (v) return `вердикт проверки на риски: ${VERDICT_WORD[v[1]!] ?? v[1]}`;
  return f
    .replace(/^права \(для сведения\):/, 'права (справочно, подпись не меняют):')
    .replace(/compliance-checker/g, 'проверка на риски')
    .replace(/ - /g, ' — ');
}
