// Подставные фоновые задачи банка мемов (CC-0075 API, договор 0.62.0): вырезка фона и обрезка
// пустых полей — план (ничего не пишет), «да» запускает задачу, задача идёт по опросам: каждый
// `GET …/jobs/{id}` — шаг вперёд («i из N»), за последним — итог (`done`, `failed` или
// `interrupted`, как взведено). Одна задача на банк: пока идёт, планы отвечают `ok:false` +
// `job`, отметки и «применить» — `job_active`; задача на другом банке машины — `machine_job` и
// `job_running`. Vision можно «выключить» (`cutout_available()`). Общий для Vitest, Playwright и
// тренировки (через ./memes.ts).
import type { components } from '../api/schema.gen';
import type { BankSeed, IndexEntry } from './memesData';

type S = components['schemas'];
type Code = S['MemesProblem']['code'];

export type JobReply =
  { status: 200; body: unknown } | { status: 404 | 409 | 422 | 500; body: S['MemesProblem'] };

export type JobOutcome = 'done' | 'failed' | 'interrupted';
type Kind = 'cutout' | 'trim_blank' | AddKind;
/** CC-0133: задачи по шагам (`i из N` — шаги, а не мемы). */
type AddKind = 'add_image' | 'add_gif' | 'sheet' | 'embed';
const ADD_KINDS: readonly string[] = ['add_image', 'add_gif', 'sheet', 'embed'];

type Ctx = {
  banks: Record<string, BankSeed>;
  bankOf: (channel: string) => { bank: string } | null;
  hash: (text: string) => string;
};

const KIND_WORD: Record<Kind, string> = {
  cutout: 'вырезка фона',
  trim_blank: 'обрезка пустых полей',
  add_image: 'добавление картинки',
  add_gif: 'нарезка GIF',
  sheet: 'контактный лист',
  embed: 'пересчёт признаков для поиска похожих мемов',
};
const STATE_WORD: Record<S['MemeJob']['state'], string> = {
  running: 'идёт',
  done: 'готово',
  failed: 'не удалась',
  interrupted: 'оборвалась',
};
const ACTION: Record<Kind, S['MemeJobStarted']['action']> = {
  cutout: 'meme_cutout',
  trim_blank: 'meme_trim',
  add_image: 'meme_add_image',
  add_gif: 'meme_add_gif',
  sheet: 'meme_sheet',
  embed: 'meme_embed',
};
/** Потолок растяжения после обрезки (фабрика: `ceiling`). */
const CEILING = 1.25;
const TTL_S = 120;

const isGif = (e: IndexEntry) => e.file.toLowerCase().endsWith('.gif');
const hasCut = (e: IndexEntry) => typeof e.cutout_asset?.file === 'string';
const now = () => new Date().toISOString().replace(/\.\d+Z$/, '+00:00');

const problem = (
  status: 404 | 409 | 422 | 500,
  code: Code,
  message: string,
  details: string[] = [],
): JobReply => ({ status, body: { code, message, details } });

type Rec = {
  job: S['MemeJob'];
  channel: string;
  items: string[];
  /** Сколько раз задачу уже спросили. */
  tick: number;
  outcome: JobOutcome;
  /** Сделать и вернуть `result` (банк меняется только здесь). */
  finish: () => Record<string, unknown>;
  /** Задача по шагам (добавления, лист, признаки): шаг и его строка на каждый опрос. */
  steps?: { step: string; text: string }[];
};

