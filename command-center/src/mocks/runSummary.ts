// Подставная сводка прогона (CC-0115 → CC-0099, `GET …/summary`): разделы `runlog summary
// --json` в том виде, в каком их отдаёт фабрика (сокращённо: только то, что читает центр, и
// немного соседнего), и RUN_SUMMARY.md. Виды: `full` — закрытый прогон с простоем, красными
// проверками и сдвигом кода; `clean` — прогон без замечаний; `none` — событий ещё нет;
// `broken` — посчитать не вышло, файл есть. Общий для Vitest, Playwright и тренировки.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export type SummaryKind = 'full' | 'clean' | 'none' | 'broken';

/** Строки фабрики для кодов воронки (`funnel.reason_ru`, CC-0113): у ответа — `funnel_reasons_ru`. */
const FUNNEL_RU: Record<string, string | null> = {
  no_fact: 'за темой не нашлось факта, проходящего правило фактов',
  no_support_text: 'о событии темы нет опорного текста (статьи или описания эпизода)',
  judge_footage_defect: 'судья кадров нашёл брак футажа из жёсткого списка',
};

const step = (step: string, label: string, count: number, lost: string[] = []) => ({
  step,
  label,
  count,
  items: [],
  lost: lost.map((reason_code, i) => ({
    item: `t-${step}-${i}`,
    reason_code,
    reason_ru: FUNNEL_RU[reason_code] ?? null,
    reason: reason_code,
  })),
  carried_on: [],
  reserve: [],
  held: [],
  kept_on_own_graphics: [],
  basis: null,
});

const FILE_TEXT = `GAPS: 1 (unknown 1 = 1h13m40s) - total 1h13m40s of 5h26m04s wall (22.6 %)

FUNNEL: before selection 7 -> selected 5 -> after compliance 5 -> with 2 sources 5 -> scripts 5 -> ready 5 -> frame judge 4 - 1 of 5 topics lost (20 %)

WAITS: none (no stage waited for a human longer than 10 min)

OPERATOR: 25m07s of 5h26m04s wall (7.7 %) the stage operators spent between their scripts

# RUN_SUMMARY example-film/2026-10-09T0215Z

wall 5h26m04s · live 4h12m24s (wall minus gaps 1h13m40s) · busy 3h46m22s · operator 25m07s
`;

