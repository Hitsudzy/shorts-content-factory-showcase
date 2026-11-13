// Подставной стол мемов (CC-0024 фабрики, договор 0.24.0) — с состоянием: обзор банков по
// каналам, стол канала (`desk_state` + отпечатки), картинки (кадр, вырезка, GIF), черновик
// отметок целиком по `base` (чужое изменение — `check_changed`, лишний id — `unknown_id`) и
// «применить» в два шага: план с одноразовым токеном и «да» (`confirm_*`, `check_changed`,
// `busy`), фоновые задачи банка — вырезка фона и обрезка полей (./memeJobs.ts, CC-0075). Общий
// для Vitest (MSW), Playwright и тренировки. Данные — ./memesData.ts.
import type { components } from '../api/schema.gen';
import { candidatesReply } from './memeCandidates';
import { createMemeJobs } from './memeJobs';
import {
  CHANNEL_BANKS,
  DEFAULT_BANK,
  seedBanks,
  type BankSeed,
  type DraftMark,
  type IndexEntry,
} from './memesData';

type S = components['schemas'];
type Code = S['MemesProblem']['code'];

/** Файлы-заглушки картинок (tests/e2e/assets): их отдаёт фикстура e2e и демо тренировки. */
export type MemeFile =
  | 'meme-1.jpg'
  | 'meme-2.jpg'
  | 'meme-3.jpg'
  | 'meme-4.jpg'
  | 'meme.gif'
  | 'cut.png'
  | 'contact-sheet.jpg';

export type MemeReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: S['MemesProblem'] }
  | { status: 200; file: MemeFile; type: 'image/jpeg' | 'image/gif' | 'image/png' };

const TTL_S = 120;

const problem = (
  status: 404 | 409 | 422 | 500,
  code: Code,
  message: string,
  details: string[] = [],
): MemeReply => ({ status, body: { code, message, details } });

/** Отпечаток (как sha256 у фабрики — здесь короткий хеш строки, этого хватает). */
function hash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, '0').repeat(8);
}

const clone = <T>(x: T): T => structuredClone(x);
const isGif = (e: IndexEntry) => e.file.toLowerCase().endsWith('.gif');
const MARK_KEYS = ['v', 'cut', 'note'] as const;
const MARK_META = ['marked_by', 'marked_at', 'via'] as const;

function stillOf(e: IndexEntry): MemeFile {
  if (e.id === 'grus-plan' || e.id === 'two-buttons') return 'meme-4.jpg';
  const n = [...e.id].reduce((a, c) => a + c.charCodeAt(0), 0) % 3;
  return (['meme-1.jpg', 'meme-2.jpg', 'meme-3.jpg'] as const)[n]!;
}

