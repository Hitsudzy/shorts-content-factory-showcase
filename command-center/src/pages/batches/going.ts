// Идущий батч и прогоны словами для человека (CC-0051): стадии фабрики → кадры киноленты
// в порядке плана прогона (CC-0090), статус исполнителя, оценка конца, кто запустил, итог
// прогона. Общие для экрана «Батчи» и блока главной.
import type { GoingBatch, Launch, StageSpan } from '@/api/batches';
import type { BatchEvent } from '@/api/eventsFeed';
import type { Tone } from '@/components/common/Status';

import { dateTimeMsk, FACTORY_TZ, plural, runsWord, videosWord } from './format';
import {
  isJudgeRound,
  JUDGE_EMPTY,
  JUDGE_ROUND_FRAME,
  KINDS,
  kindOf,
  repeatOf,
  USUAL,
  type FrameKind,
} from './stages';

export { isConditional, KINDS, kindOf, stageTitle, type FrameKind } from './stages';

const DONE = /^(done|skipped|ok|passed|not[-_]needed|noop)$/;
const BAD = /^(failed|halted|error|timeout|crashed)$/;
const PAUSED = /^(stopped|paused)$/;
/** Стадия не запускалась (ждёт, пропущена или батч до неё не дошёл). */
const IDLE_STATUS = /^(pending|waiting|skipped|unreached|not[-_]needed|noop|)$/;
/**
 * Своя пометка центра (CC-0095): `skipped` после упавшей или остановленной стадии — батч до
 * неё не дошёл, а не «пропустил за ненадобностью». Фабрика пишет таким `skipped` с причиной
 * «after failed stage …», но причины в ответе списка нет — решаем по порядку плана.
 */
const UNREACHED = 'unreached';

/**
 * Состояние кадра. `opt` — условный кадр, до которого батч не дошёл («только если нужно»);
 * `unneeded` — батч прошёл его, ни разу не запустив («не понадобился»); `unreached` — батч
 * упал или остановлен раньше, и фабрика пометила стадии кадра пропущенными («не дошёл»).
 */
export type FrameState =
  'done' | 'now' | 'wait' | 'part' | 'skip' | 'bad' | 'stopped' | 'opt' | 'unneeded' | 'unreached';

export type Frame = {
  n: number;
  kind: FrameKind;
  title: string;
  tip: string;
  state: FrameState;
  done: number;
  total: number;
  /** Стадии фабрики кадра — в порядке плана. */
  stages: string[];
  /** Кадр стадии, на которой батч сейчас (идёт, остановлен, упал). */
  current: boolean;
  /**
   * Готовый кадр, где остальные шаги — запасные (`*-reserve`, повторы `*-late`/`*-judge`, CC-0126): сколько их не
   * понадобилось («2 запасных шага не понадобились»).
   */
  spare?: number;
  /** Готовый кадр, у которого запасные шаги ещё могут пойти: «готово, возможен добор». */
  more?: boolean;
  /**
   * Проверке кадров нечего было проверять (CF-0707): `frame-judge-empty` готова, а сама
   * `frame-judge` пропущена — один готовый кадр «нечего проверять», не два и не пропуск.
   */
  empty?: boolean;
  /**
   * Батч вернулся в кадр (CC-0126): кадр идёт, а дальше по плану что-то уже запускалось, — или
   * это сам «Добор». Подпись — «добор · идёт N мин».
   */
  returned?: boolean;
  /**
   * Кадр — раунд добора после отказа судьи кадра (стадии `*-judge`, фабрика 2.16, CC-0150): свой
   * заголовок «Добор после судьи», а не второй «Добор».
   */
  judge?: boolean;
};

/**
 * Запасной шаг: резерв (`*-reserve`) или повтор (`*-late`, `*-judge` — после отказа судьи кадра) —
 * нужен, только если не хватило.
 */
export const isSpare = (id: string) => /-reserve$/.test(id) || repeatOf(id) !== null;
/** Стадия ещё не начиналась (может пойти). */
const NOT_STARTED = /^(pending|waiting|)$/;

type Source = Pick<GoingBatch, 'stages' | 'stage' | 'status'>;
type Group = { kind: FrameKind; members: { id: string; status: string }[] };

/**
 * Стадии плана → кадры по порядку плана: соседние стадии одного вида — один кадр, условные
 * стадии подряд — один кадр «Добор» на своём месте. После batch-done всё — «На приёмку».
 * Кадр, которого в плане нет (пересборка от монтажа), встаёт пустым на обычное место.
 */
