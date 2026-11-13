import {
  bootTraining,
  enterTraining,
  exitTraining,
  guardedFetch,
  isTraining,
  readTrainingFlag,
  resetTrainingState,
  TRAINING_KEY,
  TrainingGuardError,
  trainingState,
  withoutParam,
  writeTrainingFlag,
  type BootDeps,
  type DemoModule,
} from './mode';

/** Хранилище в памяти; `broken` — каждый вызов бросает (приватное окно, запрет сайта). */
function memory(broken = false) {
  const m = new Map<string, string>();
  const guard = () => {
    if (broken) throw new DOMException('denied', 'SecurityError');
  };
  return {
    m,
    getItem: (k: string) => {
      guard();
      return m.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      guard();
      m.set(k, v);
    },
    removeItem: (k: string) => {
      guard();
      m.delete(k);
    },
  };
}

type TestDeps = BootDeps & {
  store: ReturnType<typeof memory>;
  urls: string[];
  cleaned: number;
  loads: number;
};

function deps(over: Partial<BootDeps> = {}, href = 'http://127.0.0.1/'): TestDeps {
  const u = new URL(href);
  const d: TestDeps = {
    urls: [],
    cleaned: 0,
    loads: 0,
    store: memory(),
    location: { href: u.toString(), search: u.search },
    replaceUrl: (h: string) => {
      d.urls.push(h);
    },
    load: async (): Promise<DemoModule> => {
      d.loads += 1;
      return { startDemo: async () => ({ stop: async () => {} }) };
    },
    cleanup: async () => {
      d.cleaned += 1;
    },
  };
  return Object.assign(d, over);
}

afterEach(() => resetTrainingState());

describe('флаг тренировки', () => {
  it('в хранилище, в адресе; сломанное хранилище — смотрим адрес, не падаем', () => {
    const s = memory();
    expect(readTrainingFlag(s, '')).toBe(false);
    s.setItem(TRAINING_KEY, '1');
    expect(readTrainingFlag(s, '')).toBe(true);
    expect(readTrainingFlag(memory(true), '')).toBe(false);
    expect(readTrainingFlag(memory(true), '?training=1')).toBe(true);
    expect(readTrainingFlag(null, '?a=1&training=1')).toBe(true);
    expect(readTrainingFlag(null, '?training=0')).toBe(false);
  });

  it('запись: нет хранилища или бросает — false (флаг поедет в адресе)', () => {
    expect(writeTrainingFlag(null)).toBe(false);
    expect(writeTrainingFlag(memory(true))).toBe(false);
    const s = memory();
    expect(writeTrainingFlag(s)).toBe(true);
    expect(s.m.get(TRAINING_KEY)).toBe('1');
  });

  it('адрес без флага: остальной запрос на месте', () => {
    expect(withoutParam('http://x/videos?training=1&v=a')).toBe('http://x/videos?v=a');
  });
});

describe('загрузка центра', () => {
  it('без флага — живой центр: демо-кусок не грузится, старый service worker снимается', async () => {
    const d = deps();
    expect(await bootTraining(d)).toEqual({ mode: 'live', failed: null });
    expect(d.loads).toBe(0);
    expect(d.cleaned).toBe(1);
    expect(isTraining()).toBe(false);
  });

  it('с флагом — демо-сервер поднимается до рендера; режим «тренировка»', async () => {
    const d = deps();
    d.store.setItem(TRAINING_KEY, '1');
    const s = await bootTraining(d);
    expect(s.mode).toBe('training');
    expect(d.loads).toBe(1);
    expect(d.cleaned).toBe(0);
    expect(isTraining()).toBe(true);
  });

  it('флаг из адреса перекладывается в хранилище и убирается из адреса', async () => {
    const d = deps({}, 'http://127.0.0.1/?training=1&x=2');
    await bootTraining(d);
    expect(d.store.m.get(TRAINING_KEY)).toBe('1');
    expect(d.urls).toEqual(['http://127.0.0.1/?x=2']);
    expect(isTraining()).toBe(true);
  });

  it('демо-сервер не поднялся — флаг снят, центр живой с причиной, без смеси', async () => {
    const d = deps({
      load: async () => ({
        startDemo: async () => {
          throw new Error('демо-сервер не взял страницу под себя');
        },
      }),
    });
    d.store.setItem(TRAINING_KEY, '1');
    expect(await bootTraining(d)).toEqual({
      mode: 'live',
      failed: 'демо-сервер не взял страницу под себя',
    });
    expect(d.store.m.has(TRAINING_KEY)).toBe(false);
    expect(d.cleaned).toBe(1);
    expect(isTraining()).toBe(false);
  });

  it('кусок не загрузился — тоже живой центр', async () => {
    const d = deps({ load: () => Promise.reject(new Error('')) });
    d.store.setItem(TRAINING_KEY, '1');
    expect(await bootTraining(d)).toEqual({ mode: 'live', failed: 'демо-сервер не запустился' });
  });
});

