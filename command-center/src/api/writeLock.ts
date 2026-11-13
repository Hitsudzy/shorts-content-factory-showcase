// CC-0084: записи в полёте — один учёт на весь центр. Каждый не-GET запрос клиента `api`
// (`client.ts` оборачивает POST/PUT/PATCH/DELETE) регистрируется здесь со своей подписью и
// снимается по ответу фабрики — успех, отказ, сеть или таймаут (`finally`). Слой `WriteLock`
// в шапке читает этот учёт и замораживает интерфейс, пока он не пуст. Чтения (GET) сюда не
// попадают вовсе, а POST, которые ничего не пишут (проверка канала, сухой прогон «нового
// канала» — он идёт сам, пока человек печатает), помечены в таблице `null`.
import { useSyncExternalStore } from 'react';

export type WriteKind = 'write' | 'plan';

export type WriteLabel = {
  /** Что идёт, словами: «Сохраняю отметки…». */
  title: string;
  /** План (запрос с токеном подтверждения, до «да»): короткий, ничего ещё не записано. */
  kind: WriteKind;
  /** Долгая запись: потолок ожидания центра, мс (слой пишет «это может занять до …»). */
  upToMs?: number;
};

export type WriteInFlight = WriteLabel & { id: number };

type Entry = string | { title: string; upToMs: number } | null;

/**
 * Подпись каждой записи договора: `МЕТОД путь` (как в контракте, без `/plan`). `null` — POST,
 * который ничего не пишет: слой не нужен. Новый маршрут записи без строки здесь ловит тест
 * (`writeLock.test.ts` сверяет с `openapi.snapshot.json`), а до того получает «Записываю…».
 * Потолки долгих — те же, что ждёт центр: `UPLOAD_TIMEOUT_MS`, `STOP_TIMEOUT_MS`, `PLAN_TIMEOUT_MS`, `ARCHIVE_TIMEOUT_MS`
 * (тест сверяет; импорта нет — клиент API не тянет модули записей).
 */
