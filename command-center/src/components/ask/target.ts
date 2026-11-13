// О чём просьба оператору (CC-0019): экран, канал, батч, ролик. Кнопка «попросить» на ролике,
// батче и канале подставляет это сама, общая кнопка в шапке — только экран. В очередь уходит
// JSON (`context` у `POST /api/requests`), человеку — строки «Откуда» словами; сам JSON —
// только под «подробнее».
import { AREAS } from '@/app/areas';

/** Кто исполняет просьбу и куда придёт ответ — тултип окна и кнопок «попросить». */
export const ASK_TIP =
  'Просьбу возьмёт сессия-оператор (Claude в терминале). Центр сам ничего не исполняет — он только ставит просьбу в очередь. Ответ придёт сюда, в «Вопросы» → «Просьбы», и в Telegram';

/** Что подставить в просьбу. Подписи (`*Title`) — для человека, id — для оператора. */
export type AskTarget = {
  channel?: string | null;
  batch?: string | null;
  batchTitle?: string | null;
  video?: string | null;
  videoTitle?: string | null;
};

/** Контекст просьбы, как он лежит в очереди (`context`). */
export type AskContext = {
  screen: string;
  area: string;
  channel?: string;
  batch?: string;
  batch_title?: string;
  video?: string;
  video_title?: string;
};

/** Имя экрана по адресу: таб центра, на котором нажали «попросить». */
export function areaOf(pathname: string): string {
  const seg = pathname.replace(/^\/+/, '').split('/')[0] ?? '';
  return AREAS.find((a) => a.path === seg)?.title ?? 'Командный центр';
}

/** Контекст для очереди: адрес экрана и то, что подставила кнопка; пустое не пишем. */
export function contextOf(location: { pathname: string; search: string }, t: AskTarget = {}) {
  const ctx: AskContext = {
    screen: location.pathname + location.search,
    area: areaOf(location.pathname),
  };
  if (t.channel) ctx.channel = t.channel;
  if (t.batch) ctx.batch = t.batch;
  if (t.batchTitle) ctx.batch_title = t.batchTitle;
  if (t.video) ctx.video = t.video;
  if (t.videoTitle) ctx.video_title = t.videoTitle;
  return ctx;
}

export type ContextRow = {
  key: 'area' | 'channel' | 'batch' | 'video';
  label: string;
  value: string;
};

const text = (o: Record<string, unknown>, k: string) =>
  typeof o[k] === 'string' && o[k] ? (o[k] as string) : null;

/**
 * «Откуда» словами — из контекста любой формы (его мог записать и не центр): экран, канал,
 * батч, ролик. Незнакомое не показывается — оно есть под «подробнее».
 */
export function contextRows(
  context: unknown,
  channelName: (id: string) => string,
  channel?: string | null,
): ContextRow[] {
  const o =
    typeof context === 'object' && context !== null && !Array.isArray(context)
      ? (context as Record<string, unknown>)
      : {};
  const rows: ContextRow[] = [];
  const area =
    text(o, 'area') ?? (text(o, 'screen') ? areaOf(text(o, 'screen')!.split('?')[0]!) : null);
  if (area) rows.push({ key: 'area', label: 'Экран', value: area });
  const ch = text(o, 'channel') ?? channel ?? null;
  if (ch) rows.push({ key: 'channel', label: 'Канал', value: channelName(ch) });
  const batch = text(o, 'batch_title') ?? text(o, 'batch');
  if (batch) rows.push({ key: 'batch', label: 'Батч', value: batch });
  const videoTitle = text(o, 'video_title');
  if (videoTitle) rows.push({ key: 'video', label: 'Ролик', value: `«${videoTitle}»` });
  else if (text(o, 'video')) rows.push({ key: 'video', label: 'Ролик', value: text(o, 'video')! });
  return rows;
}
