// Перенос размещённых роликов (CC-0166; фабрика CC-0165/CF-0856, договор 0.73.0): ролик из папки
// дня — на другой день, а ещё не попавший в Studio — обратно в копилку. Пачка правок судится
// целиком (порядок не важен): «25→24, 26→25 и 24-й в копилку» проходит, без возврата 24-го оба
// переноса — `day_taken`. Два шага, как остальные записи публикации: план
// `POST …/{c}/move/plan {moves, unplace}` ничего не пишет и даёт токен на 120 с, только когда
// годится каждая правка; «да» — `POST …/{c}/move/confirm {confirm, base_sha256}` (данные
// изменились с плана — 409 `check_changed`; идёт батч — 409 `batch_open`, только здесь).
// Фабрика коммитит сама. Ролик уже в Studio переносится правкой журнала загрузок, а дату в Studio
// ставит человек — строка фабрики `STUDIO …` в предупреждениях правки.
// CC-0180 (договор 0.78.0, фабрика CF-0918): `withdraw` — снять ролик из Studio из ленты в запас
// копилки; день снятого можно занять в этом же плане. Studio центр не проверяет: «Ограниченный
// доступ» ставит человек. Ролик запаса возвращается переносом на день: `reserve`, `from_day` null,
// новой загрузки нет. Отказы — `MoveRefusal` с русским `message` (план: 200 без токена; «да»: 409).
// CC-0183 (фабрика CC-0182, CF-0920): тёзка называется батчем — `moves[].batch_id`, в `unplace` и
// `withdraw` — строка `<батч>/<имя>` (голое имя там значит ролик в папке дня).
import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { NAMESAKES_TEXT, takeBatch } from './batchProblem';
import { api, type Schemas } from './client';

export type MovePlan = Schemas['MovePlan'];
export type MoveResult = Schemas['MoveResult'];
export type MoveItem = Schemas['MoveItem'];
export type MoveEdit = Schemas['MoveEdit'];
export type MoveRefusal = Schemas['MoveRefusal'];
export type MoveBody = { moves: MoveEdit[]; unplace: string[]; withdraw?: string[] };

/** Больше правок за раз фабрика не принимает (422). */
export const MOVE_MAX_EDITS = 60;

const ch = (channel: string) => ({ path: { channel } });
const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

export const planMove = (channel: string, body: MoveBody) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/move/plan', {
        params: ch(channel),
        body,
        signal,
      }),
    ),
  );

/** «Да»: токен плана и его `base_sha256` — фабрика сверит, что данные не менялись с плана. */
export const confirmMove = (channel: string, confirm: string, base: string | null | undefined) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/publish/{channel}/move/confirm', {
        params: ch(channel),
        body: base ? { confirm, base_sha256: base } : { confirm },
        signal,
      }),
    ),
  );

/** Строка фабрики про Studio: ролик уже там, дату в Studio ставят руками. */
export const isStudioLine = (w: string) => /^STUDIO\b/.test(w.trim());

/** Отказы переноса словами — заголовок над сообщением API (оно по-русски, код — в «подробнее»). */
export const MOVE_PROBLEM_TEXT: Record<string, string> = {
  not_working_factory: 'Только смотреть: записи делает только API на рабочей фабрике',
  bad_who: 'Не записано, кто переносит',
  unknown_channel: 'Такого канала нет',
  no_queue: 'У канала нет очереди публикации: слот не задан',
  empty_order: 'Не выбран ни один ролик',
  batch_open: 'Идёт батч — переносить можно, когда он закончится',
  check_changed: 'С момента плана слоты или журнал загрузок изменились — посмотрите план заново',
  apply_failed: 'Фабрика не смогла перенести — ничего не записано',
  commit_refused: 'Перенесено, но коммит не прошёл — правки остались незакоммиченными',
  dirty: 'В папке публикации есть незакоммиченные правки — сначала их надо закоммитить',
  not_repo: 'Корень фабрики — не git-репозиторий: коммитить некуда',
  bad_order: 'Фабрика не приняла список правок',
  invalid: 'Фабрика не приняла запрос',
  busy: 'Идёт другая запись публикации — подождите и нажмите ещё раз',
  confirm_unknown: 'Подтверждение не найдено или уже использовано — нужен новый план',
  confirm_expired: 'План устарел — запросите заново: подтверждение живёт две минуты',
  confirm_mismatch: 'Подтверждение было выдано другому действию и сгорело — нужен новый план',
  not_found: 'Не найдено',
  factory_broken:
    'Фабрика сломалась посреди записи — сначала посмотрите состояние, потом повторяйте',
  // CC-0180: отказы правки на «да» (409), если с плана что-то изменилось.
  not_in_studio: 'Ролика нет в Studio — снимать из ленты нечего',
  in_reserve: 'Ролик уже снят из ленты и лежит в запасе',
  not_placed: 'У ролика есть строка журнала, но нет пары в папке дня',
  published: 'Слот ролика уже прошёл — опубликованный ролик не трогаем',
  duplicate: 'Ролик назван в плане дважды',
  ambiguous: 'Ролик лежит в нескольких местах сразу — нужен человек',
  namesakes: NAMESAKES_TEXT,
  inconsistent: 'Папка дня и журнал загрузок называют разные дни',
  in_queue: 'Ролик и так в копилке без слота',
  reserve_taken: 'Место занято роликом из запаса',
};

export const moveProblemText = (code: string | null | undefined): string =>
  (code && MOVE_PROBLEM_TEXT[code]) || 'Фабрика отказала';