export const WRITE_LABELS: Readonly<Record<string, Entry>> = {
  'POST /api/questions/{qid}/answer': 'Записываю ответ на вопрос…',
  'POST /api/questions/{qid}/resolve': 'Отмечаю вопрос решённым…',
  'POST /api/requests': 'Отправляю просьбу оператору…',
  'POST /api/requests/{rid}/close': 'Закрываю просьбу…',
  'POST /api/requests/{rid}/cancel': 'Отменяю просьбу…',
  'POST /api/channels': 'Создаю канал на фабрике…',
  'PUT /api/channels/{channel}': 'Сохраняю конфиг канала…',
  'POST /api/channels/{channel}/check': null,
  // CC-0037: вход и выход фабрику не трогают (только кука сессии этого браузера) и идут мимо
  // клиента `api` (`src/api/auth.ts`) — слоя записи на них нет.
  'POST /api/auth/login': null,
  'POST /api/auth/logout': null,
  'POST /api/channels/{channel}/history/{commit}/revert': 'Отменяю правку канала…',
  'POST /api/schedule/switch': 'Переключаю расписание…',
  'PUT /api/schedule/channels/{channel}': 'Сохраняю расписание канала…',
  'POST /api/batches/launch': 'Запускаю батч…',
  'POST /api/batches/{channel}/{batch_id}/stop': {
    title: 'Останавливаю батч…',
    upToMs: 70_000,
  },
  'POST /api/batches/{channel}/{batch_id}/resume': 'Продолжаю батч…',
  'POST /api/batches/{channel}/{batch_id}/rebuild': {
    title: 'Запускаю пересборку…',
    upToMs: 30_000,
  },
  'POST /api/batches/{channel}/{batch_id}/videos/{slug}/acceptance': 'Записываю приёмку ролика…',
  'POST /api/analytics/{channel}/studio/record': 'Вношу цифры из Studio…',
  'POST /api/publish/{channel}/pause/set': 'Ставлю канал на паузу…',
  'POST /api/publish/{channel}/pause/clear': 'Снимаю паузу канала…',
  'POST /api/publish/{channel}/card/place': 'Выкладываю карточку…',
  'POST /api/publish/{channel}/card/build': 'Собираю карточку…',
  'POST /api/publish/{channel}/rotation/assign': 'Назначаю пары…',
  'POST /api/publish/{channel}/rotation/reject': 'Записываю отклонение пары…',
  'POST /api/publish/{channel}/rotation/refuse': 'Записываю отказ за нехваткой материала…',
  'POST /api/publish/{channel}/holds/{batch_id}/{topic_id}/sign': 'Подписываю холд…',
  'POST /api/publish/{channel}/api-upload/switch': 'Переключаю загрузку через API…',
  'POST /api/publish/{channel}/upload': {
    title: 'Загружаю ролик на YouTube…',
    upToMs: 20 * 60_000,
  },
  'POST /api/publish/{channel}/studio/record': 'Записываю загрузку из Studio…',
  'PUT /api/memes/{channel}/marks': 'Сохраняю отметки…',
  'POST /api/memes/{channel}/apply': 'Применяю разбор…',
  // CC-0132/CC-0133 (договор 0.62.0): «да» запускает фоновую задачу банка — ответ сразу.
  'POST /api/memes/{channel}/cutout': 'Запускаю вырезку фона…',
  'POST /api/memes/{channel}/trim': 'Запускаю обрезку пустых полей…',
  'POST /api/memes/{channel}/add-image': 'Запускаю добавление картинки…',
  'POST /api/memes/{channel}/add-gif': 'Запускаю нарезку гифки…',
  'POST /api/memes/{channel}/sheet': 'Запускаю контакт-лист кадров…',
  'POST /api/memes/{channel}/embed': 'Запускаю пересчёт признаков для поиска похожих мемов…',
  'POST /api/notify/reminders': 'Ставлю напоминание…',
  'POST /api/oauth/api-data/purge': 'Удаляю данные API…',
  // Записи договора 0.29.0…0.44.0 — экранов пока нет (CC-0087, CC-0031, CC-0033, …), подписи — уже.
  'POST /api/batches/{channel}/{batch_id}/videos/{slug}/withdraw': 'Снимаю ролик…',
  'POST /api/publish/{channel}/studio/edited': 'Записываю правку в Studio…',
  'POST /api/publish/{channel}/studio/edited/undo': 'Отменяю отметку о правке в Studio…',
  'POST /api/notify/reminders/{rid}/cancel': 'Отменяю напоминание…',
  'POST /api/notify/test-send': 'Отправляю пробное уведомление…',
  'POST /api/oauth/revoke': 'Отзываю доступ…',
  'POST /api/oauth/api-data/auto': 'Удаляю данные API по правилам…',
  'POST /api/maintenance/journals': 'Чищу журналы…',
  'POST /api/maintenance/pool/release': 'Освобождаю пул…',
  'POST /api/maintenance/archive': {
    title: 'Архивирую месяц публикаций…',
    upToMs: 65 * 60_000,
  },
  // Записи договора 0.45.0…0.54.0 — экранов пока нет (CC-0114, CC-0119, CC-0120, CC-0122, CC-0123, …).
  'POST /api/batches/{channel}/{batch_id}/rerun-from': 'Повторяю батч со стадии…',
  'POST /api/channels/{channel}/ending': 'Запускаю рендер концовки…',
  'POST /api/channels/{channel}/fact-sources': 'Записываю источники фактов…',
  'POST /api/channels/{channel}/footage-origin': 'Записываю источники футажа…',
  'POST /api/channels/{channel}/affiliate': 'Записываю партнёрские ссылки…',
  'POST /api/gate-prices/{rule}/sign': 'Подписываю цену воротец…',
  'POST /api/gate-prices/{rule}/decide': 'Записываю решение по воротцам…',
  'POST /api/memes/{channel}/candidates/accept': 'Принимаю кандидатов в банк мемов…',
  'POST /api/publish/{channel}/stash/place': 'Ставлю ролики из копилки в слоты…',
  'POST /api/publish/{channel}/stash/repair': 'Кладу принятые ролики в копилку…',
  // Договор 0.73.0 (CC-0166): перенос размещённых роликов и возврат в копилку.
  'POST /api/publish/{channel}/move/confirm': 'Переношу ролики по дням…',
  'POST /api/studio/read': 'Запускаю чтение Studio…',
  // Договор 0.55.0…0.56.0 (CC-0127): карточка без оператора — сборка заново и решение пользователя.
  'POST /api/publish/{channel}/cards/{slug}/build': 'Запускаю сборку карточки…',
  'POST /api/publish/{channel}/cards/{slug}/ruling': 'Записываю ваше решение по карточке…',
};

