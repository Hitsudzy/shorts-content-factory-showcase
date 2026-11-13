// Строка фабрики для человека (CC-0089): фабрика пишет её для себя — с путями, кодами настроек
// в скобках, датами ISO и « - » между частями. Слова фабрики остаются её словами; убираются
// пути (`plainReason`) и коды, даты — по-русски по Москве, « - » — тире. Сама строка как есть —
// под «подробнее» у того, кто её показывает. Без зависимостей, кроме `plainReason`.
import { plainReason } from './plainReason';

const TZ = 'Europe/Moscow';
const MONTHS = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
];

const yearMsk = (d: Date) =>
  Number(new Intl.DateTimeFormat('en-US', { timeZone: TZ, year: 'numeric' }).format(d));

/** «10.10, 07:04» по Москве — как `dateTimeMsk` экранов. */
function dateTime(d: Date): string {
  const date = new Intl.DateTimeFormat('ru-RU', {
    timeZone: TZ,
    day: '2-digit',
    month: '2-digit',
  }).format(d);
  const time = new Intl.DateTimeFormat('ru-RU', {
    timeZone: TZ,
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(d);
  return `${date}, ${time}`;
}

/** Дата и время с зоной: `2026-10-10T04:05:00Z`, `…+03:00`, и вид id батча `2026-10-10T0405Z`. */
const DATETIME =
  /\b(\d{4})-(\d{2})-(\d{2})T(\d{2}):?(\d{2})(?::?(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})(?![\w:])/g;
/** Дата без времени: `2026-10-09`. */
const DATE = /\b(\d{4})-(\d{2})-(\d{2})\b(?!T)/g;

/** Даты ISO в строке — словами: «9 октября» (год — если не текущий), «10.10, 07:04». */
export function humanDates(text: string, now: Date = new Date()): string {
  return text
    .replace(DATETIME, (all, y, mo, d, h, mi, s, zone: string) => {
      const z = zone === 'Z' ? 'Z' : `${zone.slice(0, 3)}:${zone.slice(-2)}`;
      const t = new Date(`${y}-${mo}-${d}T${h}:${mi}:${s ?? '00'}${z}`);
      return Number.isNaN(t.getTime()) ? all : dateTime(t);
    })
    .replace(DATE, (all, y: string, mo: string, d: string) => {
      const m = Number(mo);
      const day = Number(d);
      if (m < 1 || m > 12 || day < 1 || day > 31) return all;
      const year = Number(y) === yearMsk(now) ? '' : ` ${y}`;
      return `${day} ${MONTHS[m - 1]}${year}`;
    });
}

/** « - » между частями фразы — тире. */
export const humanDashes = (text: string) => text.replace(/ - /g, ' — ');

/**
 * Тире между частями фразы, которое не уходит в начало строки (CC-0132): пробел перед ним —
 * неразрывный. « - » тоже становится тире.
 */
export const nbDashes = (text: string) => text.replace(/ +(?:-|—) /g, '\u00a0— ');

/**
 * Однобуквенный предлог или союз не висит в конце строки (CC-0152): пробел после «с», «в», «к»,
 * «у», «о», «и», «а», стоящих отдельным словом, — неразрывный: «с 11.10, 10:00 МСК», «встанут
 * в слоты». Слова длиннее и буквы внутри слов не трогает.
 */
export const nbShort = (text: string) =>
  text.replace(/(?<=^|[\s(«"„—])([свкуоиаСВКУОИА]) (?=\S)/gu, '$1\u00a0');

/** Коды настроек в скобках («порог батча (batch_feed_days)») — их место под «подробнее». */
export const withoutCodes = (text: string) =>
  text
    .replace(
      /\s*\((?:[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+)(?:,\s*[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+)*\)/g,
      '',
    )
    .trim();

/** Строка фабрики для основного вида: без путей и кодов, даты словами, тире. */
/** «остановлен пользователем (центр)» фабрики — человеку: «остановлен вами из центра». */
export function byYou(text: string): string {
  return text.replace(/пользователем \((?:через )?центр\)/g, 'вами из центра');
}

export function humanReason(text: string, now: Date = new Date()): string {
  return humanDashes(humanDates(withoutCodes(plainReason(byYou(text))), now));
}