export function createMemeJobs(ctx: Ctx) {
  /** Переключатели тестов и тренировки. */
  const state = {
    vision: { available: true, reason: 'распознавание Vision (macOS 15.1), среда видеомонтажа' },
    /** `poll_s` задач: у фабрики 3 с, тестам — короче. */
    pollS: 1,
    /** Чем кончится следующая задача. */
    outcome: 'done' as JobOutcome,
    /** Vision откажет этим мемам (id → причина словами фабрики). */
    refuse: {} as Record<string, string>,
    /** Мемы, у которых нет файла картинки (`missing`). */
    missing: [] as string[],
    /** Эмбеддинги после обрезки не пересчитаются. */
    embedFail: false,
    /** Задача стоит на этом шаге («i из N»), пока тест её не отпустит (`null`). */
    holdAt: null as number | null,
    /** Живая задача на другом банке машины (`machine_job`). */
    elsewhere: null as S['MemeJobRef'] | null,
    /** Следующий запуск получит отказ. */
    failStart: null as { status: 409 | 500; code: Code; message: string } | null,
    plans: [] as { kind: Kind; body: unknown }[],
    life: TTL_S,
    /** CC-0133: видео уже в кэше банка (`cached`, не скачивается). */
    cached: [] as string[],
    /** Листы кадров, что уже лежат в банке (`overwrites`; их отдаёт `…/sheets/{name}`). */
    sheets: [] as string[],
    /** Смены сцен видео, секунды (итог листа и `cuts_inside` гифки). */
    sceneCuts: [12.4, 27] as number[],
    /** Пометка фабрики о срезе пустой полосы у новой картинки: `en` — `trim_note`, `ru` — `trim_note_ru`. */
    trimNote: null as { en: string; ru: string | null } | null,
    /** Провал следующей задачи по шагам (с `outcome: 'failed'`); без него — по виду задачи. */
    jobError: null as S['MemeJobError'] | null,
    /**
     * CC-0161 (CF-0847): чем кончится коммит итога законченной задачи — `committed` (sha и пути),
     * `refused` (git отказал: итог в дереве, ничего не застейджено), `nothing`; null — как старый
     * стол, без коммита (по умолчанию).
     */
    commit: null as S['MemeJobCommit']['status'] | null,
  };
  const jobs: Rec[] = [];
  const tokens = new Map<
    string,
    { channel: string; kind: Kind; fp: string; params: Record<string, unknown>; expires: number }
  >();
  let seq = 0;

  const bankName = (channel: string) => ctx.bankOf(channel)!.bank;
  const bank = (channel: string) => ctx.banks[bankName(channel)]!;
  const running = (bankId: string) =>
    jobs.find((r) => r.job.bank === bankId && r.job.state === 'running') ?? null;

  function ref(r: Rec): S['MemeJobRef'] {
    return {
      job_id: r.job.job_id,
      kind: r.job.kind,
      kind_word: r.job.kind_word,
      bank: r.job.bank,
      channel: r.channel,
      started_at: r.job.started_at,
      progress: r.job.progress,
    };
  }

  const urls = (channel: string, e: IndexEntry | undefined, id: string): S['MemeUrls'] => {
    const base = `/api/memes/${channel}/${id}`;
    return {
      file: `${base}/media?kind=file`,
      cut: e && hasCut(e) ? `${base}/media?kind=cut` : null,
      thumb: `${base}/thumb`,
    };
  };

  /** Почему план сейчас нельзя из-за задач: та же банка или другой банк машины. */
  function guard(channel: string): {
    why: string;
    job?: S['MemeJobRef'];
    machine_job?: S['MemeJobRef'];
  } | null {
    const r = running(bankName(channel));
    if (r)
      return {
        why: `На банке ${r.job.bank} идёт задача «${r.job.kind_word}» (${r.job.job_id}) — дождитесь её конца (отмены нет).`,
        job: ref(r),
      };
    const other = state.elsewhere;
    if (other)
      return {
        why: `На машине идёт задача «${other.kind_word}» банка ${other.bank} — одна задача на машину, дождитесь её конца.`,
        machine_job: other,
      };
    return null;
  }

  // ---- вырезка фона
  function cutoutCompute(channel: string, raw: unknown) {
    const b = bank(channel);
    const body = (raw ?? {}) as { ids?: string[] | null; force?: boolean };
    const ids = body.ids ?? null;
    const force = !!body.force;
    if (Array.isArray(ids) && !ids.length)
      return {
        refusal: problem(422, 'bad_ids', 'Выберите хотя бы один мем (или не указывайте ids).'),
      };
    for (const id of ids ?? []) {
      const e = b.entries.find((x) => x.id === id);
      if (!e) return { refusal: problem(422, 'unknown_id', `мема '${id}' нет в банке`) };
      if (!e.cutout)
        return {
          refusal: problem(
            422,
            'not_cutout',
            `У мема '${id}' нет отметки «можно вырезать» — сначала отметьте и примените разбор.`,
          ),
        };
    }
    const pool = b.entries.filter((e) => e.cutout && !isGif(e) && (!ids || ids.includes(e.id)));
    const missing = pool.filter((e) => state.missing.includes(e.id)).map((e) => e.id);
    const live = pool.filter((e) => !missing.includes(e.id));
    const made = live
      .filter((e) => force || !hasCut(e))
      .map((e) => ({ id: e.id, file: `${e.id}.cutout.png`, bbox_px: null, coverage: null }));
    const unchanged = live.filter((e) => !force && hasCut(e)).map((e) => e.id);
    const params = { ids, force };
    const fp = ctx.hash(JSON.stringify({ i: b.entries, made, params }));
    return { pool, made, unchanged, missing, params, fp };
  }

  function cutoutPlan(channel: string, raw: unknown): JobReply {
    state.plans.push({ kind: 'cutout', body: raw });
    const c = cutoutCompute(channel, raw);
    if ('refusal' in c) return c.refusal!;
    const g = guard(channel);
    const v = state.vision;
    const why = g
      ? g.why
      : !v.available
        ? `Вырезка на этой машине недоступна: ${v.reason}`
        : !c.pool.length
          ? 'Вырезать нечего: в банке нет мемов с отметкой «можно вырезать».'
          : !c.made.length
            ? 'Вырезать нечего: у всех мемов «можно вырезать» вырезка свежая — заново только с «вырезать заново».'
            : null;
    const ok = !why;
    let confirm: string | null = null;
    if (ok) {
      confirm = `meme-cutout-${++seq}`;
      tokens.set(confirm, {
        channel,
        kind: 'cutout',
        fp: c.fp,
        params: c.params,
        expires: Date.now() + state.life * 1000,
      });
    }
    const body: S['MemeCutoutPlan'] = {
      action: 'meme_cutout',
      channel,
      bank: bankName(channel),
      kind: 'cutout',
      dry_run: true,
      params: c.params,
      available: v.available,
      available_reason: v.reason,
      made: c.made,
      refused: [],
      unchanged: c.unchanged,
      missing: c.missing,
      outside_bank: [],
      notes: [
        'Откажет ли распознавание (не найдёт главного предмета, передний план слишком крупный) и рамка вырезки станут известны только после прогона.',
        'Свежие вырезки фабрика не трогает — заново их делает только «вырезать заново».',
      ],
      ok,
      why,
      job: g?.job ?? null,
      machine_job: g?.machine_job ?? null,
      index_fingerprint: ctx.hash(JSON.stringify(bank(channel).entries)),
      fingerprint: c.fp,
      confirm,
      expires_in_s: confirm ? state.life : null,
    };
    return { status: 200, body };
  }

  // ---- обрезка пустых полей
  function trimRows(channel: string, raw: unknown) {
    const b = bank(channel);
    const id = ((raw ?? {}) as { id?: string | null }).id ?? null;
    const rows: S['MemeTrimRow'][] = [];
    for (const band of b.bands) {
      if (id && band.id !== id) continue;
      const e = b.entries.find((x) => x.id === band.id);
      const m = /^(top|bottom) (\d+) \w+ rows \((\d+)%\)$/.exec(band.phrase);
      if (!e || !m) continue;
      const n = Number(m[2]);
      const share = Number(m[3]) / 100;
      const h = Math.round(n / share);
      const w = 600;
      rows.push({
        id: e.id,
        file: e.file,
        size: [w, h],
        trimmed_size: [w, h - n],
        crop: m[1] === 'top' ? [n, 0] : [0, n],
        phrase: band.phrase,
        phrase_ru: band.phrase_ru ?? null,
        stretch: Math.round((1 / (1 - share)) * 100) / 100,
        ceiling: CEILING,
        recut: !!e.cutout && hasCut(e),
      });
    }
    const left: S['MemeIdReason'][] = b.entries
      .filter((e) => isGif(e) && (!id || e.id === id))
      .map((e) => ({ id: e.id, reason: 'GIF — поля у гифок фабрика не режет', en: 'a GIF' }));
    const trim = rows.filter((r) => r.stretch <= r.ceiling);
    const under = rows.filter((r) => r.stretch > r.ceiling);
    const params = { id };
    const fp = ctx.hash(JSON.stringify({ i: b.entries, trim, params }));
    return { trim, under, left, params, fp };
  }

  function trimPlan(channel: string, raw: unknown): JobReply {
    state.plans.push({ kind: 'trim_blank', body: raw });
    const t = trimRows(channel, raw);
    const g = guard(channel);
    const why = g
      ? g.why
      : !t.trim.length
        ? 'Резать нечего: пустых полос подписи нет, а где есть — обрезка растянула бы мем сильнее допустимого.'
        : null;
    const ok = !why;
    let confirm: string | null = null;
    if (ok) {
      confirm = `meme-trim-${++seq}`;
      tokens.set(confirm, {
        channel,
        kind: 'trim_blank',
        fp: t.fp,
        params: t.params,
        expires: Date.now() + state.life * 1000,
      });
    }
    const recut = t.trim.filter((r) => r.recut).map((r) => r.id);
    const body: S['MemeTrimPlan'] = {
      action: 'meme_trim',
      channel,
      bank: bankName(channel),
      kind: 'trim_blank',
      dry_run: true,
      params: t.params,
      embed: true,
      trim: t.trim,
      left: t.left,
      under: t.under,
      changed: [],
      originals: null,
      embedding: null,
      notes: [
        'После обрезки фабрика сбросит признаки обрезанных мемов для поиска похожих и посчитает их заново.',
        'Оригиналы картинок останутся в _desk/originals/ банка.',
        ...(recut.length ? [`Вырезку придётся сделать заново: ${recut.join(', ')}.`] : []),
        ...(t.under.length
          ? [
              'Мемы, которые растянулись бы сильнее допустимого, фабрика оставит целыми — решать вам.',
            ]
          : []),
      ],
      ok,
      why,
      job: g?.job ?? null,
      machine_job: g?.machine_job ?? null,
      index_fingerprint: ctx.hash(JSON.stringify(bank(channel).entries)),
      fingerprint: t.fp,
      confirm,
      expires_in_s: confirm ? state.life : null,
    };
    return { status: 200, body };
  }

  // ---- CC-0133: добавить картинку и GIF, лист кадров, признаки для поиска похожих
  const ID_RE = /^[a-z0-9][a-z0-9_-]*$/;
  const STILL = ['.png', '.jpg', '.jpeg', '.webp'];
  const MAX_FRAMES = 300;
  const PENDING = 'Мем войдёт в банк непроверенным\u00a0— его надо будет отметить на столе.';
  /** Имя канала, как его видит человек (CC-0136: в заметках — не id). */
  const CHANNEL_NAME: Record<string, string> = {
    'example-film': 'ExampleFilm',
    'example-science': 'ExampleScience',
    'example-tech': 'ExampleTech',
  };
  const named = (channel: string) => CHANNEL_NAME[channel] ?? channel;
  const REINDEX = 'После добавления банк пересчитает признаки для поиска похожих мемов.';
  const EMBED_RU = 'признаки для поиска похожих мемов';
  const human = (s: number) => {
    if (s < 60) return `до ${s} с`;
    const m = Math.ceil(s / 60);
    return m < 60 ? `до ${m} мин` : `до ${Math.floor(m / 60)} ч${m % 60 ? ` ${m % 60} мин` : ''}`;
  };
  const MAX_S: Record<AddKind, number> = { add_image: 186, add_gif: 1980, sheet: 1560, embed: 630 };
  const g = (n: number) => String(Math.round(n * 100) / 100).replace('.', ',');

  function http(value: unknown, what: string, word: string): JobReply | null {
    let ok = typeof value === 'string' && !!value && !/\s/.test(value);
    let scheme = 'none';
    if (ok) {
      try {
        const u = new URL(value as string);
        scheme = u.protocol.replace(/:$/, '');
        ok = (scheme === 'http' || scheme === 'https') && !!u.hostname;
      } catch {
        ok = false;
      }
    }
    return ok
      ? null
      : problem(
          422,
          'bad_url',
          `${word}: нужен адрес http(s)://... - локальный путь, file:// и другие схемы центр не принимает.`,
          [`${what} must be an http(s) URL with a host (got scheme '${scheme}')`],
        );
  }

  function checkNew(channel: string, id: unknown, description: unknown): JobReply | null {
    if (typeof id !== 'string' || !ID_RE.test(id))
      return problem(
        422,
        'bad_entry',
        `короткое имя мема «${String(id)}»: только строчные латинские буквы, цифры, дефис и подчёркивание`,
        [`id must match ${ID_RE.source}`],
      );
    if (bank(channel).entries.some((e) => e.id === id))
      return problem(409, 'duplicate_id', `мем «${id}» уже есть в банке`, [
        `${id} is already in the library`,
      ]);
    if (typeof description !== 'string' || !description.trim())
      return problem(422, 'bad_entry', 'нужно описание мема', ['a meme needs a description']);
    return null;
  }

  const tagList = (t: unknown) =>
    (Array.isArray(t) ? t : typeof t === 'string' ? t.split(',') : [])
      .filter((x): x is string => typeof x === 'string')
      .map((x) => x.trim())
      .filter(Boolean);

  type AddCalc = {
    params: Record<string, unknown>;
    fields: Record<string, unknown>;
    steps: { step: string; text: string }[];
    notes: string[];
  };

  function videoSays(video: string) {
    return state.cached.includes(video) ? 'из кэша банка' : video;
  }

  function fetchNote(video: string, what: string) {
    return state.cached.includes(video)
      ? `Видео уже скачано\u00a0— ${what} из него.`
      : `Будет скачано видео ${video} (только картинка, до 720p)\u00a0— один раз для листа и GIF.`;
  }

  function addCompute(
    channel: string,
    kind: AddKind,
    raw: unknown,
  ): { refusal: JobReply } | AddCalc {
    const body = (raw ?? {}) as Record<string, unknown>;
    const b = bank(channel);
    const no = (r: JobReply | null) => (r ? { refusal: r } : null);
    if (kind === 'embed')
      return {
        params: {},
        fields: {},
        steps: [{ step: 'embedding', text: EMBED_RU }],
        notes: [
          `Признаки для поиска похожих мемов будут пересчитаны заново для всего банка мемов канала ${named(channel)}; файлы и отметки мемов не меняются.`,
          'Заранее посчитать нельзя: перед запуском фабрика проверит, что банк свободен.',
        ],
      };
    if (kind === 'add_image') {
      const bad = http(body.url, 'url', 'Адрес картинки');
      if (bad) return { refusal: bad };
      if (http(body.source_url, 'source_url', 'Адрес страницы'))
        return {
          refusal: problem(422, 'no_source_url', 'нужна ссылка на страницу, где файл найден', [
            '--source-url: the page the file was found on (http/https)',
          ]),
        };
      const url = body.url as string;
      const suffix = (/\.[a-z0-9]+$/i.exec(new URL(url).pathname)?.[0] ?? '').toLowerCase();
      if (!STILL.includes(suffix))
        return {
          refusal: problem(
            422,
            'bad_suffix',
            `картинка\u00a0— файл .png, .jpg, .jpeg или .webp, а не ${suffix || 'без расширения'}; GIF добавляется из видео`,
            [`a still is .png/.jpg/.jpeg/.webp, not '${suffix}'; a GIF goes through add-gif`],
          ),
        };
      const n = no(checkNew(channel, body.id, body.description));
      if (n) return n;
      const id = body.id as string;
      const file = `${id}${suffix}`;
      if (b.entries.some((e) => e.file === file))
        return { refusal: problem(409, 'file_exists', `${file} уже лежит в банке`) };
      const tags = tagList(body.tags);
      const params = {
        meme_id: id,
        url,
        source_url: body.source_url,
        description: body.description,
        tags,
        ...(typeof body.notes === 'string' ? { notes: body.notes } : {}),
      };
      return {
        params,
        fields: {
          id,
          file,
          will_fetch: 'url',
          url,
          video: null,
          source_url: body.source_url,
          span: null,
          tags,
        },
        steps: [
          { step: 'download', text: url },
          { step: 'check', text: file },
          { step: 'index', text: id },
          { step: 'embedding', text: EMBED_RU },
        ],
        notes: [
          `Будет скачана картинка ${url} (до 25 МБ) и ляжет в банк мемов канала ${named(channel)}.`,
          PENDING,
          'Пустую полосу под подпись срежут, если она есть; если файл не картинка, залит одним тоном или растянулся бы сильнее допустимого (допустимо до 1,25)\u00a0— отказ после скачивания, банк не меняется.',
          REINDEX,
        ],
      };
    }
    const bad = http(body.video, 'video', 'Адрес видео');
    if (bad) return { refusal: bad };
    const video = body.video as string;
    if (kind === 'add_gif') {
      const start = body.start;
      const end = body.end;
      if (typeof start !== 'number' || typeof end !== 'number')
        return { refusal: problem(422, 'bad_span', 'начало и конец отрезка\u00a0— в секундах') };
      if (start < 0 || end <= start)
        return {
          refusal: problem(
            422,
            'bad_span',
            'конец отрезка должен быть позже начала, а начало\u00a0— не меньше 0',
          ),
        };
      const n = no(checkNew(channel, body.id, body.description));
      if (n) return n;
      const id = body.id as string;
      const file = `${id}.gif`;
      const tags = tagList(body.tags);
      const source =
        typeof body.source_url === 'string' && body.source_url ? body.source_url : video;
      return {
        params: {
          meme_id: id,
          video,
          start,
          end,
          description: body.description,
          tags,
          local: false,
          ...(typeof body.source_url === 'string' ? { source_url: body.source_url } : {}),
        },
        fields: {
          id,
          file,
          will_fetch: 'yt-dlp',
          url: null,
          video,
          source_url: source,
          span: { start_s: start, end_s: end },
          tags,
          cached: state.cached.includes(video),
        },
        steps: [
          { step: 'download', text: videoSays(video) },
          { step: 'scenes', text: 'смены сцен отрезка' },
          { step: 'cut', text: file },
          { step: 'check', text: file },
          { step: 'index', text: id },
          { step: 'embedding', text: EMBED_RU },
        ],
        notes: [
          fetchNote(video, 'GIF режется'),
          `Из отрезка ${g(start)}–${g(end)} с будет нарезан беззвучный GIF в банк мемов канала ${named(channel)}.`,
          'Смены сцен внутри отрезка станут известны после прогона\u00a0— на них GIF прыгнет; отрезок сужают по листу кадров.',
          PENDING,
          REINDEX,
        ],
      };
    }
    // лист кадров
    const out = body.out ?? null;
    if (out !== null && (typeof out !== 'string' || /[/\\]|\.\./.test(out)))
      return {
        refusal: problem(
          422,
          'bad_params',
          'Имя листа кадров\u00a0— одно имя файла, без папок и «..».',
          ['out must be a plain file name'],
        ),
      };
    const name = (out as string | null) ?? 'sheet.jpg';
    if (!/\.(jpe?g|png)$/i.test(name))
      return { refusal: problem(422, 'bad_suffix', 'лист кадров\u00a0— файл .jpg или .png') };
    const start = body.start ?? 0;
    const end = body.end ?? null;
    const every = body.every ?? 2;
    if (
      typeof start !== 'number' ||
      typeof every !== 'number' ||
      (end !== null && typeof end !== 'number')
    )
      return {
        refusal: problem(422, 'bad_span', 'начало, конец и шаг между кадрами\u00a0— в секундах'),
      };
    if (start < 0 || every <= 0 || (end !== null && (end as number) <= start))
      return {
        refusal: problem(
          422,
          'bad_span',
          'нужны начало не меньше 0, шаг больше 0 и конец позже начала',
        ),
      };
    const frames =
      end === null ? null : Math.max(1, Math.ceil(((end as number) - start) / every - 1e-9));
    if (frames !== null && frames > MAX_FRAMES)
      return {
        refusal: problem(
          422,
          'too_many_frames',
          `лист кадров вышел бы на ${frames} кадров (не больше ${MAX_FRAMES} кадров): сузьте отрезок или увеличьте шаг между кадрами (сейчас ${g(every)} с)`,
          [`the sheet would hold ${frames} frames, over the ${MAX_FRAMES} ceiling`],
        ),
      };
    const overwrites = state.sheets.includes(name);
    const till = end === null ? 'конца видео' : `${g(end as number)} с`;
    return {
      params: { video, start, end, every, out: name, local: false },
      fields: {
        id: null,
        file: `_desk/sheets/${name}`,
        will_fetch: 'yt-dlp',
        url: null,
        video,
        source_url: null,
        span: { start_s: start, end_s: end, every_s: every, frames },
        tags: null,
        cached: state.cached.includes(video),
        sheet: `inserts/${bankName(channel)}/_desk/sheets/${name}`,
        sheet_url: `/api/memes/${channel}/sheets/${name}`,
        overwrites,
      },
      steps: [
        { step: 'download', text: videoSays(video) },
        { step: 'frames', text: frames === null ? 'кадры' : `${frames} кадров` },
        { step: 'sheet', text: 'склейка листа и смены сцен' },
      ],
      notes: [
        fetchNote(video, 'кадры берутся'),
        `Лист: кадр каждые ${g(every)} с от ${g(start)} с до ${till}\u00a0— ${
          frames === null
            ? `число кадров станет известно после извлечения (если больше ${MAX_FRAMES}\u00a0— отказ)`
            : `${frames} кадров`
        }; и смены сцен этого отрезка.`,
        'Лист ляжет в папку листов кадров банка; в банк ничего не добавляется.',
        ...(overwrites ? ['Лист с таким именем уже есть\u00a0— будет перезаписан.'] : []),
      ],
    };
  }

  const addFp = (channel: string, kind: AddKind, params: Record<string, unknown>) =>
    ctx.hash(JSON.stringify({ i: bank(channel).entries, kind, params, s: state.sheets }));

  function addPlan(channel: string, kind: AddKind, raw: unknown): JobReply {
    state.plans.push({ kind, body: raw });
    const c = addCompute(channel, kind, raw);
    if ('refusal' in c) return c.refusal;
    const gd = guard(channel);
    const why = gd ? gd.why : null;
    const ok = !why;
    const fp = addFp(channel, kind, c.params);
    let confirm: string | null = null;
    if (ok) {
      confirm = `meme-${kind.replace('_', '-')}-${++seq}`;
      tokens.set(confirm, {
        channel,
        kind,
        fp,
        params: c.params,
        expires: Date.now() + state.life * 1000,
      });
    }
    const body = {
      action: ACTION[kind],
      channel,
      bank: bankName(channel),
      kind,
      dry_run: true as const,
      params: c.params,
      ...c.fields,
      steps: c.steps.map((x) => x.step),
      max_seconds: MAX_S[kind],
      max_seconds_word: human(MAX_S[kind]),
      notes: c.notes,
      ok,
      why,
      job: gd?.job ?? null,
      machine_job: gd?.machine_job ?? null,
      index_fingerprint: ctx.hash(JSON.stringify(bank(channel).entries)),
      fingerprint: fp,
      confirm,
      expires_in_s: confirm ? state.life : null,
    };
    return { status: 200, body };
  }

  /** Итог задачи по шагам — банк меняется здесь (новая запись `pending`, лист кадров). */
  function addFinish(channel: string, kind: AddKind, params: Record<string, unknown>) {
    const b = bank(channel);
    // Видео скачано один раз — дальше лист и GIF берут его из кэша банка.
    if (typeof params.video === 'string' && !state.cached.includes(params.video))
      state.cached.push(params.video);
    const embedding = {
      done: true,
      line: `embedded ${b.entries.length + 1}`,
      error: null,
      en: null,
      fatal: false,
    };
    if (kind === 'embed') return { bank: bankName(channel), embedding };
    if (kind === 'sheet') {
      const name = params.out as string;
      if (!state.sheets.includes(name)) state.sheets.push(name);
      const start = params.start as number;
      const end = params.end as number | null;
      return {
        sheet: `inserts/${bankName(channel)}/_desk/sheets/${name}`,
        sheet_url: `/api/memes/${channel}/sheets/${name}`,
        scene_cuts: state.sceneCuts.filter((t) => t >= start && (end === null || t <= end)),
      };
    }
    const id = params.meme_id as string;
    const gif = kind === 'add_gif';
    const suffix = gif
      ? '.gif'
      : (/\.[a-z0-9]+$/i.exec(new URL(params.url as string).pathname)?.[0] ?? '.jpg').toLowerCase();
    const entry: IndexEntry = {
      id,
      file: `${id}${suffix}`,
      description: params.description as string,
      tags: params.tags as string[],
      source_url: (params.source_url as string | undefined) ?? (params.video as string),
      review: 'pending',
      notes: `${kind} 2026-10-16 (by user, via center)`,
      ...(gif ? { clip: { start_s: params.start as number, end_s: params.end as number } } : {}),
    };
    b.entries.push(entry);
    const start = params.start as number;
    const end = params.end as number;
    return {
      entry: { ...entry, urls: urls(channel, entry, id) },
      file: entry.file,
      size: gif ? [480, 270] : [600, 450],
      ...(gif
        ? {
            duration_s: Math.round((end - start) * 100) / 100,
            cuts_inside: state.sceneCuts.filter((t) => t > start && t < end),
          }
        : { trim_note: state.trimNote?.en ?? null, trim_note_ru: state.trimNote?.ru ?? null }),
      bank: bankName(channel),
      embedding,
    };
  }

  /** Провал задачи по шагам словами фабрики: у добавлений — скачивание, у признаков — модель. */
  function addError(r: Rec): S['MemeJobError'] {
    if (state.jobError) return state.jobError;
    const p = (r.job.params ?? {}) as Record<string, unknown>;
    if (r.job.kind === 'embed')
      return {
        code: 'embed_failed',
        text: 'Признаки для поиска похожих мемов не пересчитаны: модель не загрузилась.',
        en: 'embed: model failed to load',
        log_tail: null,
      };
    if (r.job.kind === 'add_image')
      return {
        code: 'download_failed',
        text: `${String(p.url)} не скачан: сервер ответил 404\u00a0— картинка не добавлена, банк не менялся.`,
        en: 'HTTP Error 404: Not Found',
        log_tail: `download ${String(p.url)}\nurllib.error.HTTPError: HTTP Error 404: Not Found`,
      };
    return {
      code: 'video_failed',
      text: 'видео не получено: yt-dlp не скачал его (видео недоступно)\u00a0— банк не менялся.',
      en: 'ERROR: [youtube] Video unavailable',
      log_tail: 'yt-dlp -f bv*[height<=720]\nERROR: [youtube] Video unavailable',
    };
  }

  // ---- запуск и ход
  /** Параметры задачи (`meme_id`, как у `start_job`) → поля плана (`id`). */
  const raw = (_kind: Kind, p: Record<string, unknown>) =>
    'meme_id' in p ? { ...p, id: p.meme_id } : p;

  function launch(channel: string, kind: Kind, params: Record<string, unknown>): Rec {
    const b = bank(channel);
    const bankId = bankName(channel);
    let items: string[];
    let finish: () => Record<string, unknown>;
    let steps: Rec['steps'];
    if (ADD_KINDS.includes(kind)) {
      const c = addCompute(channel, kind as AddKind, raw(kind, params));
      if ('refusal' in c) throw new Error(`${kind} params refused`);
      steps = c.steps;
      items = c.steps.map((x) => x.step);
      finish = () => addFinish(channel, kind as AddKind, params);
    } else if (kind === 'cutout') {
      const c = cutoutCompute(channel, params);
      if ('refusal' in c) throw new Error('cutout params refused');
      items = c.made.map((m) => m.id);
      finish = () => {
        const made: Record<string, unknown>[] = [];
        const refused: Record<string, unknown>[] = [];
        for (const id of items) {
          const e = b.entries.find((x) => x.id === id);
          if (!e) continue;
          const no = state.refuse[id];
          if (no) {
            e.cutout_asset = { refused: no };
            refused.push({ id, reason: no, urls: urls(channel, e, id) });
          } else {
            e.cutout_asset = {
              file: `${id}.cutout.png`,
              coverage: 0.44,
              bbox_px: [48, 20, 512, 340],
            };
            made.push({
              id,
              file: `${id}.cutout.png`,
              bbox_px: [48, 20, 512, 340],
              coverage: 0.44,
              urls: urls(channel, e, id),
            });
          }
        }
        return {
          made,
          refused,
          unchanged: c.unchanged,
          missing: c.missing,
          outside_bank: [],
          written: made.length > 0 || refused.length > 0,
        };
      };
    } else {
      const t = trimRows(channel, params);
      items = t.trim.map((r) => r.id);
      finish = () => {
        b.bands = b.bands.filter((x) => !items.includes(x.id));
        for (const r of t.trim) {
          const e = b.entries.find((x) => x.id === r.id);
          if (e && r.recut)
            e.cutout_asset = {
              refused: 'картинку обрезали\u00a0— вырезку нужно сделать заново',
              refused_en: 'file missing - run meme_desk.py cutout',
            };
        }
        return {
          trim: t.trim,
          left: t.left,
          under: t.under,
          changed: items,
          originals: `${b.folder}/_desk/originals/`,
          embedding: state.embedFail
            ? {
                done: false,
                line: null,
                error:
                  'Признаки для поиска похожих мемов не пересчитались: модель не загрузилась. Картинки обрезаны, похожие ищутся по старым признакам до пересчёта.',
                en: 'embed: model failed to load',
                fatal: false,
              }
            : { done: true, line: `embedded ${items.length}`, error: null, en: null, fatal: false },
        };
      };
    }
    const id = `job-${kind === 'trim_blank' ? 'trim' : kind.replace('_', '-')}-${++seq}`;
    const rec: Rec = {
      channel,
      items,
      tick: 0,
      outcome: state.outcome,
      finish,
      steps,
      job: {
        job_id: id,
        kind,
        kind_word: KIND_WORD[kind],
        bank: bankId,
        state: 'running',
        state_word: STATE_WORD.running,
        done: false,
        started_at: now(),
        ended_at: null,
        pid: 4242,
        alive: true,
        progress: steps
          ? { step: steps[0]!.step, i: 1, of: steps.length, text: steps[0]!.text }
          : { step: kind === 'cutout' ? 'cutout' : 'trim', i: 0, of: items.length, text: '' },
        result: null,
        error: null,
        log: `${b.folder}/_desk/jobs/${id}.log`,
        by: 'user',
        via: 'center',
        params,
        max_seconds: steps ? MAX_S[kind as AddKind] : null,
        poll_s: state.pollS,
      },
    };
    jobs.unshift(rec);
    return rec;
  }

  function start(channel: string, kind: Kind, raw: unknown): JobReply {
    const token = (raw as { confirm?: unknown } | null)?.confirm;
    const t = typeof token === 'string' ? tokens.get(token) : undefined;
    if (!t || t.channel !== channel)
      return problem(409, 'confirm_unknown', 'Подтверждение не найдено - посмотрите план заново.');
    if (t.kind !== kind)
      return problem(
        409,
        'confirm_mismatch',
        'Подтверждение от другого плана - посмотрите план заново.',
      );
    const bankId = bankName(channel);
    const r = running(bankId);
    // `job_active` — до траты токена: план цел, задача идёт.
    if (r)
      return problem(
        409,
        'job_active',
        `На банке ${bankId} идёт задача «${r.job.kind_word}» (${r.job.job_id}); дождитесь её конца (отмены нет).`,
      );
    tokens.delete(token as string);
    if (t.expires <= Date.now())
      return problem(409, 'confirm_expired', 'Подтверждение устарело - посмотрите план заново.');
    if (state.failStart) {
      const f = state.failStart;
      state.failStart = null;
      return problem(f.status, f.code, f.message);
    }
    if (state.elsewhere)
      return problem(
        409,
        'job_running',
        `На машине уже идёт задача ${state.elsewhere.job_id} («${state.elsewhere.kind_word}») - одна задача на машину, дождитесь её конца.`,
      );
    if (kind === 'cutout' && !state.vision.available)
      return problem(
        409,
        'cutout_unavailable',
        `Вырезка на этой машине недоступна: ${state.vision.reason}`,
      );
    const fp = ADD_KINDS.includes(kind)
      ? { fp: addFp(channel, kind as AddKind, t.params) }
      : kind === 'cutout'
        ? cutoutCompute(channel, t.params)
        : trimRows(channel, t.params);
    if (!('fp' in fp) || fp.fp !== t.fp)
      return problem(
        409,
        'check_changed',
        'Банк изменился с момента плана - задача не запущена; посмотрите план заново.',
        ["the fingerprint of index.json + the dry run differs from the plan's"],
      );
    const rec = launch(channel, kind, t.params);
    const body: S['MemeJobStarted'] = {
      action: ACTION[kind],
      channel,
      kind,
      bank: bankId,
      job_id: rec.job.job_id,
      log: rec.job.log,
      poll_s: state.pollS,
      status_url: `/api/memes/${channel}/jobs/${rec.job.job_id}`,
    };
    return { status: 200, body };
  }

  /** Коммит итога (`commit_on_done` + `commit`), как его пишет стол фабрики (CF-0847). */
  function commitOf(r: Rec): Pick<S['MemeJob'], 'commit_on_done' | 'commit'> {
    const st = state.commit;
    if (!st) return { commit_on_done: null, commit: null };
    const b = bank(r.channel);
    const paths = [`${b.folder}/index.json`];
    if (st === 'committed')
      return {
        commit_on_done: true,
        commit: { status: st, sha: '3f9c2a1b7d4e'.padEnd(40, '0'), committed: paths, detail: null },
      };
    if (st === 'refused')
      return {
        commit_on_done: true,
        commit: {
          status: st,
          sha: null,
          committed: null,
          detail: `fatal: Unable to create '.git/index.lock': File exists. | touched: ${paths.join(', ')}`,
        },
      };
    return {
      commit_on_done: true,
      commit: { status: st, sha: null, committed: null, detail: null },
    };
  }

  /** Шаг задачи — на каждый опрос: «i из N», у обрезки ещё признаки для поиска, потом итог. */
  function advance(r: Rec) {
    if (r.job.state !== 'running') return;
    if (state.holdAt !== null && r.tick >= state.holdAt) return;
    r.tick += 1;
    const n = r.items.length;
    const steps = r.job.kind === 'trim_blank' ? n + 1 : n;
    const end = (st: S['MemeJob']['state'], error: S['MemeJobError'] | null) => {
      r.job = {
        ...r.job,
        state: st,
        state_word: STATE_WORD[st],
        done: true,
        alive: false,
        ended_at: now(),
        poll_s: null,
        error,
      };
    };
    if (r.steps) {
      const late = r.tick > Math.min(1, r.steps.length - 1);
      if (r.outcome === 'failed' && late) return end('failed', addError(r));
      if (r.outcome === 'interrupted' && late)
        return end('interrupted', {
          code: 'job_interrupted',
          text: 'Задача оборвалась: её процесс пропал, не дописав итог (машину перезагрузили или процесс остановили). Банк мог измениться частично.',
          en: 'the job process is gone without a result',
          log_tail: null,
        });
      if (r.tick < r.steps.length) {
        const st = r.steps[r.tick]!;
        r.job = {
          ...r.job,
          progress: { step: st.step, i: r.tick + 1, of: r.steps.length, text: st.text },
        };
        return;
      }
      const result = r.finish();
      end('done', null);
      r.job = { ...r.job, result, ...commitOf(r) };
      return;
    }
    if (r.outcome === 'failed' && r.tick > Math.min(1, n)) {
      const at = r.items[0] ?? '';
      end('failed', {
        code: 'job_crashed',
        text: `Задача упала на «${at}»: распознавание вернуло ошибку. Готовые до этого вырезки записаны, остальное не тронуто.`,
        en: `job crashed at ${at}: VNGenerateForegroundInstanceMaskRequest failed`,
        log_tail: `cutout ${at}\nTraceback (most recent call last):\n  File "cutout.py", line 88, in cut\nRuntimeError: Vision request failed (-6)`,
      });
      return;
    }
    if (r.outcome === 'interrupted' && r.tick > Math.min(1, n)) {
      end('interrupted', {
        code: 'job_interrupted',
        text: 'Задача оборвалась: её процесс пропал, не дописав итог (машину перезагрузили или процесс остановили). Банк мог измениться частично.',
        en: 'the job process is gone without a result',
        log_tail: null,
      });
      return;
    }
    if (r.tick <= n) {
      r.job = {
        ...r.job,
        progress: { ...r.job.progress!, i: r.tick, of: n, text: r.items[r.tick - 1]! },
      };
      return;
    }
    if (r.tick <= steps) {
      r.job = {
        ...r.job,
        progress: {
          step: 'embedding',
          i: null,
          of: null,
          text: 'признаки для поиска похожих мемов',
        },
      };
      return;
    }
    const result = r.finish();
    end('done', null);
    r.job = { ...r.job, result, ...commitOf(r) };
  }

  function one(channel: string, id: string): JobReply {
    const r = jobs.find((x) => x.job.job_id === id && x.job.bank === bankName(channel));
    if (!r) return problem(404, 'unknown_job', `задачи '${id}' у банка нет`);
    advance(r);
    return { status: 200, body: structuredClone(r.job) };
  }

  function list(channel: string, limit: number): JobReply {
    const bankId = bankName(channel);
    const mine = jobs.filter((r) => r.job.bank === bankId);
    const run = running(bankId);
    const body: S['MemeJobs'] = {
      channel,
      bank: bankId,
      running: run ? structuredClone(run.job) : null,
      jobs: mine.slice(0, limit).map((r) => structuredClone(r.job)),
      poll_s: run ? state.pollS : null,
    };
    return { status: 200, body };
  }

  return {
    state,
    jobs,
    cutoutPlan,
    trimPlan,
    /** CC-0133: план добавления картинки и GIF, листа кадров, пересчёта признаков. */
    addPlan,
    /** Лист кадров банка (`GET …/sheets/{name}`): есть ли такой. */
    hasSheet: (name: string) => state.sheets.includes(name),
    start,
    one,
    list,
    /** Идущая задача банка — для стола (`MemeDesk.job`). */
    deskJob: (bankId: string) => {
      const r = running(bankId);
      return r ? ref(r) : null;
    },
    /** Запись банка закрыта: идёт задача (`job_active`, отмены нет). */
    activeRefusal(channel: string): JobReply | null {
      const bankId = bankName(channel);
      const r = running(bankId);
      return r
        ? problem(
            409,
            'job_active',
            `На банке ${bankId} идёт задача «${r.job.kind_word}» (${r.job.job_id}); дождитесь её конца (отмены нет).`,
          )
        : null;
    },
    guard,
    /** Задача уже идёт (страницу открыли посреди неё): `cutout` — по плану без «да». */
    seed(channel: string, kind: Kind, params: Record<string, unknown> = {}) {
      return launch(
        channel,
        kind,
        kind === 'cutout' ? { ids: null, force: false, ...params } : params,
      ).job.job_id;
    },
    /** Все выданные подтверждения устарели («промотать время»). */
    expireTokens() {
      for (const t of tokens.values()) t.expires = 0;
    },
  };
}

export type MemeJobsBackend = ReturnType<typeof createMemeJobs>;