function groupsOf(stages: NonNullable<Source['stages']>): Group[] {
  const groups: Group[] = [];
  let main: FrameKind = 'trends';
  let closed = false;
  for (const s of stages) {
    const id = s.id ?? '';
    const last = groups[groups.length - 1];
    const prev: FrameKind = last && last.kind !== 'extra' ? last.kind : main;
    const kind: FrameKind = closed ? 'accept' : kindOf(id, prev);
    if (/^batch-done/.test(id)) closed = true;
    if (kind !== 'extra') main = kind;
    const member = { id, status: s.status ?? 'pending' };
    if (last && last.kind === kind) last.members.push(member);
    else groups.push({ kind, members: [member] });
  }
  const rank = (k: FrameKind) => USUAL.indexOf(k);
  for (const k of USUAL) {
    if (k === 'extra' || groups.some((g) => g.kind === k)) continue;
    let at = 0;
    groups.forEach((g, i) => {
      if (rank(g.kind) < rank(k)) at = i + 1;
    });
    groups.splice(at, 0, { kind: k, members: [] });
  }
  return groups;
}

/**
 * План с пометкой «не дошёл»: `skipped` после первой стадии `failed`/`stopped` (по порядку
 * плана) — `unreached`. Стадии до неё, условные в том числе, остаются как есть: условная
 * `skipped` до места падения — «не понадобилась».
 */
export function markUnreached(
  stages: NonNullable<Source['stages']>,
): NonNullable<Source['stages']> {
  const halt = stages.findIndex((s) => BAD.test(s.status ?? '') || PAUSED.test(s.status ?? ''));
  if (halt < 0) return stages;
  return stages.map((s, i) =>
    i > halt && s.status === 'skipped' ? { ...s, status: UNREACHED } : s,
  );
}

/**
 * Кадры киноленты батча. С планом прогона (`stages` из run-state, порядок запуска) — по его
 * стадиям и в его порядке: номера идут подряд, как фабрика их запускает. Кадр готов, когда
 * готовы все его стадии; текущий — где идёт `stage`. Без плана (батч только по маркерам) —
 * обычный порядок, кадры до текущего готовы, после — ждут.
 */
export function framesOf(b: Source): Frame[] {
  const plan = markUnreached(b.stages ?? []);
  const planned = plan.length > 0;
  const groups: Group[] = planned ? groupsOf(plan) : USUAL.map((kind) => ({ kind, members: [] }));
  let cur = b.stage ? groups.findIndex((g) => g.members.some((m) => m.id === b.stage)) : -1;
  if (cur < 0 && b.stage) {
    const k = kindOf(b.stage);
    cur = groups.findIndex((g) => g.kind === k);
  }
  const status = b.status ?? '';
  const finished = status === 'done';
  /** Дальше кадра `i` батч уже что-то запускал. */
  const passed = (i: number) =>
    finished ||
    (cur >= 0 && i < cur) ||
    groups.slice(i + 1).some((g) => g.members.some((m) => !IDLE_STATUS.test(m.status)));
  return groups.map((g, i) => {
    const m = g.members;
    const done = m.filter((x) => DONE.test(x.status)).length;
    const judge = g.kind === 'extra' && m.length > 0 && m.every((x) => isJudgeRound(x.id));
    const base = {
      n: i + 1,
      kind: g.kind,
      title: judge ? JUDGE_ROUND_FRAME.title : KINDS[g.kind].title,
      tip: judge ? JUDGE_ROUND_FRAME.tip : KINDS[g.kind].tip,
      ...(judge ? { judge: true } : {}),
      done,
      total: m.length,
      stages: m.map((x) => x.id),
      current: i === cur,
    };
    const extra = g.kind === 'extra';
    const ran = m.some((x) => !IDLE_STATUS.test(x.status));
    // Готовое запущенное есть, а всё незаконченное и незапущенное — запасные шаги (CC-0126).
    const spare = m.filter((x) => isSpare(x.id) && IDLE_STATUS.test(x.status));
    const spareOnly =
      m.some((x) => DONE.test(x.status) && !IDLE_STATUS.test(x.status)) &&
      m.every((x) => DONE.test(x.status) || spare.includes(x));
    let state: FrameState;
    let extraFields: Pick<Frame, 'spare' | 'more' | 'returned' | 'empty'> = {};
    if (i === cur && !finished) {
      state = PAUSED.test(status) ? 'stopped' : BAD.test(status) ? 'bad' : 'now';
      const later = groups
        .slice(i + 1)
        .some((x) => x.members.some((y) => !IDLE_STATUS.test(y.status)));
      if (state === 'now' && (extra || later)) extraFields = { returned: true };
    } else if (spareOnly) {
      state = 'done';
      const waiting = spare.filter((x) => NOT_STARTED.test(x.status));
      if (waiting.length && !finished && !passed(i)) extraFields = { more: true };
      else if (spare.length) extraFields = { spare: spare.length };
    } else if (m.some((x) => BAD.test(x.status))) state = 'bad';
    else if (m.length && m.every((x) => x.status === UNREACHED)) state = 'unreached';
    else if (extra && !planned) state = 'opt';
    else if (extra) state = passed(i) ? (ran ? 'done' : 'unneeded') : ran ? 'part' : 'opt';
    else if (finished) state = planned && !m.length ? 'skip' : 'done';
    else if (!planned) state = cur >= 0 && i < cur ? 'done' : 'wait';
    else if (!m.length) state = i < cur ? 'skip' : 'wait';
    else if (done === m.length) state = 'done';
    else if (done > 0) state = 'part';
    else state = 'wait';
    const emptyJudge =
      state === 'done' &&
      m.some((x) => x.id === JUDGE_EMPTY && x.status === 'done') &&
      m.every((x) => x.id === JUDGE_EMPTY || IDLE_STATUS.test(x.status));
    if (emptyJudge)
      return {
        ...base,
        tip: 'Роликов на проверку не было: фабрика записала пустой итог, проверку кадров не запускала',
        state,
        ...extraFields,
        empty: true,
      };
    return { ...base, state, ...extraFields };
  });
}

