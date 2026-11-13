// Тренировка на демо-данных (CC-0073): режим этой вкладки. Здесь — только переключатель: он
// лежит в основном куске и не тянет ни MSW, ни моки. Демо-сервер (`./demo`) грузится лениво —
// только когда вкладка в тренировке.
//
// Как устроено, чтобы живые и демо-данные никогда не смешались:
// - флаг тренировки — в sessionStorage этой вкладки (а если хранилища нет — в адресе
//   `?training=1`); читается в try/catch;
// - вход и выход — через перезагрузку страницы: кэш TanStack Query, токен сессии и всё, что
//   держит память, начинаются с чистого листа;
// - при загрузке в тренировке демо-сервер (service worker MSW) поднимается ДО первого рендера,
//   то есть до первого запроса; не поднялся — флаг снимается и центр открывается живым;
// - пока тренировка идёт, клиент API не отправит запрос, если страницу не держит service worker
//   (`guardedFetch`): лучше отказ, чем запрос в настоящую фабрику.

export const TRAINING_KEY = 'cc-training';
/** Флаг в адресе — когда sessionStorage недоступен. */
export const TRAINING_PARAM = 'training';

type FlagStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function sessionStore(): FlagStore | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Вкладка в тренировке: флаг в хранилище или в адресе. Ошибки хранилища — «нет флага». */
export function readTrainingFlag(store: FlagStore | null, search: string): boolean {
  try {
    if (store?.getItem(TRAINING_KEY) === '1') return true;
  } catch {
    // Хранилище есть, но не читается — смотрим адрес.
  }
  try {
    return new URLSearchParams(search).get(TRAINING_PARAM) === '1';
  } catch {
    return false;
  }
}

/** Эта вкладка грузится в тренировку (флаг этой вкладки): о входе живой API не спрашиваем. */
export function trainingRequested(): boolean {
  return readTrainingFlag(
    sessionStore(),
    typeof window === 'undefined' ? '' : window.location.search,
  );
}

/** Записать флаг; false — хранилища нет, флаг поедет в адресе. */
export function writeTrainingFlag(store: FlagStore | null): boolean {
  try {
    if (!store) return false;
    store.setItem(TRAINING_KEY, '1');
    return store.getItem(TRAINING_KEY) === '1';
  } catch {
    return false;
  }
}

export function clearTrainingFlag(store: FlagStore | null): void {
  try {
    store?.removeItem(TRAINING_KEY);
  } catch {
    // Не удалось — на выходе флаг всё равно снимается из адреса, а демо-сервер остановлен.
  }
}

/** Адрес без флага тренировки (остальной запрос — как был). */
export function withoutParam(href: string): string {
  const u = new URL(href);
  u.searchParams.delete(TRAINING_PARAM);
  return u.toString();
}

/** Состояние режима: до загрузки — `live`; `training` — демо-сервер поднят и держит страницу. */
export type TrainingState =
  { mode: 'live'; failed: string | null } | { mode: 'training'; demo: DemoHandle };

/** То, что основной кусок знает о демо-сервере (сам он — в ленивом `./demo`). */
export type DemoHandle = {
  /** Остановить демо-сервер и снять его service worker. */
  stop: () => Promise<void>;
};

export type DemoModule = {
  startDemo: () => Promise<DemoHandle>;
};

let state: TrainingState = { mode: 'live', failed: null };

export const trainingState = (): TrainingState => state;
export const isTraining = (): boolean => state.mode === 'training';

/** Для тестов: вернуть режим к началу. */
export function resetTrainingState(next: TrainingState = { mode: 'live', failed: null }): void {
  state = next;
}

const loadDemo = (): Promise<DemoModule> => import('./demo');

export type BootDeps = {
  store: FlagStore | null;
  location: Pick<Location, 'href' | 'search'>;
  replaceUrl: (href: string) => void;
  load: () => Promise<DemoModule>;
  /** Снять service worker MSW, оставшийся от прошлой тренировки (живая загрузка). */
  cleanup: () => Promise<void>;
};

