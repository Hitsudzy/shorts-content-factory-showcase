// «Не в копилке» (CF-0821 фабрики, CC-0152): принятый ролик, который фабрика в копилку канала не
// положила (другая версия уже размещена или отказ копилки). Видимая строка — своя, центра: по
// коду фабрики (`code`) и названию ролика, как его показывает центр; строки фабрики `alert_ru` и
// `text_ru` (с приставкой «НЕ В КОПИЛКЕ: »), имена батчей и пути — под «Подробнее». Тёзка
// (`namesake`) — другой ролик под тем же именем: видно только «Такое имя уже у ролика на другую
// тему», путь и почему другой — под «Подробнее».
import type { Schemas } from '@/api/client';
import { readableSlug } from '@/api/videos';

export type AcceptNamesake = Schemas['AcceptNamesake'];
/** Что нужно метке: запись `left_out` ответа или поля очереди `queued`. */
export type LeftOut = Partial<
  Pick<
    Schemas['AcceptLeftOut'],
    'entry_id' | 'slug' | 'batch_id' | 'code' | 'text_ru' | 'alert_ru' | 'notified'
  >
> & { namesake?: AcceptNamesake | null };

/** Приставка фабрики в `text_ru` ролика не в копилке. */
export const LEFT_OUT_MARK = 'НЕ В КОПИЛКЕ: ';

/** `text_ru` без приставки «НЕ В КОПИЛКЕ: » (метка «Не в копилке» и так рядом). */
export function withoutMark(text: string | null | undefined): string {
  return (text ?? '').replace(/^\s*НЕ В КОПИЛКЕ:\s*/i, '').trim();
}

/**
 * Почему не в копилке — по коду очереди фабрики (`LEFT_OUT` в shared/runlog/acceptance.py:
 * другая версия размещена и пять отказов копилки). Неизвестный код — без причины.
 */
export const LEFT_OUT_REASON: Record<string, string> = {
  slug_taken: 'такое имя уже занято роликом другого батча',
  other_version_placed:
    'в копилке уже лежит другая версия этого ролика. Если это новый ролик, решает человек',
  batch_missing: 'фабрика не нашла батч ролика',
  render_missing: 'в батче нет файла ролика',
  channel_unknown: 'фабрика не смогла прочитать канал',
  queue_failed: 'не удалось скопировать ролик в копилку',
};

/** Дефис в названии не переносится: «USB\u2011C» и длинные имена не рвутся на телефоне. */
const unbroken = (s: string) => s.replace(/-/g, '\u2011');

/**
 * Главная строка метки: «Ролик «<название>» принят, но в копилку не попал: <причина>».
 * `title` — название, что центр показывает у ролика; нет — имя ролика словами.
 */
export function leftOutText(x: LeftOut, title?: string | null): string {
  const name = (title ?? '').trim() || (x.slug ? readableSlug(x.slug) : '');
  const who = name ? `Ролик «${unbroken(name)}»` : 'Ролик';
  const why = x.code ? LEFT_OUT_REASON[x.code] : undefined;
  return `${who} принят, но в копилку не попал${why ? `: ${why}` : ''}`;
}

/** Тёзка — видно одной строкой; путь и почему другой ролик — под «Подробнее». */
export function namesakeText(ns: AcceptNamesake | null | undefined): string | null {
  return ns && (ns.publish_path || ns.why || ns.entry_id) ? 'У того ролика другая тема' : null;
}

/** Ушло ли уведомление (`notified.status === 'sent'`); иначе — ничего, ответ шины под «подробнее». */
export function notifiedText(n: Record<string, unknown> | null | undefined): string | null {
  return n?.status === 'sent' ? 'Фабрика отправила уведомление' : null;
}
