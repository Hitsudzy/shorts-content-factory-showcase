// Публикация (CC-0064 фабрики, договор 0.18.0+; центр собран под 0.20.0) — только чтение:
// очереди каналов в строку (`GET /api/publish`), лента слотов канала на N дней с занявшими их
// роликами (`…/queue?days`), пауза, переключатель API-загрузки, ротация, серия Studio без правок,
// холды публикации и карточка ролика в папке дня (`…/notes/{slug}?day`) с полями для Studio.
// Записи (пауза, карточка, ротация, переключатель, загрузка, отметка Studio) — CC-0068/0069.
// Отказы — `{message, code, details}` (PublishProblem), их разбирает `takeBatch` (./batchProblem).
import { useQueries, useQuery } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type PublishOverview = Schemas['PublishOverview'];
export type QueueLine = Schemas['QueueLine'];
export type SlotRule = Schemas['SlotRule'];
export type Tomorrow = Schemas['Tomorrow'];
export type ChannelQueue = Schemas['ChannelQueue'];
export type QueueSlot = Schemas['QueueSlot'];
export type Occupant = Schemas['Occupant'];
export type WithdrawnRow = Schemas['WithdrawnRow'];
export type UploadWithdrawn = Schemas['UploadWithdrawn'];
export type ChannelPause = Schemas['ChannelPause'];
export type PauseRow = Schemas['PauseRow'];
export type ApiUpload = Schemas['ApiUpload'];
export type ApiSwitchState = Schemas['ApiSwitchState'];
export type ChannelRotation = Schemas['ChannelRotation'];
export type RotationReport = Schemas['RotationReport'];
export type ChannelStudio = Schemas['ChannelStudio'];
export type StudioStreak = Schemas['StudioStreak'];
export type PublicationHolds = Schemas['PublicationHolds'];
export type HoldRow = Schemas['HoldRow'];
export type ReleasedHolds = Schemas['ReleasedHolds'];
export type ReleasedHold = Schemas['ReleasedHold'];
export type PublishNote = Schemas['PublishNote'];
export type StudioFields = Schemas['StudioFields'];
export type FormField = Schemas['FormField'];
export type PublishProblem = Schemas['PublishProblem'];

/** Сколько дней ленты показывает экран (= `publish_queue.py show --days` по умолчанию). */
export const FEED_DAYS = 14;
/** Окно снятых холдов (`GET /api/publish/holds/released?days`, 1–90), CC-0170. */
export const RELEASED_DAYS = 14;

const path = (channel: string) => ({ path: { channel } });

export async function getPublishOverview(signal?: AbortSignal): Promise<PublishOverview> {
  return takeBatch(await api.GET('/api/publish', { signal }));
}

export async function getQueue(
  channel: string,
  days = FEED_DAYS,
  signal?: AbortSignal,
): Promise<ChannelQueue> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/queue', {
      params: { ...path(channel), query: { days } },
      signal,
    }),
  );
}

export async function getPause(channel: string, signal?: AbortSignal): Promise<ChannelPause> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/pause', { params: path(channel), signal }),
  );
}

export async function getApiUpload(channel: string, signal?: AbortSignal): Promise<ApiUpload> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/api-upload', { params: path(channel), signal }),
  );
}

export async function getRotation(channel: string, signal?: AbortSignal): Promise<ChannelRotation> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/rotation', { params: path(channel), signal }),
  );
}

export async function getStudio(channel: string, signal?: AbortSignal): Promise<ChannelStudio> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/studio', { params: path(channel), signal }),
  );
}

export async function getHolds(
  channel: string | null,
  signal?: AbortSignal,
): Promise<PublicationHolds> {
  return takeBatch(
    await api.GET('/api/publish/holds', {
      params: { query: channel ? { channel } : {} },
      signal,
    }),
  );
}

/** Снятые за `days` дней холды (и снова поставленные правилом сцен), новые первыми — CC-0170. */
export async function getReleasedHolds(
  channel: string | null,
  days = RELEASED_DAYS,
  signal?: AbortSignal,
): Promise<ReleasedHolds> {
  return takeBatch(
    await api.GET('/api/publish/holds/released', {
      params: { query: channel ? { channel, days } : { days } },
      signal,
    }),
  );
}

