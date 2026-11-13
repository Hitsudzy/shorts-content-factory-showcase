// Копилка канала (CC-0122; фабрика CF-0738/CF-0746, договор 0.53.0+): принятый ролик, которому
// ещё не дали слот, лежит в `publish/<канал>/_queue/`. Чтение — `GET /api/publish/{c}/stash`
// (ролики с подробностями, давность и пометка «устарел» — старше 14 дней от даты новости, у
// вечнозелёных — от принятия; только пометка, не отказ) и `not_queued` — принятые, что в копилку
// не легли. Записи — в два шага, как остальные записи публикации (./publishWrites): размещение
// пачкой на ближайшие свободные слоты (`…/stash/place/plan {order}` → `…/stash/place {confirm}`;
// API коммитит тронутые файлы сам) и «доложить в копилку» (`…/stash/repair/plan {entries}` →
// `…/stash/repair {confirm}`). Отказы — `StashProblem {message, code, details}`: сообщение уже
// по-русски, словами по коду их называет `stashProblemText`.
// CC-0180 (договор 0.78.0, фабрика CF-0918/CF-0919): у роликов `feed_kind`, `news_why`, `stale_at`,
// `reserve`, `video_id`, `bucket`, у копилки `news`, `reserve`, `horizon`; авто-раскладка — план
// `{auto, force?}`: порядок выбирает фабрика, что ждёт — в `skipped`; нечего ставить — `ok:false`,
// код `empty_order`.
// CC-0183 (фабрика CC-0182, CF-0920): у `StashSkipped` — `batch_id`, `slug` всегда простое имя (строка
// `beyond_horizon` раньше несла там `<батч>/<имя>`); `order` — `<батч>/<имя>`, тёзок различает батч.
// CC-0187 (фабрика CC-0186, CF-0921): `other_version` — принятые, которых правило не отличило от версии
// уже размещённого ролика; решает драйвер, центр только показывает (`repair` — данные, маршрута нет).
import { useQuery } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { NAMESAKES_TEXT, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { publishKeys } from './publish';

export type PublishStash = Schemas['PublishStash'];
export type StashVideo = Schemas['StashVideo'];
/** CC-0187 (фабрика CC-0186, CF-0921): принятый, не положенный как другая версия — только чтение. */
export type StashOtherVersion = Schemas['StashOtherVersion'];
export type StashAge = Schemas['StashAge'];
export type StashKindMark = Schemas['StashKindMark'];
export type StashCard = Schemas['StashCard'];
export type StashPlacePlan = Schemas['StashPlacePlan'];
export type StashPlaceResult = Schemas['StashPlaceResult'];
export type StashPlaceItem = Schemas['StashPlaceItem'];
export type StashRefusal = Schemas['StashRefusal'];
export type StashSkipped = Schemas['StashSkipped'];
export type StashHorizon = Schemas['StashHorizon'];
export type StashRepairPlan = Schemas['StashRepairPlan'];
export type StashRepairResult = Schemas['StashRepairResult'];
export type StashRepairItem = Schemas['StashRepairItem'];
export type StashProblem = Schemas['StashProblem'];
export type AcceptQueued = Schemas['AcceptQueued'];

/** Порог свежести по умолчанию (CF-0746), если фабрика его не назвала. */
export const STALE_DAYS = 14;

export const stashKey = (c: string) => [...publishKeys.all, 'stash', c] as const;

const ch = (channel: string) => ({ path: { channel } });

export async function getStash(channel: string, signal?: AbortSignal): Promise<PublishStash> {
  return takeBatch(await api.GET('/api/publish/{channel}/stash', { params: ch(channel), signal }));
}

/** Отказ 4xx (канала нет, очереди нет) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/**
 * Копилка канала. Один запрос на канал: блок «Копилка», «в копилке N» у карточек каналов и на
 * главной читают один и тот же кэш (свежий минуту), перечитывается раз в минуту и после любой
 * записи публикации (`publishKeys.all`).
 */
export function useStash(channel: string | null) {
  return useQuery({
    queryKey: stashKey(channel ?? ''),
    queryFn: ({ signal }) => getStash(channel!, signal),
    enabled: !!channel,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry,
  });
}

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

/** План размещения пачкой: ролики (`slug` или `<батч>/<slug>`) по порядку — на ближайшие слоты. */
export const planStashPlace = (channel: string, order: string[]) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/stash/place/plan', {
        params: ch(channel),
        body: { order, auto: false, force: false },
        signal,
      }),
    ),
  );

/** План авто-раскладки: порядок выбирает фабрика; `force` — брать и устаревшие новости. */
export const planStashAuto = (channel: string, force: boolean) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/stash/place/plan', {
        params: ch(channel),
        body: { auto: true, force },
        signal,
      }),
    ),
  );

export const stashPlace = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/stash/place', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

/** План «доложить в копилку»: записи приёмки из `not_queued` (null — все). */
export const planStashRepair = (channel: string, entries: string[] | null) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/stash/repair/plan', {
        params: ch(channel),
        body: { entries },
        signal,
      }),
    ),
  );

export const stashRepair = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/stash/repair', {
        params: ch(channel),
        body: { confirm },
        signal,
      }),
    ),
  );

/** Отказы копилки словами — заголовок над сообщением API (оно уже по-русски, код — в «подробнее»). */
export const STASH_PROBLEM_TEXT: Record<string, string> = {
  not_working_factory: 'Только смотреть: записи делает только API на рабочей фабрике',
  bad_who: 'Не записано, кто размещает',
  unknown_channel: 'Такого канала нет',
  no_queue: 'У канала нет очереди публикации: слот не задан',
  paused: 'Публикации канала на паузе — сначала снимите паузу',
  batch_open: 'Идёт батч — разложить можно, когда он закончится',
  empty_order: 'Не выбран ни один ролик',
  check_changed: 'С момента плана копилка или слоты изменились — посмотрите план заново',
  dirty: 'В папке публикации есть незакоммиченные правки — сначала их надо закоммитить',
  not_repo: 'Корень фабрики — не git-репозиторий: коммитить некуда',
  commit_refused: 'Ролики разложены, но коммит не прошёл — правки остались незакоммиченными',
  duplicate: 'Ролик выбран дважды',
  not_in_queue: 'Ролика уже нет в копилке',
  not_accepted: 'Ролик не принят',
  held: 'Ролик держит холд публикации',
  render_missing: 'Нет файла ролика',
  batch_missing: 'Батча ролика нет на диске',
  no_card: 'У ролика нет карточки',
  namesakes: NAMESAKES_TEXT,
  card_building: 'Карточка ролика ещё собирается — разложить можно, когда сборка закончится',
  card_not_ready: 'Карточка ролика не готова',
  note_differs: 'Карточка в копилке расходится с карточкой батча',
  no_slot: 'Свободного слота впереди не хватило',
  place_failed: 'Фабрика не смогла разместить ролик',
  not_found: 'Не найдено',
  invalid: 'Фабрика не приняла запрос',
  busy: 'Идёт другая запись публикации — подождите и нажмите ещё раз',
  confirm_unknown: 'Подтверждение не найдено или уже использовано — нужен новый план',
  confirm_expired: 'План устарел — запросите заново: подтверждение живёт две минуты',
  confirm_mismatch: 'Подтверждение было выдано другому действию и сгорело — нужен новый план',
  factory_broken:
    'Фабрика сломалась посреди записи — сначала посмотрите состояние, потом повторяйте',
};

export const stashProblemText = (code: string | null | undefined): string =>
  (code && STASH_PROBLEM_TEXT[code]) || 'Фабрика отказала';