function data(kind: 'full' | 'clean', batch: string): Record<string, unknown> {
  const clean = kind === 'clean';
  const wall = clean ? 8619.6 : 19563.8;
  const gaps = clean ? 0 : 4419.8;
  return {
    batch,
    header: { batch, markup: 2 },
    times: {
      wall: { start: '2026-10-09T02:15:00Z', end: '2026-10-09T07:41:04Z', seconds: wall },
      gaps_s: gaps,
      live_s: wall - gaps,
      busy_s: (wall - gaps) * 0.9,
      waits_s: clean ? 0 : 1260,
      operator_s: 1507.1,
      idle_s: 0,
      stages: [],
      videos: [],
    },
    gaps: {
      count: clean ? 0 : 1,
      seconds: gaps,
      by_cause: {
        limit: { count: 0, seconds: 0 },
        unknown: { count: clean ? 0 : 1, seconds: gaps },
      },
      gaps: [],
    },
    gaps_line: clean
      ? 'GAPS: none'
      : 'GAPS: 1 (unknown 1 = 1h13m40s) - total 1h13m40s of 5h26m04s wall (22.6 %)',
    waits: clean
      ? { count: 0, seconds: 0, outside_gaps_s: 0, by_stage: {}, waits: [] }
      : { count: 1, seconds: 1260, outside_gaps_s: 1260, by_stage: {}, waits: [] },
    waits_line: clean
      ? 'WAITS: none (no stage waited for a human longer than 10 min)'
      : 'WAITS: 1 (21m00s) - compliance-checker waited for a human',
    operator: { seconds: 1507.1, idle_s: 0, count: 0, by_stage: {} },
    operator_line:
      'OPERATOR: 25m07s of 5h26m04s wall (7.7 %) the stage operators spent between their scripts',
    consistency: { ok: true, checks: [], violations: [], notes: [] },
    funnel: {
      available: true,
      missing: [],
      errors: [],
      steps: clean
        ? [
            step('before_selection', 'before selection', 4),
            step('selected', 'selected', 3),
            step('after_compliance', 'after compliance', 3),
            step('two_sources', 'with 2 sources', 3),
            step('scripts', 'scripts', 3),
            step('ready', 'ready', 3),
            step('frame_judge', 'frame judge', 3),
          ]
        : [
            step('before_selection', 'before selection', 7, [
              'no_fact',
              'no_support_text',
              'no_fact',
            ]),
            step('selected', 'selected', 5),
            step('after_compliance', 'after compliance', 5),
            step('two_sources', 'with 2 sources', 5),
            step('scripts', 'scripts', 5),
            step('ready', 'ready', 5),
            step('frame_judge', 'frame judge', 4, ['judge_footage_defect']),
          ],
      losses: clean ? {} : { no_fact: 2, judge_footage_defect: 1, no_support_text: 1 },
    },
    scores: (clean
      ? [
          ['delver', 'S', 97],
          ['plankton', 'A', 88],
          ['comet', 'C', 74],
        ]
      : [
          ['vanguards-doomsday', 'E', 56],
          ['other-mommy', 'C', 74.26],
          ['weekend-night-live', 'S', 97],
          ['the-social-reckoning', 'D', 67.1],
          ['blade-runner-2099', 'F', 67],
        ]
    ).map(([slug, tier, score]) => ({
      script_id: `${slug}-script1`,
      slug,
      score,
      tier,
      threshold: 40,
      state: tier === 'F' ? 'refused' : 'ready',
    })),
    stopcock: { state: 'open', scripts: clean ? 3 : 5 },
    no_waiting: { verdict: clean ? 'clean' : 'incident', gaps_count: clean ? 0 : 1, gaps_s: gaps },
    watchdog: [],
    code_drift: clean
      ? []
      : [
          {
            ts: '2026-10-09T03:52:49Z',
            marker: 'stage-start',
            stage: 'footage-indexer',
            repo: 'root',
          },
        ],
    monitors: clean
      ? { task: 'CF-0511', state: 'green', green: 28, red: 0, not_checked: 0, files: [] }
      : { task: 'CF-0511', state: 'red', green: 23, red: 5, not_checked: 0, files: [] },
    quota_line: 'YouTube quota: 66 of 100 search call(s) (6600 units)',
    counts: { events: 64649, samples: 2236, limits: 0, usage_rows: 133 },
  };
}

/** Ответ `GET …/summary` подставного батча. */
export function summaryReply(batch: string, kind: SummaryKind): S['BatchRunSummary'] {
  const [channel, batch_id] = batch.split('/') as [string, string];
  const file =
    kind === 'none'
      ? null
      : {
          name: 'RUN_SUMMARY.md',
          size: FILE_TEXT.length,
          modified: '2026-10-09T07:41:30Z',
          text: FILE_TEXT,
        };
  return {
    batch,
    channel,
    batch_id,
    file,
    file_note: file ? null : 'RUN_SUMMARY.md ещё нет: его пишет batch-done, когда батч закрыт.',
    data: kind === 'full' || kind === 'clean' ? data(kind, batch) : null,
    data_note:
      kind === 'none'
        ? 'Событий прогона (RUN_EVENTS.jsonl) ещё нет - сводке не из чего считаться.'
        : null,
    data_error: kind === 'broken' ? "KeyError: 'stage' (shared/runlog/summary.py, line 412)" : null,
    computed_at: kind === 'none' ? null : '2026-10-09T07:42:00Z',
    funnel_reasons_ru: kind === 'full' ? FUNNEL_RU : {},
    cached: kind !== 'none',
    poll_s: 60,
  };
}