describe('вход и выход', () => {
  it('вход: флаг и на главную; без хранилища — флаг в адресе', () => {
    const gone: string[] = [];
    const s = memory();
    enterTraining(s, (h) => gone.push(h));
    expect(s.m.get(TRAINING_KEY)).toBe('1');
    enterTraining(memory(true), (h) => gone.push(h));
    expect(gone.map((h) => new URL(h).pathname + new URL(h).search)).toEqual(['/', '/?training=1']);
  });

  it('выход: демо-сервер остановлен, флаг снят, перезагрузка живым', async () => {
    const stop = vi.fn(async () => {});
    resetTrainingState({ mode: 'training', demo: { stop } });
    const s = memory();
    s.setItem(TRAINING_KEY, '1');
    const gone: string[] = [];
    await exitTraining(s, (h) => gone.push(h));
    expect(stop).toHaveBeenCalledTimes(1);
    expect(s.m.has(TRAINING_KEY)).toBe(false);
    expect(trainingState()).toEqual({ mode: 'live', failed: null });
    expect(gone).toHaveLength(1);
  });

  it('выход, даже если остановка бросила, — всё равно перезагрузка без флага', async () => {
    resetTrainingState({
      mode: 'training',
      demo: { stop: () => Promise.reject(new Error('x')) },
    });
    const gone: string[] = [];
    await exitTraining(memory(true), (h) => gone.push(h));
    expect(gone).toHaveLength(1);
    expect(isTraining()).toBe(false);
  });
});

describe('сторож клиента API', () => {
  it('в тренировке без service worker демо-сервера запрос не уходит вовсе', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    resetTrainingState({ mode: 'training', demo: { stop: async () => {} } });
    await expect(guardedFetch(new Request('http://127.0.0.1/api/health'))).rejects.toBeInstanceOf(
      TrainingGuardError,
    );
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it('в тренировке под чужим service worker — тоже не уходит', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { controller: { scriptURL: 'http://127.0.0.1/other-sw.js' } },
    });
    try {
      resetTrainingState({ mode: 'training', demo: { stop: async () => {} } });
      await expect(guardedFetch(new Request('http://127.0.0.1/api/health'))).rejects.toThrow(
        'демо-сервер не отвечает',
      );
      expect(spy).not.toHaveBeenCalled();
    } finally {
      Reflect.deleteProperty(navigator, 'serviceWorker');
      spy.mockRestore();
    }
  });

  it('в тренировке под service worker демо-сервера — уходит (его ловит демо-сервер)', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { controller: { scriptURL: 'http://127.0.0.1/mockServiceWorker.js' } },
    });
    try {
      resetTrainingState({ mode: 'training', demo: { stop: async () => {} } });
      await guardedFetch(new Request('http://127.0.0.1/api/health'));
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      Reflect.deleteProperty(navigator, 'serviceWorker');
      spy.mockRestore();
    }
  });

  it('живой центр — запрос как обычно', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    await guardedFetch(new Request('http://127.0.0.1/api/health'));
    expect(spy).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