export async function getNote(
  channel: string,
  slug: string,
  day: string | null,
  signal?: AbortSignal,
  /** CC-0183: какой из двух роликов одного имени в копилке; без тёзки не нужен. */
  batchId?: string | null,
): Promise<PublishNote> {
  return takeBatch(
    await api.GET('/api/publish/{channel}/notes/{slug}', {
      params: {
        path: { channel, slug },
        query: { ...(day ? { day } : {}), ...(batchId ? { batch_id: batchId } : {}) },
      },
      signal,
    }),
  );
}

export const publishKeys = {
  all: ['api', 'publish'] as const,
  overview: ['api', 'publish', 'overview'] as const,
  queue: (c: string, days: number) => ['api', 'publish', 'queue', c, days] as const,
  pause: (c: string) => ['api', 'publish', 'pause', c] as const,
  apiUpload: (c: string) => ['api', 'publish', 'api-upload', c] as const,
  rotation: (c: string) => ['api', 'publish', 'rotation', c] as const,
  studio: (c: string) => ['api', 'publish', 'studio', c] as const,
  holds: (c: string | null) => ['api', 'publish', 'holds', c ?? ''] as const,
  released: (c: string | null, days: number) =>
    ['api', 'publish', 'holds-released', c ?? '', days] as const,
  note: (c: string, slug: string, day: string | null, batchId?: string | null) =>
    ['api', 'publish', 'note', c, slug, day ?? '', batchId ?? ''] as const,
};

/** Отказ 4xx (канала нет, очередь не читается) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Состояние публикации меняется из терминала и по таймеру: перечитываем раз в минуту. */
const live = { refetchInterval: 60_000, refetchIntervalInBackground: false, retry } as const;

/** Очереди всех каналов публикации в строку. */
export function usePublishOverview() {
  return useQuery({
    queryKey: publishKeys.overview,
    queryFn: ({ signal }) => getPublishOverview(signal),
    ...live,
  });
}

export function useQueue(channel: string | null, days = FEED_DAYS) {
  return useQuery({
    queryKey: publishKeys.queue(channel ?? '', days),
    queryFn: ({ signal }) => getQueue(channel!, days, signal),
    enabled: !!channel,
    ...live,
  });
}

export function usePause(channel: string | null) {
  return useQuery({
    queryKey: publishKeys.pause(channel ?? ''),
    queryFn: ({ signal }) => getPause(channel!, signal),
    enabled: !!channel,
    ...live,
  });
}

export function useApiUpload(channel: string | null) {
  return useQuery({
    queryKey: publishKeys.apiUpload(channel ?? ''),
    queryFn: ({ signal }) => getApiUpload(channel!, signal),
    enabled: !!channel,
    ...live,
  });
}

/** Ротация меняется только с новым батчем: без опроса, по открытию канала. */
export function useRotation(channel: string | null) {
  return useQuery({
    queryKey: publishKeys.rotation(channel ?? ''),
    queryFn: ({ signal }) => getRotation(channel!, signal),
    enabled: !!channel,
    retry,
  });
}

export function useStudio(channel: string | null) {
  return useQuery({
    queryKey: publishKeys.studio(channel ?? ''),
    queryFn: ({ signal }) => getStudio(channel!, signal),
    enabled: !!channel,
    ...live,
  });
}

/** Холды публикации канала (null — всех). Холд с `signable: true` центр подписывает (./publishWrites). */
export function useHolds(channel: string | null) {
  return useQuery({
    queryKey: publishKeys.holds(channel),
    queryFn: ({ signal }) => getHolds(channel, signal),
    ...live,
  });
}

/** Снятые холды канала за `days` дней (CC-0170): строка фабрики `release.line_ru` на каждый. */
export function useReleasedHolds(channel: string | null, days = RELEASED_DAYS) {
  return useQuery({
    queryKey: publishKeys.released(channel, days),
    queryFn: ({ signal }) => getReleasedHolds(channel, days, signal),
    ...live,
  });
}

/** Карточка ролика в папке дня и поля для Studio — по выбору слота. */
export function useNote(
  channel: string | null,
  slug: string | null,
  day: string | null,
  batchId?: string | null,
) {
  return useQuery({
    queryKey: publishKeys.note(channel ?? '', slug ?? '', day, batchId),
    queryFn: ({ signal }) => getNote(channel!, slug!, day, signal, batchId),
    enabled: !!channel && !!slug,
    retry,
  });
}