export const PLAN_TITLE = 'Готовлю план…';
export const FALLBACK_TITLE = 'Записываю…';

const PLAN_SUFFIX = /\/plan$/;

/** Подпись записи по методу, пути контракта и телу; `null` — запрос ничего не пишет. */
export function writeLabel(method: string, schemaPath: string, body?: unknown): WriteLabel | null {
  const m = method.toUpperCase();
  if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return null;
  if (PLAN_SUFFIX.test(schemaPath)) return { title: PLAN_TITLE, kind: 'plan' };
  // Сухой прогон «нового канала» (`dry_run: true`) — фоновая проверка по мере ввода.
  if (m === 'POST' && schemaPath === '/api/channels' && isDryRun(body)) return null;
  const entry = WRITE_LABELS[`${m} ${schemaPath}`];
  if (entry === null) return null;
  if (entry === undefined) return { title: FALLBACK_TITLE, kind: 'write' };
  if (typeof entry === 'string') return { title: entry, kind: 'write' };
  return { title: entry.title, kind: 'write', upToMs: entry.upToMs };
}

let probing = 0;

/**
 * CC-0094: фоновая проверка — план (`…/plan`), которого человек не начинал (центр сам
 * спрашивает `resume/plan`, жив ли исполнитель батча). Слой записи на неё не встаёт: план
 * ничего не пишет, а замораживать экран раз в минуту без действия человека нельзя. Запрос
 * должен уйти синхронно внутри `call` (как у `planResume`); запись под `probe` всё равно
 * идёт под слоем.
 */
export function probe<T>(call: () => T): T {
  probing++;
  try {
    return call();
  } finally {
    probing--;
  }
}

/** Подпись записи для учёта: `writeLabel`, но план внутри `probe` — без слоя. */
export function lockLabel(method: string, schemaPath: string, body?: unknown): WriteLabel | null {
  const label = writeLabel(method, schemaPath, body);
  return label?.kind === 'plan' && probing > 0 ? null : label;
}

function isDryRun(body: unknown): boolean {
  return (
    typeof body === 'object' && body !== null && (body as { dry_run?: unknown }).dry_run === true
  );
}

/** «до 20 минут», «до 70 секунд»: потолок ожидания словами (без ложной точности). */
export function upToText(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s >= 60 && s % 60 === 0) {
    const min = s / 60;
    return `до ${min} ${plural(min, 'минуты', 'минут', 'минут')}`;
  }
  return `до ${s} ${plural(s, 'секунды', 'секунд', 'секунд')}`;
}

/** Родительный после «до»: «до 1 минуты», «до 2 минут», «до 21 минуты». */
function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return one;
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return few;
  return many;
}

// ---- учёт ----

let seq = 0;
let inFlight: readonly WriteInFlight[] = [];
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

/** Запись ушла: слой включается сразу. Возвращает «запись ответила» (повтор — без вреда). */
export function beginWrite(label: WriteLabel): () => void {
  const id = ++seq;
  inFlight = [...inFlight, { ...label, id }];
  emit();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    inFlight = inFlight.filter((w) => w.id !== id);
    emit();
  };
}

/** Выполнить запрос под учётом: `label === null` — без слоя. Снимается при любом исходе. */
export async function trackWrite<T>(label: WriteLabel | null, run: () => Promise<T>): Promise<T> {
  if (!label) return run();
  const end = beginWrite(label);
  try {
    return await run();
  } finally {
    end();
  }
}

export function getWritesInFlight(): readonly WriteInFlight[] {
  return inFlight;
}

export function subscribeWrites(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Тесты: чистый учёт между тестами (запрос, оставшийся висеть, не держит слой следующему). */
export function resetWritesInFlight(): void {
  if (inFlight.length === 0) return;
  inFlight = [];
  emit();
}

/** Записи в полёте (старые первыми); пустой список — слоя нет. */
export function useWritesInFlight(): readonly WriteInFlight[] {
  return useSyncExternalStore(subscribeWrites, getWritesInFlight, getWritesInFlight);
}

/** Идёт ли хоть одна запись. */
export function useWriteLocked(): boolean {
  return useWritesInFlight().length > 0;
}
