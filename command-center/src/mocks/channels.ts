// Подставной API каналов (CC-0006 фабрики) — с состоянием: правка, проверка, конфликт,
// блокировка батчем, история и «вернуть». Общий для Vitest (MSW, src/mocks/handlers.ts) и
// Playwright (tests/e2e/fixtures.ts). Тела ответов типизированы сгенерированными типами
// контракта; данные выдуманные, но по форме как у живой фабрики. Импорты — относительные.
import type { components } from '../api/schema.gen';
import { createChannelDataState, routeChannelData } from './channelData';
import {
  ID_PATTERN,
  LANGUAGE_PATTERN,
  NAME_MAX,
  NO_PIPELINE_LINE,
  RESERVED_IDS,
  renderChannel,
  TEMPLATE_BASE,
} from './channelTemplate';

type S = components['schemas'];
type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = { [k: string]: Json };

/** Конфиг example-film — отформатирован «руками» (строчные массивы), чтобы ловить переформатирование. */
export const REEL_CONFIG_TEXT = `{
  "channel_id": "example-film",
  "former_channel_ids": ["legacy-film"],
  "display_name": "ExampleFilm",
  "language": "en",
  "scope": {
    "content_type": ["tv_series", "film", "animation"],
    "min_popularity_score": 45,
    "min_popularity_score_note": "CF-0060: a candidate below this popularity score is not taken into a batch. Re-derived 2026-09-03 after the RSS signal began counting publishing houses.",
    "max_titles_per_batch": 5
  },
  "voice_profile": {
    "engine": "kokoro",
    "voice": "am_puck",
    "speed": 1.1,
    "note": "The voice of the narration: Kokoro voice id and speed. Changing either requires re-measuring the speaking rate."
  },
  "video_editor": {
    "max_video_seconds": 58,
    "burn_subtitles": true,
    "max_video_seconds_note": "Hard ceiling of a finished video, seconds: YouTube counts a Short up to 60."
  },
  "batch_schedule": {
    "window": "02:00",
    "tz": "Europe/Moscow",
    "window_hours": 3,
    "min_feed_days": 3,
    "batch_feed_days": 3,
    "note": "CF-0592 (grill 06.10): when the day's batch of this channel may start by the schedule."
  },
  "stance": "channels/example-film/stance.json",
  "stance_note": "The channel's position file: what the channel is and is not."
}
`;

export const REEL_STANCE_TEXT = `{
  "channel_id": "example-film",
  "position": {
    "one_line": "Facts about films and series, checked at the source.",
    "one_line_note": "The channel's position in one line - shown to every writing stage."
  }
}
`;

const STUB = (id: string, name: string, accent: string) => `{
  "channel_id": "${id}",
  "display_name": "${name}",
  "theme": {
    "bg": "#050A14",
    "accent": "${accent}",
    "note": "The on-screen theme of the channel, from its brand."
  },
  "status": {
    "pipeline": false,
    "reason": "конвейера нет - батча не будет"
  }
}
`;

const CHECKS: S['ConfigCheck'][] = [
  { block: 'theme', check: 'channel_theme_errors', on_stub: true },
  { block: 'scope', check: 'channel_scope_errors', on_stub: false },
  { block: 'voice_profile', check: 'voice_profile_errors', on_stub: false },
  { block: 'video_editor', check: 'video_editor_errors', on_stub: false },
  { block: 'batch_schedule', check: 'batch_schedule_errors', on_stub: false },
];

const kindOf = (v: Json): S['ConfigField']['kind'] =>
  v === null
    ? 'null'
    : Array.isArray(v)
      ? 'array'
      : typeof v === 'object'
        ? 'object'
        : (typeof v as 'string' | 'number' | 'boolean');

const isProseKey = (k: string) => k === 'note' || k.endsWith('_note');
const isObj = (v: Json | undefined): v is Obj =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** Описание полей так, как его отдаёт фабрика (`channel_fields`): пояснение — из `*_note` / `note`. */
export function describeFields(doc: Obj, file: 'config' | 'stance'): S['ConfigField'][] {
  const rows: S['ConfigField'][] = [];
  const walk = (o: Obj, prefix: string[]) => {
    for (const [k, v] of Object.entries(o)) {
      const p = [...prefix, k];
      const own = o[`${k}_note`];
      const inner = isObj(v) ? v.note : undefined;
      const note = isProseKey(k)
        ? null
        : typeof own === 'string'
          ? own
          : typeof inner === 'string'
            ? inner
            : null;
      const checked =
        file === 'config' ? CHECKS.filter((c) => c.block === p[0]).map((c) => c.check) : [];
      rows.push({
        file,
        path: p,
        kind: kindOf(v),
        prose: isProseKey(k),
        note,
        checked_by: checked,
      });
      if (isObj(v)) walk(v, p);
    }
  };
  walk(doc, []);
  return rows;
}