/** Ленты слотов нескольких каналов сразу (главная, CC-0138): те же ключи и опрос, что у `useQueue`. */
export function useQueues(channels: readonly string[], days = FEED_DAYS) {
  return useQueries({
    queries: channels.map((c) => ({
      queryKey: publishKeys.queue(c, days),
      queryFn: ({ signal }: { signal: AbortSignal }) => getQueue(c, days, signal),
      ...live,
    })),
  });
}

/** Занятые слоты ленты, у которых есть карточка в папке дня (`publish/…`). */
export function slotsWithNote(q: ChannelQueue | undefined): { slug: string; day: string }[] {
  return (q?.slots ?? []).flatMap((s) => {
    const o = q ? occupantOf(q, s) : undefined;
    return s.taken_by && o?.sources.some((x) => x.startsWith('publish/'))
      ? [{ slug: s.taken_by, day: s.day }]
      : [];
  });
}

/** Карточки роликов разных каналов: по каналу, дню и имени ролика (CC-0138). */
export function useNotesOf(wanted: readonly { channel: string; slug: string; day: string }[]) {
  const results = useQueries({
    queries: wanted.map((w) => ({
      queryKey: publishKeys.note(w.channel, w.slug, w.day),
      queryFn: ({ signal }: { signal: AbortSignal }) => getNote(w.channel, w.slug, w.day, signal),
      retry,
    })),
  });
  const byKey = new Map<string, SlotNote>();
  wanted.forEach((w, i) => {
    const r = results[i];
    if (r)
      byKey.set(`${w.channel}/${w.day}/${w.slug}`, {
        note: r.data,
        pending: r.isPending,
        failed: r.isError,
      });
  });
  /** Карточка слота; undefined — у слота её нет (свободен или только в журнале загрузок). */
  return (channel: string, day: string, slug: string): SlotNote | undefined =>
    byKey.get(`${channel}/${day}/${slug}`);
}

/**
 * Карточки занятых слотов ленты (название и готовность) — только тех, у кого есть папка дня:
 * ролик, известный лишь журналу загрузок, карточки в `publish/` не имеет.
 */
export function useSlotNotes(channel: string | null, q: ChannelQueue | undefined) {
  const wanted = channel ? slotsWithNote(q).map((w) => ({ ...w, channel })) : [];
  const of = useNotesOf(wanted);
  return (day: string, slug: string): SlotNote | undefined =>
    channel ? of(channel, day, slug) : undefined;
}

export type SlotNote = { note: PublishNote | undefined; pending: boolean; failed: boolean };

/** Занявший слот ролик уже загружен в YouTube: его строка есть в журнале загрузок. */
export const isUploaded = (o: Occupant | undefined) =>
  !!o?.sources.some((s) => s.startsWith('uploads.json'));

/** Кто занимает слот: по дню и имени ролика (у ленты — только имя, источник — в `occupants`). */
export function occupantOf(q: ChannelQueue, slot: QueueSlot): Occupant | undefined {
  if (!slot.taken_by) return undefined;
  return (
    q.occupants.find((o) => o.slug === slot.taken_by && o.day === slot.day) ??
    q.occupants.find((o) => o.slug === slot.taken_by)
  );
}

/** Время слота ещё впереди (лента фабрики начинается с сегодняшнего дня, и прошедший слот в ней есть). */
export const isAhead = (q: ChannelQueue, s: QueueSlot) => Date.parse(s.at) >= Date.parse(q.as_of);

/**
 * Слот, карточку которого экран открывает сам: ближайший занятый, ещё не загруженный ролик
 * (его поля сейчас нужны в Studio); все загружены — ближайший впереди с карточкой в папке дня
 * (поля для сверки); нет и такого — ничего.
 */
export function defaultSlot(q: ChannelQueue): QueueSlot | undefined {
  const ahead = q.slots.filter((s) => s.taken_by && isAhead(q, s));
  return (
    ahead.find((s) => !isUploaded(occupantOf(q, s))) ??
    ahead.find((s) => occupantOf(q, s)?.sources.some((x) => x.startsWith('publish/')))
  );
}