/** Снять зарегистрированный service worker демо-сервера: живому центру он не нужен. */
export async function unregisterDemoWorker(): Promise<void> {
  try {
    const sw = typeof navigator === 'undefined' ? undefined : navigator.serviceWorker;
    if (!sw?.getRegistrations) return;
    const regs = await sw.getRegistrations();
    await Promise.all(
      regs
        .filter((r) =>
          [r.active, r.waiting, r.installing].some((w) =>
            w?.scriptURL.endsWith('/mockServiceWorker.js'),
          ),
        )
        .map((r) => r.unregister()),
    );
  } catch {
    // Не снялся — без активации из вкладки он только пропускает запросы как есть.
  }
}

const defaultDeps = (): BootDeps => ({
  store: sessionStore(),
  location: window.location,
  replaceUrl: (href) => window.history.replaceState(window.history.state, '', href),
  load: loadDemo,
  cleanup: unregisterDemoWorker,
});

/**
 * Загрузка центра: в тренировке — поднять демо-сервер до первого запроса. Не вышло — снять флаг
 * и открыться живым (с причиной в `failed`), никогда не наполовину.
 */
export async function bootTraining(deps: BootDeps = defaultDeps()): Promise<TrainingState> {
  if (!readTrainingFlag(deps.store, deps.location.search)) {
    void deps.cleanup();
    state = { mode: 'live', failed: null };
    return state;
  }
  // Флаг из адреса — переложить в хранилище (если есть) и убрать из адреса.
  if (new URLSearchParams(deps.location.search).get(TRAINING_PARAM) === '1') {
    if (writeTrainingFlag(deps.store)) deps.replaceUrl(withoutParam(deps.location.href));
  }
  try {
    const demo = await (await deps.load()).startDemo();
    state = { mode: 'training', demo };
  } catch (e) {
    clearTrainingFlag(deps.store);
    deps.replaceUrl(withoutParam(deps.location.href));
    await deps.cleanup();
    state = {
      mode: 'live',
      failed: e instanceof Error && e.message ? e.message : 'демо-сервер не запустился',
    };
  }
  return state;
}

/** «Начать тренировку»: флаг — и перезагрузка на главную, демо-сервер поднимется до запросов. */
export function enterTraining(
  store: FlagStore | null = sessionStore(),
  go: (href: string) => void = (href) => window.location.assign(href),
): void {
  const home = new URL(import.meta.env.BASE_URL, window.location.origin);
  if (!writeTrainingFlag(store)) home.searchParams.set(TRAINING_PARAM, '1');
  go(home.toString());
}

/** «Выйти из тренировки»: остановить демо-сервер, снять флаг, перезагрузиться живым. */
export async function exitTraining(
  store: FlagStore | null = sessionStore(),
  go: (href: string) => void = (href) => window.location.replace(href),
): Promise<void> {
  const current = state;
  clearTrainingFlag(store);
  state = { mode: 'live', failed: null };
  if (current.mode === 'training') {
    try {
      await current.demo.stop();
    } catch {
      // Остановить не вышло — перезагрузка без флага всё равно не поднимет демо-сервер.
    }
  }
  go(withoutParam(window.location.href));
}

/** Отказ запроса в тренировке, когда страницу не держит демо-сервер. */
export class TrainingGuardError extends Error {
  constructor() {
    super('Тренировка: демо-сервер не отвечает, запрос не отправлен в фабрику');
    this.name = 'TrainingGuardError';
  }
}

/**
 * fetch клиента API. В тренировке запрос уходит только через service worker демо-сервера: если
 * страницу он не держит (жёсткая перезагрузка, сбой), запрос не отправляется вовсе.
 */
export function guardedFetch(request: Request): Promise<Response> {
  if (state.mode === 'training') {
    const sw = typeof navigator === 'undefined' ? undefined : navigator.serviceWorker;
    if (!sw?.controller?.scriptURL.endsWith('/mockServiceWorker.js'))
      return Promise.reject(new TrainingGuardError());
  }
  return globalThis.fetch(request);
}