/** Ревизия обоих файлов, как у фабрики: хеш содержимого (здесь — FNV-1a). */
export function revisionOf(config: string, stance: string | null): string {
  let h = 0xcbf29ce484222325n;
  for (const ch of `${config}\0${stance ?? ''}`) {
    h ^= BigInt(ch.codePointAt(0)!);
    h = (h * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return h.toString(16).padStart(16, '0');
}

/** Строка без русского у фабрики (проверка позиции): показать `text`. */
const NO_RU = { code: null, text_ru: null } as const;

/**
 * Строка проверки фабрики, как её собирает `check_finding` (CF-0657): английская `text`,
 * код причины и русская `text_ru` — «<что проверяли>, поле <путь> (сейчас <значение>): <почему>.»
 */
function finding(
  field: string,
  text: string,
  code: string,
  title: string,
  value: unknown,
  reason: string,
): S['CheckLine'] {
  const now = value === undefined || value === null ? 'пусто' : JSON.stringify(value);
  return { field, text, code, text_ru: `${title}, поле ${field} (сейчас ${now}): ${reason}.` };
}

/**
 * Проверка фабрики на подставном канале: несколько правил, тексты — как у её проверок.
 * Проверка позиции русской строки не даёт (`code`/`text_ru` — null, как `_stance_errors` API).
 */
function configErrors(id: string, cfg: Obj, stance: Obj | null): S['CheckLine'][] {
  const out: S['CheckLine'][] = [];
  const scope = isObj(cfg.scope) ? cfg.scope : null;
  const score = scope?.min_popularity_score;
  if (scope && (typeof score !== 'number' || score < 0 || score > 100)) {
    out.push(
      finding(
        'scope.min_popularity_score',
        `${id}.json.scope.min_popularity_score: must be a number from 0 to 100, got ${JSON.stringify(score)}`,
        'content_researcher_invalid',
        'Настройки сценариста',
        score,
        'значение не подходит сценаристу - он его не прочтёт',
      ),
    );
  }
  const ve = isObj(cfg.video_editor) ? cfg.video_editor : null;
  const secs = ve?.max_video_seconds;
  if (ve && (typeof secs !== 'number' || secs > 60)) {
    out.push(
      finding(
        'video_editor.max_video_seconds',
        `${id}.json.video_editor.max_video_seconds: a Short is at most 60 seconds, got ${JSON.stringify(secs)}`,
        'video_editor_invalid',
        'Настройки монтажёра',
        secs,
        'значение не подходит монтажёру - с ним он не соберёт ролик',
      ),
    );
  }
  if (stance && stance.channel_id !== id) {
    out.push({
      text: `stance.json.channel_id: must be '${id}' (the channel it is the position of), got ${JSON.stringify(stance.channel_id)}`,
      field: 'stance.channel_id',
      code: null,
      text_ru: null,
    });
  }
  return out;
}

function leafPaths(a: Json | undefined, b: Json | undefined, prefix = ''): string[] {
  if (isObj(a) && isObj(b)) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
    return keys.flatMap((k) => leafPaths(a[k], b[k], prefix ? `${prefix}.${k}` : k));
  }
  return JSON.stringify(a) === JSON.stringify(b) ? [] : [prefix || '(весь файл)'];
}

type Channel = {
  id: string;
  name: string;
  formers: string[];
  noPipeline: string | null;
  config: string;
  stance: string | null;
  lock: string | null;
  /** Видят ли батч чтения (false — «устаревшее открыто»: увидит только запись). */
  lockSeen: boolean;
};

/** Свежесть ответа о батчах (CC-0041 фабрики): когда начался скан, сколько ему, идёт ли новый. */
export type Freshness = Pick<S['ChannelLock'], 'checked_at' | 'age_s' | 'checking'>;

type Snapshot = { config: string; stance: string | null };

export type Reply<T> =
  { status: 200; body: T } | { status: 400 | 404 | 409 | 422 | 500; body: S['ChannelProblem'] };

const problem = (
  status: 400 | 404 | 409 | 422 | 500,
  code: S['ChannelProblem']['code'],
  message: string,
  extra: Partial<S['ChannelProblem']> = {},
): Reply<never> => ({
  status,
  body: { message, code, details: [], errors: [], batches: [], ...extra },
});

let commitNo = 0;
const sha = () => (++commitNo).toString(16).padStart(8, '0').repeat(5);

/** Подставная фабрика с тремя каналами; каждый тест создаёт свою. */
export function createChannelsBackend() {
  const channels: Channel[] = [
    {
      id: 'example-film',
      name: 'ExampleFilm',
      formers: ['legacy-film'],
      noPipeline: null,
      config: REEL_CONFIG_TEXT,
      stance: REEL_STANCE_TEXT,
      lock: null,
      lockSeen: true,
    },
    {
      id: 'example-science',
      name: 'ExampleScience',
      formers: [],
      noPipeline: 'конвейера нет - батча не будет (конвейер - веха 2.3.2)',
      config: STUB('example-science', 'ExampleScience', '#3DD68C'),
      stance: null,
      lock: null,
      lockSeen: true,
    },
    {
      id: 'example-tech',
      name: 'ExampleTech',
      formers: [],
      noPipeline: 'конвейера нет - батча не будет (конвейер - веха 2.3.3)',
      config: STUB('example-tech', 'ExampleTech', '#22D3EE'),
      stance: null,
      lock: null,
      lockSeen: true,
    },
  ];
  const history = new Map<string, S['HistoryEntry'][]>(channels.map((c) => [c.id, []]));
  const before = new Map<string, Snapshot>();
  /** Тела всех PUT, POST revert и создания — тесты сверяют, что ушло (`base`, `config_text`). */
  const writes: { kind: 'save' | 'revert' | 'create'; id: string; body: unknown }[] = [];
  /** Идёт батч «где-то» (не у одного из каналов): создание канала закрыто. */
  let openBatch: string | null = null;
  let openBatchSeen = true;
  /** Последний известный скан батчей; `checkingReads` — столько следующих чтений скажут `checking`. */
  let scan = { checked_at: '2026-10-10T09:00:00Z', age_s: 4.2 };
  let checkingReads = 0;
  /** Свежесть для ответа на чтение: последний скан; пока `checkingReads` — «идёт новый». */
  const readMeta = (): Freshness => {
    const checking = checkingReads > 0;
    if (checking) checkingReads -= 1;
    return { ...scan, checking };
  };
  /** Запись сканирует заново: свежесть нулевая. */
  const writeMeta = (): Freshness => ({ checked_at: scan.checked_at, age_s: 0, checking: false });

  history.get('example-film')!.push({
    commit: 'f40c69aa78bae63ccf8e636f5b52dec20ad7bbae',
    short: 'f40c69a',
    at: '2026-10-09T22:33:47+03:00',
    author: 'Оператор фабрики',
    subject: 'WIP CF-0645: the late reserve round in the run plan',
    action: null,
    reverts: null,
    files: ['channels/example-film.json', 'docs/pipeline.md'],
    from_center: false,
    revertible: false,
    why_not:
      'в этом коммите менялись и другие файлы фабрики - отменить только правку канала нельзя',
    reverted_by: null,
  });

  const find = (id: string) => channels.find((c) => c.id === id || c.formers.includes(id));
  const rev = (c: Channel) => revisionOf(c.config, c.stance);
  const lockOf = (c: Channel, meta: Freshness, write = false): S['ChannelLock'] =>
    c.lock && (write || c.lockSeen)
      ? {
          ...meta,
          locked: true,
          message: c.lock,
          batches: [
            {
              dir: `pipeline/runs/${c.id}/2026-10-10T0200Z`,
              channel: c.id,
              rebuild: false,
              last: '2026-10-10T02:14:00Z',
            },
          ],
        }
      : { ...meta, locked: false, message: null, batches: [] };

  const parse = (text: string, what: string): { doc: Obj } | { fail: Reply<never> } => {
    try {
      const doc = JSON.parse(text) as Json;
      if (isObj(doc)) return { doc };
      return { fail: problem(422, 'not_json', `${what} должен быть JSON-объектом {…}.`) };
    } catch (e) {
      return {
        fail: problem(422, 'not_json', `${what} - не JSON: ${(e as Error).message}.`, {
          details: [String(e)],
        }),
      };
    }
  };

  const detail = (c: Channel, meta: Freshness = writeMeta()): S['ChannelDetail'] => {
    const cfg = JSON.parse(c.config) as Obj;
    const stance = c.stance ? (JSON.parse(c.stance) as Obj) : null;
    return {
      id: c.id,
      display_name: c.name,
      no_pipeline: c.noPipeline,
      revision: rev(c),
      config: cfg,
      config_text: c.config,
      config_path: `channels/${c.id}.json`,
      stance,
      stance_text: c.stance,
      stance_path: c.stance ? `channels/${c.id}/stance.json` : null,
      fields: [
        ...describeFields(cfg, 'config'),
        ...(stance ? describeFields(stance, 'stance') : []),
      ],
      checks: CHECKS,
      errors: configErrors(c.id, cfg, stance),
      lock: lockOf(c, meta),
    };
  };

  /** Кандидат правки: тексты обоих файлов или отказ. */
  const candidate = (c: Channel, body: S['ChannelEdit']) => {
    const config = body.config_text ?? (body.config ? JSON.stringify(body.config, null, 2) : null);
    const stance = body.stance_text ?? (body.stance ? JSON.stringify(body.stance, null, 2) : null);
    const cfgText = config ?? c.config;
    const stText = stance ?? c.stance;
    const cfg = parse(cfgText, 'Конфиг');
    if ('fail' in cfg) return cfg;
    let st: Obj | null = null;
    if (stText !== null) {
      const p = parse(stText, 'Позиция');
      if ('fail' in p) return p;
      st = p.doc;
    }
    return { cfgText, stText, cfg: cfg.doc, st };
  };

  const commit = (
    c: Channel,
    next: Snapshot,
    action: 'edit' | 'revert',
    reverts: string | null,
  ): Reply<S['SaveResult']> => {
    const oldCfg = JSON.parse(c.config) as Obj;
    const newCfg = JSON.parse(next.config) as Obj;
    const changed = [
      ...leafPaths(oldCfg, newCfg),
      ...leafPaths(
        c.stance ? (JSON.parse(c.stance) as Json) : null,
        next.stance ? (JSON.parse(next.stance) as Json) : null,
      ).map((p) => `позиция.${p}`),
    ];
    const id = sha();
    before.set(id, { config: c.config, stance: c.stance });
    c.config = next.config;
    c.stance = next.stance;
    const names = changed.length ? changed.join(', ') : 'форматирование';
    const subject =
      action === 'edit'
        ? `Канал ${c.name}: изменено ${names} (из центра)`
        : `Канал ${c.name}: возвращено ${names} - отмена правки ${reverts!.slice(0, 7)} (из центра)`;
    const files = [`channels/${c.id}.json`];
    history.get(c.id)!.unshift({
      commit: id,
      short: id.slice(0, 7),
      at: new Date(Date.UTC(2026, 9, 10, 9, commitNo)).toISOString().replace('.000Z', '+00:00'),
      author: 'Командный центр',
      subject,
      action,
      reverts,
      files,
      from_center: true,
      revertible: true,
      why_not: null,
      reverted_by: null,
    });
    return {
      status: 200,
      body: { commit: id, subject, changed, files, channel: detail(c) },
    };
  };

  const createLock = (meta: Freshness, write = false): S['ChannelLock'] => {
    const busy = channels.find((c) => c.lock && (write || c.lockSeen));
    const open = openBatch && (write || openBatchSeen) ? openBatch : null;
    if (!open && !busy) return { ...meta, locked: false, message: null, batches: [] };
    const channel = busy?.id ?? 'example-film';
    return {
      ...meta,
      locked: true,
      message:
        open ??
        `Идёт батч канала ${channel} (2026-10-10T0200Z): пока не закончится, канал не создать - коммит нового канала сдвинул бы код фабрики под идущим батчем (runlog записал бы это как code_drift).`,
      batches: [
        {
          dir: `pipeline/runs/${channel}/2026-10-10T0200Z`,
          channel,
          rebuild: false,
          last: '2026-10-10T02:14:00Z',
        },
      ],
    };
  };

  /** Проверка входов нового канала — тексты как у `shared/new_channel.py` `input_errors`. */
  const inputErrors = (v: { channel_id: string; display_name: string; language: string }) => {
    const out: S['CheckLine'][] = [];
    // Строка входа у фабрики уже русская: `text_ru` = `text`, кода причины нет (CC-0054).
    const row = (field: string, text: string) =>
      out.push({ field, text, code: null, text_ru: text });
    const { channel_id: cid, display_name: name, language: lang } = v;
    if (!cid) row('channel_id', 'channel_id: не задан');
    else if (!new RegExp(ID_PATTERN).test(cid))
      row(
        'channel_id',
        `channel_id: '${cid}' - не годится: латиница в нижнем регистре, цифры, дефис внутри, 2-40 знаков, первая - буква`,
      );
    else if (channels.some((c) => c.id === cid))
      row('channel_id', `channel_id: канал '${cid}' уже есть (channels/${cid}.json)`);
    else if (find(cid))
      row(
        'channel_id',
        `channel_id: '${cid}' - прежнее имя канала '${find(cid)!.id}' (former_channel_ids): это тот же канал`,
      );
    else if (RESERVED_IDS.includes(cid))
      row('channel_id', `channel_id: '${cid}' - служебное имя, не канал`);
    if (!name) row('display_name', 'display_name: не задано');
    else if (/[\r\n]/.test(name) || name.length > NAME_MAX)
      row('display_name', `display_name: одна строка до ${NAME_MAX} знаков`);
    else {
      const twin = channels.find((c) => c.name.toLowerCase() === name.toLowerCase());
      if (twin) row('display_name', `display_name: '${name}' - уже название канала '${twin.id}'`);
    }
    if (!new RegExp(LANGUAGE_PATTERN).test(lang))
      row('language', `language: '${lang}' - не код языка (en, ru, pt-BR...)`);
    return out;
  };

  /** Позиция из мастера (`stance_text`) вместо шаблонной: как `_new_channel` фабрики. */
  const stanceRows = (cid: string, text: string): S['CheckLine'][] => {
    let doc: Json;
    try {
      doc = JSON.parse(text) as Json;
    } catch (e) {
      return [{ field: 'stance', text: `stance.json: не JSON: ${(e as Error).message}`, ...NO_RU }];
    }
    if (!isObj(doc))
      return [{ field: 'stance', text: 'stance.json: is not a JSON object', ...NO_RU }];
    if (doc.channel_id !== cid)
      return [
        {
          field: 'stance.channel_id',
          text: `stance.json.channel_id: must be '${cid}' (the channel it is the position of), got ${JSON.stringify(doc.channel_id ?? null)}`,
          ...NO_RU,
        },
      ];
    return [];
  };

  return {
    writes,
    /** Данные канала (CC-0115): концовка, источники фактов, партнёрские ссылки. */
    data: createChannelDataState(),
    known: (id: string) => channels.some((c) => c.id === id || c.formers.includes(id)),
    /**
     * Сделать вид, что идёт батч (любой): создание канала закрыто; null — снять.
     * `seen: false` — чтения его ещё не видят (последний скан был до батча), увидит запись.
     */
    openBatch(message: string | null, seen = true) {
      openBatch = message;
      openBatchSeen = seen;
    },
    /** Свежесть последнего скана; `checking` — столько следующих чтений скажут «идёт новый». */
    scan(next: { checked_at?: string; age_s?: number; checking?: number }) {
      scan = { ...scan, ...next };
      if (next.checking !== undefined) checkingReads = next.checking;
    },
    template(): Reply<S['ChannelTemplate']> {
      return { status: 200, body: { ...TEMPLATE_BASE, lock: createLock(readMeta()) } };
    },
    create(
      body: Omit<S['NewChannel'], 'dry_run'> & { dry_run?: boolean },
    ): Reply<S['CreateResult']> {
      const dry = body.dry_run === true;
      const v = {
        channel_id: (body.channel_id ?? '').trim(),
        display_name: (body.display_name ?? '').trim(),
        language: (body.language ?? '').trim() || 'en',
      };
      if (!dry) writes.push({ kind: 'create', id: v.channel_id, body });
      const errors = inputErrors(v);
      const files = errors.length ? [] : renderChannel(v);
      const stanceText = body.stance_text ?? null;
      if (stanceText !== null && files.length) {
        errors.push(...stanceRows(v.channel_id, stanceText));
        files[1] = { ...files[1]!, text: stanceText };
      }
      const lock = dry ? createLock(readMeta()) : createLock(writeMeta(), true);
      const out: S['CreateResult'] = {
        ok: errors.length === 0,
        dry_run: dry,
        channel_id: v.channel_id || null,
        files,
        errors,
        lock,
        commit: null,
        subject: null,
        channel: null,
      };
      if (dry) return { status: 200, body: out };
      if (lock.locked) {
        openBatchSeen = true; // скан записи — теперь последний известный
        for (const c of channels) c.lockSeen = true;
        return problem(409, 'batch_running', lock.message!, {
          batches: lock.batches,
          details: lock.batches.map((b) => b.dir),
        });
      }
      if (errors.length)
        return problem(
          422,
          'invalid',
          `Фабрика не приняла новый канал: ${errors.length} ${errors.length === 1 ? 'ошибка' : 'ошибки'} проверки. Ничего не создано.`,
          { errors, details: errors.map((e) => e.text) },
        );
      const c: Channel = {
        id: v.channel_id,
        name: v.display_name,
        formers: [],
        noPipeline: NO_PIPELINE_LINE,
        config: files[0]!.text,
        stance: files[1]!.text,
        lock: null,
        lockSeen: true,
      };
      channels.push(c);
      const id = sha();
      const subject = `Канал ${c.name}: создан (из центра)`;
      history.set(c.id, [
        {
          commit: id,
          short: id.slice(0, 7),
          at: new Date(Date.UTC(2026, 9, 10, 9, commitNo)).toISOString().replace('.000Z', '+00:00'),
          author: 'Командный центр',
          subject,
          action: 'create',
          reverts: null,
          files: files.map((f) => f.path),
          from_center: true,
          revertible: false,
          why_not: 'создание канала из центра не отменяется',
          reverted_by: null,
        },
      ]);
      return {
        status: 200,
        body: { ...out, ok: true, commit: id, subject, channel: detail(c) },
      };
    },
    /**
     * Сделать вид, что идёт батч канала (правка запрещена). `seen: false` — чтения его ещё
     * не видят («открыто» по прошлому скану), запись найдёт его и ответит 409.
     */
    lock(id: string, message: string | null, seen = true) {
      const c = find(id)!;
      c.lock = message;
      c.lockSeen = seen;
    },
    /** Правка «мимо центра»: ревизия меняется — следующая запись получит 409 conflict. */
    touch(id: string) {
      const c = find(id)!;
      c.config = c.config.replace(/\n$/, '\n\n');
    },
    list(): Reply<S['ChannelList']> {
      return {
        status: 200,
        body: {
          ...readMeta(),
          channels: channels.map((c) => ({
            id: c.id,
            display_name: c.name,
            former_ids: c.formers,
            no_pipeline: c.noPipeline,
            stance: c.stance !== null,
            locked: c.lock !== null && c.lockSeen,
            error: null,
            revision: rev(c),
          })),
        },
      };
    },
    detail(id: string): Reply<S['ChannelDetail']> {
      const c = find(id);
      if (!c) return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`);
      return { status: 200, body: detail(c, readMeta()) };
    },
    check(id: string, body: S['ChannelEdit']): Reply<S['CheckResult']> {
      const c = find(id);
      if (!c) return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`);
      const k = candidate(c, body);
      if ('fail' in k) return k.fail;
      const errors = configErrors(c.id, k.cfg, k.st);
      return { status: 200, body: { ok: errors.length === 0, errors } };
    },
    save(id: string, body: S['ChannelEdit']): Reply<S['SaveResult']> {
      writes.push({ kind: 'save', id, body });
      const c = find(id);
      if (!c) return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`);
      if (c.lock) {
        c.lockSeen = true; // скан записи — теперь последний известный: чтения видят батч
        return problem(409, 'batch_running', c.lock, {
          batches: lockOf(c, writeMeta(), true).batches,
        });
      }
      if (body.base && body.base !== rev(c))
        return problem(
          409,
          'conflict',
          'Конфиг изменился, пока вы его правили. Обновите страницу и повторите правку.',
          { details: [`base ${body.base} != revision ${rev(c)}`] },
        );
      const k = candidate(c, body);
      if ('fail' in k) return k.fail;
      if (k.cfg.channel_id !== c.id)
        return problem(
          422,
          'forbidden_change',
          'Эти поля из центра не меняются: channel_id (имя канала меняется переименованием, не правкой).',
        );
      const errors = configErrors(c.id, k.cfg, k.st);
      if (errors.length)
        return problem(
          422,
          'invalid',
          `Фабрика не приняла правку: ${errors.length} ${errors.length === 1 ? 'ошибка' : 'ошибки'} проверки. Ничего не сохранено.`,
          { errors, details: errors.map((e) => e.text) },
        );
      if (k.cfgText === c.config && k.stText === c.stance)
        return problem(400, 'nothing_changed', 'Изменений нет - сохранять нечего.');
      return commit(c, { config: k.cfgText, stance: k.stText }, 'edit', null);
    },
    history(id: string): Reply<S['ChannelHistory']> {
      const c = find(id);
      if (!c) return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`);
      return {
        status: 200,
        body: {
          id: c.id,
          files: [`channels/${c.id}.json`, ...(c.stance ? [`channels/${c.id}/stance.json`] : [])],
          entries: history.get(c.id)!,
        },
      };
    },
    revert(id: string, commitId: string, base: string | null): Reply<S['SaveResult']> {
      writes.push({ kind: 'revert', id, body: { base } });
      const c = find(id);
      if (!c) return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`);
      const row = history.get(c.id)!.find((e) => e.commit === commitId);
      if (!row) return problem(404, 'unknown_commit', 'Такой правки нет в истории этого канала.');
      if (c.lock) {
        c.lockSeen = true; // скан записи — теперь последний известный: чтения видят батч
        return problem(409, 'batch_running', c.lock, {
          batches: lockOf(c, writeMeta(), true).batches,
        });
      }
      if (base && base !== rev(c))
        return problem(
          409,
          'conflict',
          'Конфиг изменился, пока вы его правили. Обновите страницу и повторите правку.',
        );
      const snap = before.get(commitId);
      if (!row.revertible || !snap)
        return problem(409, 'not_revertible', row.why_not ?? 'Эту правку нельзя отменить.');
      const r = commit(c, snap, 'revert', commitId);
      row.reverted_by = r.status === 200 ? r.body.commit : null;
      row.revertible = false;
      row.why_not = 'уже возвращено';
      return r;
    },
  };
}

export type ChannelsBackend = ReturnType<typeof createChannelsBackend>;

/** Маршрутизатор подставного API каналов: метод + путь → ответ, null — не про каналы. */
export function routeChannels(
  backend: ChannelsBackend,
  method: string,
  url: URL,
  body: unknown,
): Reply<unknown> | null {
  const data = routeChannelData(backend.data, backend.known, method, url, body);
  // Свой тип ответа у данных канала (src/mocks/channelData.ts) — шире статусов этого роутера.
  if (data) return data as never;
  const m = url.pathname.match(
    /\/api\/channels(?:\/([^/]+))?(\/check|\/history(?:\/([^/]+)\/revert)?)?$/,
  );
  if (!m) return null;
  const [, raw, tail, commitId] = m;
  const id = raw ? decodeURIComponent(raw) : undefined;
  const edit = (body ?? {}) as S['ChannelEdit'];
  if (!id) {
    if (method === 'GET') return backend.list();
    if (method === 'POST') return backend.create((body ?? {}) as S['NewChannel']);
    return null;
  }
  // «template» — маршрут API, не канал (RESERVED_IDS фабрики).
  if (id === 'template' && !tail) return method === 'GET' ? backend.template() : null;
  if (!tail) {
    if (method === 'GET') return backend.detail(id);
    if (method === 'PUT') return backend.save(id, edit);
    return null;
  }
  if (tail === '/check' && method === 'POST') return backend.check(id, edit);
  if (tail === '/history' && method === 'GET') return backend.history(id);
  if (commitId && method === 'POST')
    return backend.revert(id, commitId, (edit as S['RevertRequest']).base ?? null);
  return null;
}

/** Канал есть в подставном списке каналов (по нынешнему id). */
export function isListed(backend: ChannelsBackend, id: string): boolean {
  const r = backend.list();
  return r.status === 200 && r.body.channels.some((c) => c.id === id);
}