/** Статус исполнителя батча (`status` run-state) одним словом. */
export function batchStatus(
  status: string | null | undefined,
  fresh = true,
): { label: string; tone: Tone; tip: string } {
  const s = status ?? '';
  if (s === 'running' && !fresh)
    return {
      label: 'давно без событий',
      tone: 'warn',
      tip: 'Батч открыт, но больше суток не пишет событий — похоже, исполнитель не работает',
    };
  switch (s) {
    case 'running':
      return { label: 'идёт', tone: 'live', tip: 'Исполнитель батча работает' };
    case 'stopped':
      return {
        label: 'остановлен',
        tone: 'warn',
        tip: 'Батч остановлен и ждёт «продолжить»: готовое сохранено',
      };
    case 'paused':
      return { label: 'на паузе', tone: 'warn', tip: 'Исполнитель ждёт, прежде чем идти дальше' };
    case 'halted':
      return {
        label: 'встал',
        tone: 'danger',
        tip: 'Исполнитель остановился сам: причина — ниже',
      };
    case 'failed':
      return { label: 'упал', tone: 'danger', tip: 'Стадия завершилась ошибкой' };
    case 'done':
      return { label: 'готов', tone: 'ok', tip: 'Все стадии плана пройдены' };
    case '':
      return {
        label: fresh ? 'идёт' : 'давно без событий',
        tone: fresh ? 'live' : 'warn',
        tip: 'Батч без файла состояния исполнителя: ход виден только по отметкам стадий',
      };
    default:
      return { label: s, tone: 'idle', tip: 'Статус исполнителя батча — как его пишет фабрика' };
  }
}

/**
 * Неразрывный пробел между числом и единицей длительности (CC-0150, ревью экранов): «20 мин»
 * и «1 ч» не рвутся на строки.
 */
const NBSP = '\u00a0';

/** «1 ч 30 мин», «20 мин», «меньше минуты». */
export function spanText(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const min = Math.round(Math.abs(seconds) / 60);
  if (min < 1) return 'меньше минуты';
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `${m}${NBSP}мин`;
  return m ? `${h}${NBSP}ч ${m}${NBSP}мин` : `${h}${NBSP}ч`;
}

/** «2 запасных шага не понадобились». */
export const spareText = (n: number) =>
  `${n} ${plural(n, 'запасной шаг', 'запасных шага', 'запасных шагов')} ${plural(n, 'не понадобился', 'не понадобились', 'не понадобились')}`;

/** «1 ч 05 мин», «25 мин», «меньше минуты» — длительность кадра киноленты (CC-0126). */
export function clockSpan(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const min = Math.round(Math.abs(seconds) / 60);
  if (min < 1) return 'меньше минуты';
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `${m}${NBSP}мин`;
  return m ? `${h}${NBSP}ч ${String(m).padStart(2, '0')}${NBSP}мин` : `${h}${NBSP}ч`;
}

/**
 * Сколько шёл кадр (CC-0126): сумма закончившихся пролётов его стадий (`…/stages`), с; у кадра
 * без плана — пролёты стадий его вида. null — закончившихся пролётов нет.
 */
export function frameSpent(
  f: Pick<Frame, 'stages' | 'kind'>,
  spans: readonly StageSpan[] | null | undefined,
): number | null {
  if (!spans?.length) return null;
  const mine = spans.filter(
    (sp) =>
      !sp.open &&
      sp.duration_s != null &&
      (f.stages.length ? f.stages.includes(sp.stage ?? '') : kindOf(sp.stage) === f.kind),
  );
  return mine.length ? mine.reduce((a, sp) => a + (sp.duration_s ?? 0), 0) : null;
}

