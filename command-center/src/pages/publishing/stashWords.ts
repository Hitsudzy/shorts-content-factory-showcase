// Копилка словами (CC-0122): давность принятия, возраст по правилу свежести CF-0746 (от даты
// новости, у вечнозелёных — от принятия; старше 14 дней — «устарел», только пометка), карточка,
// холд, название и адрес ролика на экране «Ролики».
import { readableSlug, withoutHashtags } from '@/api/videos';
import { STALE_DAYS, type StashAge, type StashKindMark, type StashVideo } from '@/api/stash';
import { plural, timeMsk } from '@/pages/batches/format';

const days = (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`;

const text = (x: unknown): string | null => (typeof x === 'string' && x.trim() ? x.trim() : null);

type Titled = Pick<StashVideo, 'slug'> & {
  title?: unknown;
  title_clean?: unknown;
  card?: { title?: unknown; title_clean?: unknown } | null;
};

/**
 * Название ролика копилки (CC-0128, договор 0.58.0): `title_clean` (название карточки без
 * « #shorts»), иначе — то же из карточки, иначе — название без хэштегов, иначе — читаемое имя.
 */
export function stashTitle(v: Titled): string {
  const raw = text(v.title) ?? text(v.card?.title);
  return (
    text(v.title_clean) ??
    text(v.card?.title_clean) ??
    (raw ? text(withoutHashtags(raw)) : null) ??
    readableSlug(v.slug)
  );
}

/**
 * Адрес ролика копилки и строка заказа размещения: `<батч>/<slug>` (или только `slug`, если батч
 * неизвестен). CC-0183: имя в копилке не единственно (CF-0920), всё, что различает строки, — по нему.
 */
export const stashKeyOf = (v: { slug: string; batch_id?: string | null }) =>
  v.batch_id ? `${v.batch_id}/${v.slug}` : v.slug;

/** CC-0183: тёзки копилки — имя и батчи его роликов; только имена с двумя роликами и больше. */
export type Namesakes = ReadonlyMap<string, readonly string[]>;

export function namesakesOf(videos: { slug: string; batch_id?: string | null }[]): Namesakes {
  const all = new Map<string, string[]>();
  for (const v of videos) {
    if (!v.batch_id) continue;
    const batches = all.get(v.slug) ?? [];
    if (!batches.includes(v.batch_id)) batches.push(v.batch_id);
    all.set(v.slug, batches);
  }
  return new Map([...all].filter(([, batches]) => batches.length > 1));
}

/**
 * Чем отличить ролик от тёзки — «батч от 4.11»; тёзки из батчей одного дня — со временем батча по
 * Москве («батч от 4.11, 05:00»); id батча не похож на дату — сам id. null — тёзки нет: строка как раньше.
 */
export function namesakeMark(
  names: Namesakes,
  slug: string,
  batchId: string | null | undefined,
): string | null {
  const batches = names.get(slug);
  if (!batches || !batchId) return null;
  const word = batchFrom(batchId);
  if (batches.filter((b) => batchFrom(b) === word).length < 2) return word;
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z/.exec(batchId);
  const time = m ? timeMsk(`${m[1]}T${m[2]}:${m[3]}:00Z`) : null;
  return time ? `${word}, ${time}` : `батч ${batchId}`;
}

/** Название и, у тёзки, его батч — для окон, подсказок и строк плана. */
export const withMark = (title: string, mark: string | null) =>
  mark ? `${title} · ${mark}` : title;

/** Название ролика по имени и, если известен, батчу; у тёзки к названию добавлен его батч. */
export type NameOf = (slug: string | null | undefined, batchId?: string | null) => string;

/**
 * Названия роликов копилки (`videos`) и «не в копилке» (`others`) — для плана, итога, отказов. Тёзки
 * считаются только в копилке: ролик «не в копилке» и так показан с батчем.
 */
export function stashTitles(videos: StashVideo[], others: StashVideo[] = []): NameOf {
  const names = namesakesOf(videos);
  const byKey = new Map<string, string>();
  const byName = new Map<string, string>();
  for (const v of [...videos, ...others]) {
    const title = stashTitle(v);
    byKey.set(stashKeyOf(v), title);
    if (!byName.has(v.slug)) byName.set(v.slug, title);
  }
  return (slug, batchId) => {
    if (!slug) return '—';
    const title =
      byKey.get(stashKeyOf({ slug, batch_id: batchId })) ?? byName.get(slug) ?? readableSlug(slug);
    return withMark(title, namesakeMark(names, slug, batchId));
  };
}

/**
 * CC-0183: у тёзки файл в копилке называется `<имя>~<батч>` (CF-0920). Это внутреннее дело фабрики:
 * оператор такого имени не видит ни в строках, ни в путях, и как адрес оно не годится (404).
 */
export const withoutBatchTail = (text: string) => text.replace(/(?<=[\w-])~[\w-]+/g, '');

/** «принят сегодня», «принят вчера», «принят 5 дней назад». */
export function acceptedAgo(n: number | null | undefined): string {
  if (n == null) return 'когда принят — неизвестно';
  if (n <= 0) return 'принят сегодня';
  if (n === 1) return 'принят вчера';
  return `принят ${days(n)} назад`;
}

/** «батч от 9.10» из id батча «2026-10-09T0200Z»; id не похож на дату — «батч». */
export function batchFrom(id: string | null | undefined): string {
  const m = id ? /^(\d{4})-(\d{2})-(\d{2})/.exec(id) : null;
  return m ? `батч от ${Number(m[3])}.${m[2]}` : 'батч';
}

/**
 * Строка фабрики без путей (CC-0128): «Будет положен в копилку: publish/…/x.mp4» → «Будет положен
 * в копилку»; путь посреди строки, в скобках или кавычках — тоже вон. Строка целиком — под
 * «Подробнее» у того, кто её показывает.
 */
export function withoutPath(text: string): string {
  return text
    .replace(/\s*[:—–]?\s*[(`«"]?(?:publish|pipeline|logs)\/[^\s,;)`»"]*[)`»"]?/g, '')
    .replace(/\(\s*\)/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([,.;])/g, '$1')
    .replace(/[\s:—–-]+$/, '')
    .trim();
}

/** «20.09» из ISO (день по МСК). */
function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: '2-digit',
    month: '2-digit',
  }).format(d);
}

/** Возраст ролика по правилу свежести: текст, пометка «устарел» и откуда считали — для подсказки. */
export function ageOf(
  age: StashAge,
  threshold: number = STALE_DAYS,
): { text: string; stale: boolean; tip: string } {
  const stale = age.stale === true;
  const rule = stale
    ? `Старше ${days(threshold)} — ролик помечен устаревшим. Это только пометка: разместить его можно.`
    : `Устаревшим ролик станет, когда возраст перевалит за ${days(threshold)}.`;
  if (age.basis === 'news' && age.days != null) {
    const at = shortDate(age.news_at);
    return {
      text: `новости ${age.days} дн.`,
      stale,
      tip: `Возраст считается от даты новости темы${at ? ` (${at})` : ''}: ${days(age.days)}. ${rule}`,
    };
  }
  if (age.basis === 'accepted' && age.days != null)
    return {
      text: age.days === 0 ? 'принят сегодня' : `принят ${age.days} дн. назад`,
      stale,
      tip: `У темы нет датированной новости (вечнозелёная) — возраст считается от принятия: ${days(age.days)}. ${rule}`,
    };
  return {
    text: 'возраст неизвестен',
    stale: false,
    tip: 'Ни даты новости, ни даты принятия у ролика нет — возраст не посчитать.',
  };
}

/**
 * Можно ли ставить в слот — по тому, что видно в копилке (последнее слово — у плана фабрики).
 * CC-0127: по `card.placeable` (готова или принята вашим решением), не по `ready` — у карточки,
 * принятой решением, `ready` строго false.
 */
export const placeable = (v: StashVideo) =>
  !v.held && v.card.present && (v.card.placeable ?? v.card.ready === true);

/** Батч ролика копилки `<канал>/<id>` (папка батча без `pipeline/`); null — не известен. */
export const stashBatch = (v: Pick<StashVideo, 'batch_dir' | 'batch_id' | 'channel'>) =>
  v.batch_dir?.replace(/^pipeline\//, '') || (v.batch_id ? `${v.channel}/${v.batch_id}` : null);

/** Адрес ролика на экране «Ролики»: `?batch=<папка батча>&v=<slug>`. */
export function videoHref(v: StashVideo): string | null {
  const batch = stashBatch(v);
  if (!batch) return null;
  const p = new URLSearchParams({ batch, v: v.slug });
  return `/videos?${p.toString()}`;
}

/** Порядок по умолчанию — по дате принятия, раньше принятые первыми. */
export function byAccepted(a: StashVideo, b: StashVideo): number {
  const x = a.accepted_at ? Date.parse(a.accepted_at) : Infinity;
  const y = b.accepted_at ? Date.parse(b.accepted_at) : Infinity;
  return x - y || a.slug.localeCompare(b.slug);
}

/** Порядок после перечитывания: прежний для оставшихся, новые — в конец по дате принятия. */
export function mergeOrder(prev: string[], videos: StashVideo[]): string[] {
  const keys = new Set(videos.map(stashKeyOf));
  const kept = prev.filter((k) => keys.has(k));
  const fresh = [...videos]
    .sort(byAccepted)
    .map(stashKeyOf)
    .filter((k) => !kept.includes(k));
  return [...kept, ...fresh];
}

/** Сдвинуть элемент на `by` (−1 вверх, +1 вниз). */
export function move<T>(list: T[], i: number, by: -1 | 1): T[] {
  const j = i + by;
  if (i < 0 || j < 0 || j >= list.length) return list;
  const out = [...list];
  [out[i], out[j]] = [out[j]!, out[i]!];
  return out;
}

/** «завтра, 01:00» из дня и метки слота («2026-10-14 01:00 МСК»). */
export function slotWhen(
  day: string | null | undefined,
  label: string | null | undefined,
  dayText: (d: string) => string,
): string {
  const time = label ? /\d{2}:\d{2}/.exec(label)?.[0] : null;
  if (!day) return label ?? '—';
  return time ? `${dayText(day)}, ${time}` : dayText(day);
}

/** CC-0180: ролик снят из ленты и лежит в запасе копилки (уже в Studio). */
export const inReserve = (v: Pick<StashVideo, 'reserve' | 'bucket'>) =>
  !!v.reserve || v.bucket === RESERVE_DAY;

/**
 * CC-0180: заметка запаса читается с `day=_reserve`, но маршруты записи (размещение карточки,
 * загрузка, запись из Studio) такой день не принимают — такие кнопки центр не предлагает.
 */
export const RESERVE_DAY = '_reserve';
export const RESERVE_WHY = 'Ролик в запасе: вернуть на день можно из копилки';

const KIND_WORD: Record<StashKindMark['kind'], string> = {
  news: 'новостной',
  evergreen: 'бессрочный',
};

/**
 * CC-0180: вид ролика поставлен вручную (`kind_mark`) — подпись для карточки копилки. Без пометки
 * вид определён по самому ролику. У новости с `news_why` это уже сказано строкой фабрики.
 */
export function kindMarkLabel(
  v: Pick<StashVideo, 'kind_mark' | 'feed_kind' | 'news_why'>,
): { text: string; tip: string } | null {
  if (!v.kind_mark || (v.feed_kind === 'news' && v.news_why)) return null;
  return {
    text: 'вид определён вручную',
    tip: `Вид поставлен вручную: ${KIND_WORD[v.kind_mark.kind] ?? v.kind_mark.kind}. По самому ролику он сейчас не определяется`,
  };
}

/** CC-0180: новость устарела — по пометке фабрики или по её дню `stale_at` (не позже сегодня). */
export function newsStale(
  v: Pick<StashVideo, 'feed_kind' | 'stale_at'> & { age: { stale?: boolean | null } },
  today: string,
): boolean {
  if (v.feed_kind !== 'news') return false;
  return v.age.stale === true || (!!v.stale_at && v.stale_at < today);
}

/** Почему авто-раскладка оставила ролик ждать — если фабрика не сказала по-русски. */
const SKIP_WORDS: Record<string, string> = {
  stale_news: 'Новость устарела, можно поставить вручную.',
  beyond_horizon: 'В горизонте ленты нет свободных слотов — ролик ждёт в копилке.',
  no_card: 'У ролика нет карточки.',
  card_building: 'Карточка ролика ещё собирается.',
  card_not_ready: 'Карточка ролика не готова.',
  note_differs: 'Карточка в копилке расходится с карточкой батча.',
};

/**
 * Причина пропуска словами: сообщение фабрики по-русски, слова по коду, иначе запасной текст. У
 * `stale_news` — всегда слова центра: сообщение фабрики называет `force`, оно — под «подробнее».
 */
export function skipReasonText(reason: string, message?: string | null): string {
  if (reason !== 'stale_news' && message && /[а-яё]/i.test(message)) return message;
  return SKIP_WORDS[reason] ?? 'Ролик пока ждёт в копилке — причина в «Подробнее».';
}

/**
 * CC-0187 (фабрика CC-0186, CF-0921): почему принятый ролик не положен как другая версия —
 * словами. `other_why` фабрики («темы нет в записи - новый ролик от версии не отличить»), иначе
 * `queue_text_ru` без скобок с записью, путей и хвоста с командой (команда — данные для драйвера,
 * на экран её не выводим). Ничего — общие слова.
 */
export function otherVersionWhy(v: { other_why?: unknown; queue_text_ru?: unknown }): string {
  const sentence = (s: string) => {
    const t = s
      .replace(/ +(?:-|—) /g, ' — ')
      .replace(/[\s.;:,—–-]+$/u, '')
      .trim();
    return t ? `${t[0]!.toUpperCase()}${t.slice(1)}.` : '';
  };
  const why = text(v.other_why);
  if (why) return sentence(why);
  const raw = text(v.queue_text_ru);
  if (raw) {
    const cut = raw
      .split(/\s*(?:Если это новый ролик|runlog |python3 |--)/)[0]!
      .replace(/\s*\([^)]*\)/g, '');
    const t = sentence(withoutPath(cut));
    if (t) return t;
  }
  return 'Правило не отличило новый ролик от версии уже размещённого.';
}

/** `<канал>/<батч>/<имя>` записи приёмки (`other_entry`) → канал, батч и имя; иначе null. */
export function entryParts(
  entry: string | null | undefined,
): { channel: string; batch: string; slug: string } | null {
  const m = entry ? /^([^/:]+)[/:]([^/:]+)[/:]([^/:]+)$/.exec(entry.trim()) : null;
  return m ? { channel: m[1]!, batch: m[2]!, slug: m[3]! } : null;
}

/**
 * CC-0187: куда вести на уже размещённую версию по её `publish_path`
 * (`publish/<канал>/<папка>/<имя>[~<батч>].mp4`, папка — день ленты, `_queue` или `_reserve`):
 * ключ слота экрана публикаций `<папка>/<имя>`, у файла с `~` — и батч. Другой канал или путь не
 * такого вида — null: тогда центр называет версию по имени и батчу.
 */
export function otherVersionSlot(
  path: string | null | undefined,
  channel: string,
): { slot: string; batch: string | null; where: string } | null {
  const m = path
    ? /^publish\/([^/]+)\/(\d{4}-\d{2}-\d{2}|_queue|_reserve)\/([^/~]+)(?:~([^/]+?))?\.(?:mp4|md)$/.exec(
        path.trim(),
      )
    : null;
  if (!m || m[1] !== channel) return null;
  const folder = m[2]!;
  const where =
    folder === '_queue'
      ? 'в копилке'
      : folder === '_reserve'
        ? 'в запасе'
        : `в ленте на ${Number(folder.slice(8))}.${folder.slice(5, 7)}`;
  return { slot: `${folder}/${m[3]!}`, batch: m[4] ?? null, where };
}