export function createMemesBackend() {
  const banks: Record<string, BankSeed> = seedBanks();
  const tokens = new Map<string, { channel: string; drop: boolean; fp: string; expires: number }>();
  let seq = 0;
  let next: { code: Code; message?: string } | null = null;

  const bankOf = (channel: string) => CHANNEL_BANKS.find((c) => c.channel === channel) ?? null;
  const draftFp = (b: BankSeed) => (b.draft ? hash(JSON.stringify(b.draft)) : null);
  const indexFp = (b: BankSeed) => hash(JSON.stringify(b.entries));
  /** Фоновые задачи банка (CC-0075): вырезка фона, обрезка полей — ./memeJobs.ts. */
  const jobs = createMemeJobs({ banks, bankOf, hash });

  function cutOf(e: IndexEntry) {
    const a = e.cutout_asset;
    const none = { cut_file: null, cut_refused: null, cut_refused_en: null };
    if (!e.cutout || !a) return none;
    if (typeof a.file === 'string') return { ...none, cut_file: a.file };
    return {
      cut_file: null,
      cut_refused:
        typeof a.refused === 'string' ? a.refused : 'вырезки нет\u00a0— её нужно сделать заново',
      cut_refused_en:
        typeof a.refused_en === 'string' ? a.refused_en : 'file missing - run meme_desk.py cutout',
    };
  }

  function status(b: BankSeed): S['MemeDeskStatus'] {
    const dec = b.draft ?? {};
    const ids = new Set(b.entries.map((e) => e.id));
    const by = new Map(b.entries.map((e) => [e.id, e]));
    const marks = Object.entries(dec);
    return {
      pending: b.entries.filter((e) => e.review === 'pending').map((e) => e.id),
      keep: marks
        .filter(([i, d]) => d.v === 'keep' && ids.has(i))
        .map(([i]) => i)
        .sort(),
      drop: marks
        .filter(([i, d]) => d.v === 'drop' && ids.has(i))
        .map(([i]) => i)
        .sort(),
      cut_diff: marks
        .filter(([i, d]) => 'cut' in d && ids.has(i) && !!d.cut !== !!by.get(i)!.cutout)
        .map(([i]) => i)
        .sort(),
      notes: Object.fromEntries(
        marks.filter(([i, d]) => (d.note ?? '').trim() && ids.has(i)).map(([i, d]) => [i, d.note!]),
      ),
      stale: marks
        .map(([i]) => i)
        .filter((i) => !ids.has(i))
        .sort(),
      blank_bands: b.bands.filter((x) => ids.has(x.id)),
      blank_band_errors: [],
      blank_band_min_share: 0.12,
      blank_bands_checked: true,
    };
  }

  function desk(channel: string): S['MemeDesk'] {
    const row = bankOf(channel)!;
    const b = banks[row.bank]!;
    return {
      bank: row.bank,
      default_bank: row.bank === DEFAULT_BANK,
      channel,
      folder: b.folder,
      entries: b.entries.map((e) => {
        const base = `/api/memes/${channel}/${e.id}`;
        const c = cutOf(e);
        return {
          id: e.id,
          file: e.file,
          gif: isGif(e),
          description: e.description,
          tags: e.tags,
          source_url: e.source_url ?? null,
          notes: e.notes ?? null,
          review: e.review ?? null,
          cutout: !!e.cutout,
          cutout_asset: e.cutout_asset ?? null,
          ...c,
          clip: e.clip ?? null,
          urls: {
            file: `${base}/media?kind=file`,
            cut: c.cut_file ? `${base}/media?kind=cut` : null,
            thumb: `${base}/thumb`,
          },
        };
      }),
      decisions: clone(b.draft ?? {}),
      status: status(b),
      fingerprint: draftFp(b),
      index_fingerprint: indexFp(b),
      job: jobs.deskJob(row.bank),
    };
  }

  function overview(): S['MemesOverview'] {
    return {
      channels: CHANNEL_BANKS.map((c) => {
        const st = status(banks[c.bank]!);
        return {
          channel: c.channel,
          bank: c.bank,
          default_bank: c.bank === DEFAULT_BANK,
          layer_enabled: c.layer_enabled,
          entries: banks[c.bank]!.entries.length,
          pending: st.pending.length,
          keep: st.keep.length,
          drop: st.drop.length,
          cut_diff: st.cut_diff.length,
          stale: st.stale.length,
          error: null,
        };
      }),
    };
  }

  function save(channel: string, body: unknown): MemeReply {
    const busy = jobs.activeRefusal(channel);
    if (busy) return busy;
    const b = banks[bankOf(channel)!.bank]!;
    const { decisions, base } = (body ?? {}) as { decisions?: unknown; base?: unknown };
    if (base !== draftFp(b))
      return problem(
        409,
        'check_changed',
        'Отметки изменились с тех пор, как вы открыли стол (другая вкладка или стол в терминале) - отметки не сохранены; откройте стол заново.',
        [`decisions.json is ${draftFp(b)}, the request's base is ${String(base)}`],
      );
    if (typeof decisions !== 'object' || decisions === null || Array.isArray(decisions))
      return problem(422, 'bad_decisions', 'отметки - объект {id мема: отметка}');
    const ids = new Set(b.entries.map((e) => e.id));
    const out: Record<string, DraftMark> = {};
    const now = new Date().toISOString().replace(/\.\d+Z$/, '+00:00');
    for (const [i, raw] of Object.entries(decisions as Record<string, unknown>)) {
      if (!ids.has(i)) return problem(422, 'unknown_id', `мема '${i}' нет в банке`);
      const d = raw as DraftMark;
      if (typeof d !== 'object' || d === null)
        return problem(422, 'bad_decisions', `${i}: отметка - объект {v, cut, note}`);
      if ('v' in d && d.v !== 'keep' && d.v !== 'drop')
        return problem(422, 'bad_decisions', `${i}: v - keep или drop, а не '${String(d.v)}'`);
      const core: DraftMark = {};
      for (const k of MARK_KEYS) if (k in d) Object.assign(core, { [k]: d[k] });
      const prev = b.draft?.[i] ?? {};
      const prevCore: DraftMark = {};
      for (const k of MARK_KEYS) if (k in prev) Object.assign(prevCore, { [k]: prev[k] });
      if (JSON.stringify(core) === JSON.stringify(prevCore)) {
        const meta: DraftMark = {};
        for (const k of MARK_META) if (k in prev) Object.assign(meta, { [k]: prev[k] });
        out[i] = { ...core, ...meta };
      } else out[i] = { ...core, marked_by: 'user', marked_at: now, via: 'center' };
    }
    b.draft = out;
    return {
      status: 200,
      body: {
        channel,
        saved: Object.keys(out).length,
        bank: bankOf(channel)!.bank,
        fingerprint: draftFp(b),
      } satisfies S['MemeMarksResult'],
    };
  }

  /** `_plan` фабрики: что сделает «применить», ничего не записывая. */
  function compute(channel: string, drop: boolean) {
    const b = banks[bankOf(channel)!.bank]!;
    const dec = b.draft ?? {};
    const accept: string[] = [];
    const remove: string[] = [];
    const refused: S['MemeRefused'][] = [];
    const changed: string[] = [];
    const files: string[] = [];
    const out: IndexEntry[] = [];
    for (const e0 of b.entries) {
      const e = clone(e0);
      const d = dec[e.id] ?? {};
      const pending = e.review === 'pending';
      if (d.v === 'drop' && (pending || drop)) {
        const intent = b.leaders[e.id];
        if (intent) {
          refused.push({ id: e.id, intent });
          out.push(e);
          continue;
        }
        remove.push(e.id);
        files.push(e.file);
        if (typeof e.cutout_asset?.file === 'string') files.push(e.cutout_asset.file);
        continue;
      }
      if (pending && d.v === 'keep') {
        delete e.review;
        accept.push(e.id);
      }
      if ('cut' in d) {
        const want = !!d.cut && !isGif(e);
        if (!!e.cutout !== want || !('cutout' in e)) {
          e.cutout = want;
          changed.push(e.id);
        }
        if (!want && e.cutout_asset) {
          if (typeof e.cutout_asset.file === 'string') files.push(e.cutout_asset.file);
          delete e.cutout_asset;
        }
      }
      out.push(e);
    }
    const kept = new Set(out.map((e) => e.id));
    const held = Object.entries(dec)
      .filter(
        ([i, d]) =>
          d.v === 'drop' &&
          kept.has(i) &&
          out.find((e) => e.id === i)!.review !== 'pending' &&
          !drop &&
          !b.leaders[i],
      )
      .map(([i]) => i)
      .sort();
    const plan = {
      action: 'meme_apply' as const,
      channel,
      bank: bankOf(channel)!.bank,
      default_bank: bankOf(channel)!.bank === DEFAULT_BANK,
      drop,
      accept,
      cutout_changed: changed,
      remove,
      refused,
      held,
      errors: [] as string[],
      files_to_delete: files.map((f) => f),
      decisions_fingerprint: draftFp(b),
      index_fingerprint: indexFp(b),
    };
    const fp = hash(JSON.stringify(plan));
    return { plan, fp, out, removed: remove };
  }

  function plan(channel: string, body: unknown): MemeReply {
    const drop = !!(body as { drop?: unknown } | null)?.drop;
    const { plan: p, fp } = compute(channel, drop);
    const g = jobs.guard(channel);
    const ok = p.errors.length === 0 && !g;
    let confirm: string | null = null;
    if (ok) {
      confirm = `meme-${++seq}`;
      tokens.set(confirm, { channel, drop, fp, expires: Date.now() + TTL_S * 1000 });
    }
    const body200: S['MemeApplyPlan'] = {
      ...p,
      ok,
      why: g
        ? g.why
        : ok
          ? null
          : `Применить нельзя - index.json вышел бы неверным: ${p.errors.join('; ')}`,
      job: g?.job ?? null,
      machine_job: g?.machine_job ?? null,
      fingerprint: fp,
      confirm,
      expires_in_s: ok ? TTL_S : null,
    };
    return { status: 200, body: body200 };
  }

  function apply(channel: string, body: unknown): MemeReply {
    const busy = jobs.activeRefusal(channel);
    if (busy) return busy;
    const token = (body as { confirm?: unknown } | null)?.confirm;
    if (next) {
      const n = next;
      next = null;
      if (n.code === 'busy')
        return problem(
          409,
          'busy',
          n.message ?? 'Идёт другая запись мемов - подождите и повторите.',
        );
      return problem(409, n.code, n.message ?? 'Фабрика отказала.');
    }
    const t = typeof token === 'string' ? tokens.get(token) : undefined;
    if (!t || t.channel !== channel)
      return problem(409, 'confirm_unknown', 'Подтверждение не найдено - посмотрите план заново.');
    tokens.delete(token as string);
    if (t.expires <= Date.now())
      return problem(409, 'confirm_expired', 'Подтверждение устарело - посмотрите план заново.');
    const { plan: p, fp, out, removed } = compute(channel, t.drop);
    if (fp !== t.fp)
      return problem(
        409,
        'check_changed',
        'Банк или отметки изменились с момента плана - отметки не применены; посмотрите план заново.',
        ["the fingerprint of index.json + decisions.json + the plan differs from the plan's"],
      );
    const b = banks[bankOf(channel)!.bank]!;
    b.entries = out;
    if (b.draft) for (const i of removed) delete b.draft[i];
    return {
      status: 200,
      body: {
        ...p,
        decisions_fingerprint: draftFp(b),
        index_fingerprint: indexFp(b),
        written: true,
      } satisfies S['MemeApplyResult'],
    };
  }

  function media(channel: string, id: string, kind: string, thumb: boolean): MemeReply {
    const b = banks[bankOf(channel)!.bank]!;
    const e = b.entries.find((x) => x.id === id);
    if (!e) return problem(404, 'unknown_id', `мема '${id}' нет в банке`);
    if (isGif(e)) return { status: 200, file: 'meme.gif', type: 'image/gif' };
    if (!thumb && kind === 'cut') {
      if (!cutOf(e).cut_file) return problem(404, 'no_cut', `у мема '${id}' нет вырезки`);
      return { status: 200, file: 'cut.png', type: 'image/png' };
    }
    return { status: 200, file: stillOf(e), type: 'image/jpeg' };
  }

  // ---- приём кандидатов в банк (CC-0115 шаг 3 → CC-0114 API)
  /**
   * Переключатели теста: `refuse` — код отказа «да» (`busy` — токен цел), `listChanged` — список
   * кандидатов сдвинулся с плана (`list_changed`, план заново), `life` — срок токена.
   */
  const accept = {
    accepted: [] as string[],
    plans: [] as unknown[],
    answers: [] as string[],
    refuse: null as Code | null,
    listChanged: false,
    life: 120,
    tokens: new Map<
      string,
      { channel: string; ids: string[]; details: unknown; expires: number }
    >(),
    seq: 0,
  };

  function acceptPlan(channel: string, raw: unknown): MemeReply {
    accept.plans.push(raw);
    const b = (raw ?? {}) as { ids?: string[] | null; details?: unknown };
    if (Array.isArray(b.ids) && !b.ids.length)
      return problem(
        422,
        'bad_ids',
        'Выберите хотя бы одного кандидата (или не указывайте ids - тогда все готовые).',
      );
    const c = candidatesReply(channel, bankOf(channel)!.bank !== DEFAULT_BANK, accept.accepted);
    if (!c.candidates.length)
      return problem(409, 'no_candidates', 'У банка нет списка кандидатов (candidates.json).');
    const ids = b.ids ?? c.accept.ready;
    const want = new Set(ids);
    const take = c.accept.ready.filter((id) => want.has(id));
    const refused = ids
      .filter((id) => !take.includes(id))
      .map((id) => {
        const st = c.candidates.find((x) => x.id === id)?.status;
        return {
          id,
          reason: (st === 'in_bank' ? 'in_bank' : 'not_downloaded') as 'in_bank',
          text: st === 'in_bank' ? 'уже в банке' : 'не скачан',
        };
      });
    const ok = take.length > 0;
    let confirm: string | null = null;
    if (ok) {
      confirm = `meme-accept-${++accept.seq}`;
      accept.tokens.set(confirm, {
        channel,
        ids: take,
        details: b.details ?? null,
        expires: Date.now() + accept.life * 1000,
      });
    }
    const body: S['MemeAcceptPlan'] = {
      action: 'meme_candidates_accept',
      channel,
      bank: c.bank,
      ids,
      accept: take,
      refused,
      fingerprint: 'sha256:0123456789abcdef',
      answer: {
        must_contain: 'да',
        must_not_contain: ['нет'],
        prompt: ok ? `Принять в банк ${take.length} шаблон(а)? Ответьте «да».` : null,
      },
      review: 'pending',
      downloads: 0,
      by: 'user',
      via: 'center',
      dry_run: true,
      details: (b.details as S['MemeAcceptPlan']['details']) ?? null,
      ok,
      why: ok ? null : 'Принять некого: готовых кандидатов нет',
      plan_fingerprint: `fp-accept-${accept.seq}`,
      confirm,
      expires_in_s: confirm ? accept.life : null,
    };
    return { status: 200, body };
  }

  function acceptAct(channel: string, raw: unknown): MemeReply {
    const b = (raw ?? {}) as { confirm?: string; answer?: string };
    if (accept.refuse === 'busy')
      return problem(409, 'busy', 'Идёт другая запись банка - подождите и нажмите ещё раз.', [
        'the token is not spent',
      ]);
    const answer = b.answer ?? '';
    if (!/да/i.test(answer) || /нет/i.test(answer))
      return problem(422, 'bad_answer', 'Кандидаты не приняты: ответ не «да».', [
        'check_accept_answer: not a yes',
        'the token is not spent',
      ]);
    const got = accept.tokens.get(b.confirm ?? '');
    accept.tokens.delete(b.confirm ?? '');
    if (!got || got.channel !== channel)
      return problem(409, 'confirm_unknown', 'Подтверждение не найдено - запросите план заново.');
    if (got.expires <= Date.now())
      return problem(409, 'confirm_expired', 'Подтверждение устарело - запросите план заново.');
    if (accept.listChanged)
      return problem(
        409,
        'list_changed',
        'Список кандидатов изменился с плана - ничего не записано, посмотрите план заново.',
        ['accept_candidates: fingerprint differs'],
      );
    if (accept.refuse)
      return problem(409, accept.refuse, 'Стол мемов отказал в приёме кандидатов.', [
        `accept_candidates: ${accept.refuse}`,
      ]);
    accept.accepted.push(...got.ids);
    accept.answers.push(answer);
    const details = (got.details ?? {}) as Record<string, Record<string, unknown>>;
    const body: S['MemeAcceptResult'] = {
      action: 'meme_candidates_accept',
      channel,
      bank: `shared/inserts/memes-${channel}/`,
      accepted: got.ids,
      refused: [],
      unchanged: false,
      entries: got.ids.map((id) => ({ id, review: 'pending', ...(details[id] ?? {}) })),
      fingerprint: 'sha256:0123456789abcdef',
      by: 'user',
      via: 'center',
      dry_run: false,
      embedding: { done: true, line: 'embedded 2', error: null },
      answer,
    };
    return { status: 200, body };
  }

  return {
    banks,
    overview,
    desk,
    save,
    plan,
    apply,
    media,
    channelOk: (channel: string) => !!bankOf(channel),
    /** Кандидаты в банк (CC-0115): свой банк — список, банк по умолчанию — списка нет. */
    candidates: (channel: string) =>
      candidatesReply(channel, bankOf(channel)!.bank !== DEFAULT_BANK, accept.accepted),
    accept,
    acceptPlan,
    acceptAct,
    jobs,
    /** Черновик поменяли мимо этой страницы (другая вкладка, стол в терминале). */
    editElsewhere(bank: string, id: string, mark: DraftMark) {
      const b = banks[bank]!;
      b.draft = { ...(b.draft ?? {}), [id]: mark };
    },
    /** Все выданные подтверждения устарели («промотать время»). */
    expireTokens() {
      for (const t of tokens.values()) t.expires = 0;
      jobs.expireTokens();
    },
    /** Следующее «да» получит отказ `code` (`busy` — подтверждение цело). */
    failNext(code: Code, message?: string) {
      next = { code, message };
    },
  };
}