/** Оценка конца из `estimate`: «осталось ≈ 1 ч» или «дольше обычного на 20 мин». */
export function etaText(
  e: GoingBatch['estimate'],
): { text: string; over: boolean; tip: string } | null {
  if (!e) return null;
  const tip = `Оценка по ${runsWord(e.runs)}: обычно батч канала идёт ${spanText(e.mean_wall_s)} — не обещание`;
  if (e.left_s < 0) return { text: `дольше обычного на ${spanText(e.left_s)}`, over: true, tip };
  return { text: `осталось ≈ ${spanText(e.left_s)}`, over: false, tip };
}

/** Кто запустил прогон (`launch.by`); `launch` null — запущен руками в чате. */
export function launchedBy(launch: Launch | null | undefined): { label: string; tip: string } {
  const by = launch?.by ?? null;
  if (!launch || !by)
    return {
      label: 'вручную в чате',
      tip: 'В журнале запусков расписания нет строки — батч запустили в чате с оператором',
    };
  if (by === 'tick') return { label: 'таймер', tip: 'Запустило расписание в окне канала' };
  if (by.includes('пульт')) return { label: 'пульт', tip: 'Запущен кнопкой на пульте фабрики' };
  if (by.includes('центр')) return { label: 'центр', tip: 'Запущен из командного центра' };
  return { label: by, tip: 'Кто запустил — как записала фабрика' };
}

/** Итог прогона (`outcome` строки runs.jsonl). */
export function outcomeText(
  outcome: string | null | undefined,
  videos: number | null | undefined,
): { label: string; tone: Tone } {
  if (outcome === 'videos')
    return { label: videos ? `готово: ${videosWord(videos)}` : 'ролики готовы', tone: 'ok' };
  if (outcome === 'no_material') return { label: 'не хватило материала', tone: 'warn' };
  if (!outcome) return { label: 'итог не записан', tone: 'idle' };
  return { label: outcome, tone: 'idle' };
}

/** Время из имени батча «2026-10-08T0200Z» (UTC) → ISO; null — имя не такое. */
export function batchIdIso(id: string | null | undefined): string | null {
  const m = /^(\d{4}-\d\d-\d\d)T(\d\d)(\d\d)Z$/.exec(id ?? '');
  return m ? `${m[1]}T${m[2]}:${m[3]}:00Z` : null;
}

/** Батч в тексте фабрики («example-film 2026-10-09T2305Z», «example-film/2026-…») — каналом и
 * временем по МСК: «ExampleFilm · батч 10.10, 02:05»; текст как есть — под «подробнее». */
const BATCH_IN_TEXT = /\b([a-z][a-z0-9_-]*)[ /](\d{4}-\d{2}-\d{2}T\d{4}Z)\b/g;
export function batchesInText(text: string, name: (id: string) => string): string {
  return text.replace(BATCH_IN_TEXT, (m, ch: string, id: string) => {
    const when = dateTimeMsk(batchIdIso(id));
    return when ? `${name(ch)} · батч ${when}` : m;
  });
}

/** «идёт 20 мин из 90» и доля потолка стадии; null — фабрика не сказала. */
export function stageClock(b: GoingBatch) {
  const el = b.stage_elapsed_s;
  const cap = b.stage_timeout_min;
  if (el == null) return { text: null, progress: null };
  const text = cap ? `${spanText(el)} из ${spanText(cap * 60)}` : spanText(el);
  return { text, progress: cap ? el / (cap * 60) : null };
}

const clock = new Intl.DateTimeFormat('ru-RU', {
  timeZone: FACTORY_TZ,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

function timeOf(ts: unknown): string {
  if (typeof ts !== 'string') return '—';
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? '—' : clock.format(d);
}

const str = (v: unknown) => (typeof v === 'string' && v ? v : null);

/** Строка события словами: «video-editor · delver · edit-3 — ok». */
export function eventLine(e: BatchEvent): { time: string; text: string; marker: boolean } {
  if (!e.event) return { time: '—', text: e.text ?? '', marker: false };
  const ev = e.event;
  const what = [str(ev.stage), str(ev.video), str(ev.step)].filter(Boolean).join(' · ');
  const status = str(ev.status);
  const note = str(ev.note);
  const kind = str(ev.kind) ?? 'событие';
  const text = [what || kind, status ? `— ${status}` : null, note ? `(${note})` : null]
    .filter(Boolean)
    .join(' ');
  return { time: timeOf(ev.ts), text, marker: kind === 'marker' };
}

/** «12 КБ», «1,4 МБ», «300 Б»; перед единицей — неразрывный пробел (CC-0131). */
export function sizeText(n: number): string {
  if (n < 1024) return `${n}\u00a0Б`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)}\u00a0КБ`;
  return `${(n / 1024 / 1024).toFixed(1).replace('.', ',')}\u00a0МБ`;
}
