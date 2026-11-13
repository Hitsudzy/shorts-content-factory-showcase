// Задания тренировки (CC-0073): что попробовать на демо-данных и как центр понимает, что задание
// сделано, — по ответу демо-сервера на запись (метод, путь, статус, код отказа). Отметки — в
// localStorage этого браузера; хранилища может не быть — тогда отметки живут до перезагрузки.
import { PAST } from '../mocks/batches';
import { READY, REEL } from '../mocks/publish';

export type TaskId =
  | 'accept'
  | 'pause'
  | 'card'
  | 'answer'
  | 'ask'
  | 'confirm'
  | 'expired'
  | 'refused'
  | 'upload'
  | 'hold'
  | 'meme'
  | 'studio';

export type TrainingTask = {
  id: TaskId;
  title: string;
  /** Где и что нажать — одной строкой. */
  hint: string;
  /** Куда отвести по «Открыть»; нет — задание делается с любого экрана. */
  to?: string;
  /** Только в тренировке: на живой фабрике центр этого за вас не делает без подписи и аудита. */
  demoOnly?: boolean;
};

export const TASKS: readonly TrainingTask[] = [
  {
    id: 'accept',
    title: 'Принять ролик',
    hint: '«Ролики» → ролик → «Да», допишите слова и подтвердите.',
    to: `/videos?batch=${encodeURIComponent(PAST)}&v=delver`,
  },
  {
    id: 'pause',
    title: 'Поставить паузу выкладки',
    hint: '«Публикация» → «Пауза»: причина и срок → план → «да».',
    to: `/publishing?channel=${REEL}`,
  },
  {
    id: 'card',
    title: 'Разместить карточку в слот',
    hint: '«Публикация» → «Карточка»: ролик из очереди, батч → в слот → «да».',
    to: `/publishing?channel=${REEL}`,
  },
  {
    id: 'answer',
    title: 'Ответить на вопрос',
    hint: '«Вопросы» → напишите ответ под вопросом → «Отправить».',
    to: '/questions',
  },
  {
    id: 'ask',
    title: 'Попросить оператора',
    hint: '«Попросить оператора» в шапке → текст просьбы → «Отправить».',
  },
  {
    id: 'confirm',
    title: 'Пройти план и подтвердить',
    hint: 'Любая запись: сначала план фабрики — что изменится, потом ваше «да» с отсчётом.',
  },
  {
    id: 'expired',
    title: 'Увидеть «план устарел»',
    hint: '«Промотать время» ниже, потом «да» в любом плане — фабрика скажет, что он устарел.',
  },
  {
    id: 'refused',
    title: 'Увидеть отказ фабрики',
    hint: '«Следующее «да» — отказ» ниже, потом «да» в записи на «Публикации».',
    to: `/publishing?channel=${REEL}`,
  },
  {
    id: 'upload',
    title: 'Загрузить ролик на YouTube',
    hint: '«Публикация» → готовый ролик → «Загрузить на YouTube» → ответ «да».',
    to: `/publishing?channel=${REEL}&slot=2026-10-13/${READY}`,
    demoOnly: true,
  },
  {
    id: 'hold',
    title: 'Подписать холд',
    hint: '«Публикация» → «Холды»: посмотрите ролик → заметка → план → «да».',
    to: `/publishing?channel=${REEL}`,
    demoOnly: true,
  },
  {
    id: 'meme',
    title: 'Разобрать мемы',
    hint: '«Мемы» → мем → «Оставить» или «Убрать» (клавиши K и D) → «Сохранить отметки».',
    to: '/memes?channel=example-tech',
  },
  {
    id: 'studio',
    title: 'Внести цифры Studio',
    hint: '«Статистика» → «Внести прочитанное в Studio»: строки по ролику → план → «да».',
    to: `/stats?channel=${REEL}`,
  },
];

/** Ответ демо-сервера на запись (не GET): этого хватает, чтобы узнать сделанное. */
export type WriteEvent = {
  method: string;
  path: string;
  status: number;
  /** `code` из тела отказа, если он есть. */
  code: string | null;
};

/** Отказы, которые сами по себе — отдельное задание, а не «отказ фабрики». */
const NOT_A_REFUSAL = new Set(['confirm_expired']);

const ok = (s: number) => s >= 200 && s < 300;