export type MemesBackend = ReturnType<typeof createMemesBackend>;

/** Маршрутизатор `/api/memes…`; `null` — путь не мемов. */
export function routeMemes(
  backend: MemesBackend,
  method: string,
  url: URL,
  body: unknown,
): MemeReply | null {
  const m = /\/api\/memes(?:\/([^/]+))?(?:\/(.+))?$/.exec(url.pathname);
  if (!m) return null;
  const channel = m[1] ? decodeURIComponent(m[1]) : null;
  const rest = m[2] ?? '';
  const read = method === 'GET' || method === 'HEAD';
  if (!channel) return read ? { status: 200, body: backend.overview() } : null;
  if (!backend.channelOk(channel))
    return problem(404, 'unknown_channel', `канала '${channel}' нет на фабрике`);
  if (!rest && read) return { status: 200, body: backend.desk(channel) };
  if (rest === 'candidates' && read) return { status: 200, body: backend.candidates(channel) };
  if (rest === 'candidates/accept/plan' && method === 'POST')
    return backend.acceptPlan(channel, body);
  if (rest === 'candidates/accept' && method === 'POST') return backend.acceptAct(channel, body);
  if (rest === 'marks' && method === 'PUT') return backend.save(channel, body);
  if (rest === 'apply/plan' && method === 'POST') return backend.plan(channel, body);
  if (rest === 'apply' && method === 'POST') return backend.apply(channel, body);
  if (rest === 'cutout/plan' && method === 'POST') return backend.jobs.cutoutPlan(channel, body);
  if (rest === 'cutout' && method === 'POST') return backend.jobs.start(channel, 'cutout', body);
  if (rest === 'trim/plan' && method === 'POST') return backend.jobs.trimPlan(channel, body);
  if (rest === 'trim' && method === 'POST') return backend.jobs.start(channel, 'trim_blank', body);
  // CC-0133: добавить картинку и GIF, лист кадров, признаки для поиска похожих
  const add = /^(add-image|add-gif|sheet|embed)(\/plan)?$/.exec(rest);
  if (add && method === 'POST') {
    const kind = (
      { 'add-image': 'add_image', 'add-gif': 'add_gif', sheet: 'sheet', embed: 'embed' } as const
    )[add[1] as 'add-image' | 'add-gif' | 'sheet' | 'embed'];
    return add[2]
      ? backend.jobs.addPlan(channel, kind, body)
      : backend.jobs.start(channel, kind, body);
  }
  const sheet = /^sheets\/([^/]+)$/.exec(rest);
  if (sheet && read) {
    const name = decodeURIComponent(sheet[1]!);
    if (!/\.(jpe?g|png)$/i.test(name))
      return problem(
        404,
        'outside_bank',
        'Лист кадров отдаётся только из <банк>/_desk/sheets/ и только .jpg/.jpeg/.png.',
      );
    if (!backend.jobs.hasSheet(name)) return problem(404, 'no_file', `Листа ${name} нет в банке.`);
    return { status: 200, file: 'contact-sheet.jpg', type: 'image/jpeg' };
  }
  if (rest === 'jobs' && read)
    return backend.jobs.list(channel, Number(url.searchParams.get('limit') ?? 20) || 20);
  const job = /^jobs\/([^/]+)$/.exec(rest);
  if (job && read) return backend.jobs.one(channel, decodeURIComponent(job[1]!));
  const media = /^([^/]+)\/(media|thumb)$/.exec(rest);
  if (media && read)
    return backend.media(
      channel,
      decodeURIComponent(media[1]!),
      url.searchParams.get('kind') ?? 'file',
      media[2] === 'thumb',
    );
  return null;
}