/** Запись, у которой был план: «да» в публикации, действиях с батчами, пересборке. */
function isConfirm(path: string): boolean {
  if (path.endsWith('/plan')) return false;
  return (
    /\/api\/publish\/[^/]+\/./.test(path) ||
    /\/api\/batches\/launch$/.test(path) ||
    /\/api\/batches\/[^/]+\/[^/]+\/(stop|resume|rebuild)$/.test(path) ||
    /\/api\/memes\/[^/]+\/(apply|cutout|trim|add-image|add-gif|sheet|embed)$/.test(path) ||
    /\/api\/analytics\/[^/]+\/studio\/record$/.test(path)
  );
}

/** Какие задания закрывает этот ответ демо-сервера. */
export function detect(ev: WriteEvent): TaskId[] {
  if (ev.method === 'GET' || ev.method === 'HEAD') return [];
  const p = ev.path.replace(/\/+$/, '');
  const out: TaskId[] = [];
  if (!ok(ev.status)) {
    if (ev.code === 'confirm_expired') out.push('expired');
    else if (ev.status >= 400 && !NOT_A_REFUSAL.has(ev.code ?? '')) out.push('refused');
    return out;
  }
  if (/\/api\/batches\/[^/]+\/[^/]+\/videos\/[^/]+\/acceptance$/.test(p)) out.push('accept');
  if (/\/api\/publish\/[^/]+\/pause\/set$/.test(p)) out.push('pause');
  if (/\/api\/publish\/[^/]+\/card\/place$/.test(p)) out.push('card');
  if (/\/api\/questions\/[^/]+\/answer$/.test(p)) out.push('answer');
  if (/\/api\/requests$/.test(p)) out.push('ask');
  if (/\/api\/publish\/[^/]+\/upload$/.test(p)) out.push('upload');
  if (/\/api\/publish\/[^/]+\/holds\/[^/]+\/[^/]+\/sign$/.test(p)) out.push('hold');
  if (/\/api\/memes\/[^/]+\/marks$/.test(p)) out.push('meme');
  if (/\/api\/analytics\/[^/]+\/studio\/record$/.test(p)) out.push('studio');
  if (isConfirm(p)) out.push('confirm');
  return out;
}

export const TASKS_STORAGE_KEY = 'cc-training-tasks';

const KNOWN = new Set<string>(TASKS.map((t) => t.id));

/** Разбор сохранённого: чужое и испорченное отбрасывается. Порядок — как в `TASKS`. */
export function parseDone(raw: string | null): TaskId[] {
  if (!raw) return [];
  try {
    const v: unknown = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    const got = new Set(v.filter((x): x is TaskId => typeof x === 'string' && KNOWN.has(x)));
    return TASKS.map((t) => t.id).filter((id) => got.has(id));
  } catch {
    return [];
  }
}

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function localStore(): Store | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function loadDone(store: Store | null): TaskId[] {
  try {
    return parseDone(store?.getItem(TASKS_STORAGE_KEY) ?? null);
  } catch {
    return [];
  }
}

export function saveDone(store: Store | null, done: readonly TaskId[]): void {
  try {
    store?.setItem(TASKS_STORAGE_KEY, JSON.stringify(done));
  } catch {
    // Не запомнили — отметки живут до перезагрузки.
  }
}

/** Отметить сделанное; тот же массив, если нового нет. Порядок — как в `TASKS`. */
export function markDone(done: readonly TaskId[], ids: readonly TaskId[]): readonly TaskId[] {
  if (ids.every((id) => done.includes(id))) return done;
  const all = new Set([...done, ...ids]);
  return TASKS.map((t) => t.id).filter((id) => all.has(id));
}

/** Отметки заданий с подпиской — для панели (useSyncExternalStore). */
export function createChecklist(store: Store | null = localStore()) {
  let done: readonly TaskId[] = loadDone(store);
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((l) => l());
  return {
    get: () => done,
    subscribe(l: () => void) {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
    /** Учесть ответ демо-сервера; вернуть только что закрытые задания. */
    record(ev: WriteEvent): TaskId[] {
      const fresh = detect(ev).filter((id) => !done.includes(id));
      if (!fresh.length) return [];
      done = markDone(done, fresh);
      saveDone(store, done);
      emit();
      return fresh;
    },
    reset() {
      done = [];
      saveDone(store, done);
      emit();
    },
  };
}

export type Checklist = ReturnType<typeof createChecklist>;
