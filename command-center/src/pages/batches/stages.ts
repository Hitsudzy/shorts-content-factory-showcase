// Стадии фабрики словами (CC-0090): вид кадра киноленты, общая подпись и условные стадии
// (резерв, добор, повторы `*-late` и `*-judge`). Без алиасов `@/` — модуль берут и тесты Playwright
// (tests/e2e, tsconfig.node.json).

/** Вид кадра киноленты: общая подпись группы стадий фабрики. */
export type FrameKind =
  'trends' | 'footage' | 'research' | 'extra' | 'scripts' | 'edit' | 'judge' | 'accept';

/** Подписи кадров (docs/design.md → вариант A, макет «Кинозал»). */
export const KINDS: Record<FrameKind, { title: string; tip: string }> = {
  trends: { title: 'Тренды', tip: 'Подготовка батча и поиск тем: тренды, проверка тем на риски' },
  footage: { title: 'Футаж', tip: 'Подбор и разметка видеоматериала под темы' },
  research: { title: 'Исследование', tip: 'Факты и сценарии роликов по собранному футажу' },
  extra: {
    title: 'Добор',
    tip: 'Резерв футажа и сценариев, добор тонкого пула: фабрика запускает эти шаги, только когда основного не хватило',
  },
  scripts: { title: 'Проверка сценариев', tip: 'Проверка сценариев на риски перед монтажом' },
  edit: { title: 'Монтаж', tip: 'Сборка роликов' },
  judge: { title: 'Проверка кадров', tip: 'Проверка готовых роликов по кадрам' },
  accept: {
    title: 'На приёмку',
    tip: 'Батч закрыт: ролики ждут вашей приёмки, фабрика подводит итоги',
  },
};

/**
 * Обычный порядок кадров (как run_plan фабрики): им рисуется лента без плана прогона, по нему
 * же встают кадры, которых в плане нет («не в этом прогоне»). Футаж — раньше исследования:
 * исследователь пишет сценарии по пулу, который собрал индексатор (CC-0090).
 */
export const USUAL: FrameKind[] = [
  'trends',
  'footage',
  'research',
  'extra',
  'scripts',
  'edit',
  'judge',
  'accept',
];

/**
 * Условные стадии фабрики — запускаются, только когда нужно: резерв футажа и сценариев, добор
 * тонкого пула и проверка плана после него; их повторы — в `REPEATS`. Признака «условная»
 * в ответе API нет, поэтому — по имени стадии. Единственный такой список в центре: при новой
 * условной стадии фабрики дописать её сюда.
 */
const CONDITIONAL = new Set([
  'footage-indexer-reserve',
  'content-researcher-reserve',
  'thin-pool-supplement',
  'plan-check-after-supplement',
]);

/** Вид повтора стадии: поздний (`*-late`) или после отказа судьи кадра (`*-judge`). */
export type RepeatKind = 'late' | 'judge';

/**
 * Повторы стадий — суффикс к имени стадии: `*-late` — поздний повтор резерва и добора (CC-0116);
 * `*-judge` — раунд добора из резерва после отказа судьи кадра (фабрика 2.16, CF-0798/0802,
 * CC-0150): семь стадий между `frame-judge` и `batch-done`, только при `reserve_after_judge`.
 * Повтор — условная и запасная стадия, его кадр — «Добор», имя — имя стадии с пометкой.
 * `anyBase` — повтором считается и повтор незнакомой стадии; у `-judge` так нельзя: сама
 * `frame-judge` кончается на `-judge`, поэтому только повтор стадии из словаря (`frame-judge-judge`
 * — повтор `frame-judge`). Новый повтор фабрики — новая строка здесь.
 */
const REPEATS: { kind: RepeatKind; suffix: string; label: string; anyBase: boolean }[] = [
  { kind: 'late', suffix: '-late', label: 'поздний повтор', anyBase: true },
  { kind: 'judge', suffix: '-judge', label: 'повтор после отказа судьи кадра', anyBase: false },
];

/** Стадия — повтор другой (`base`): вид повтора и пометка к имени; не повтор — `null`. */
export function repeatOf(
  id: string | null | undefined,
): { kind: RepeatKind; base: string; label: string } | null {
  if (!id) return null;
  for (const r of REPEATS) {
    if (!id.endsWith(r.suffix)) continue;
    const base = id.slice(0, -r.suffix.length);
    if (base && (r.anyBase || Object.hasOwn(STAGE_NAME, base)))
      return { kind: r.kind, base, label: r.label };
  }
  return null;
}

/** Стадия раунда добора после отказа судьи кадра (`*-judge`, CC-0150). */
export const isJudgeRound = (id: string | null | undefined): boolean =>
  repeatOf(id)?.kind === 'judge';

/** Кадр «Добор» из одних стадий `*-judge` — свой заголовок и подсказка (CC-0150). */
export const JUDGE_ROUND_FRAME = {
  title: 'Добор после судьи',
  tip: 'Судья кадра отказал роликам — фабрика добирает темы из резерва, монтирует и проверяет их заново. Только если был отказ',
};

/** Стадия запускается только когда нужно (резерв, добор, их повторы). */
export const isConditional = (id: string | null | undefined): boolean =>
  !!id && (CONDITIONAL.has(id) || repeatOf(id) !== null);

/**
 * Машинная стадия «нечего проверять» (CF-0707): ролик не собран — она пишет пустой итог судьи
 * кадров, а сама `frame-judge` тогда пропущена с причиной. Её кадр — «Проверка кадров» (правило
 * `frame|judge`), а не отдельный.
 */
export const JUDGE_EMPTY = 'frame-judge-empty';

/** Стадия фабрики → вид кадра; первое совпадение. */
const RULES: [RegExp, FrameKind][] = [
  [/^(studio|rights|batch-start|pool-maint)/, 'trends'],
  [/trend|shortlist/, 'trends'],
  [/compliance-scripts|script-check/, 'scripts'],
  [/research|script/, 'research'],
  [/footage|supplement|plan-check|pool/, 'footage'],
  [/edit|montage|render/, 'edit'],
  [/frame|judge|qc/, 'judge'],
  [/batch-done|accept|publish|monitor|triage|commit|rotation/, 'accept'],
];

/** Вид кадра стадии `id`; нет совпадения — `prev` (кадр предыдущей по плану стадии). */
export function kindOf(id: string | null | undefined, prev: FrameKind = 'trends'): FrameKind {
  if (!id) return prev;
  if (isConditional(id)) return 'extra';
  const hit = RULES.find(([re]) => re.test(id));
  return hit ? hit[1] : prev;
}

/** Общая подпись стадии фабрики словами: «Футаж», «Монтаж», «Добор»… */
export const stageTitle = (id: string | null | undefined): string => KINDS[kindOf(id)].title;

/**
 * Имя одной стадии фабрики словами (CC-0089: «Упал на стадии «Старт батча»»). Общая подпись
 * кадра (`stageTitle`) — для киноленты; здесь — точнее, по известным стадиям run_plan. Новой
 * стадии в списке нет — её кадр (`stageTitle`).
 */
const STAGE_NAME: Record<string, string> = {
  'studio-read-due': 'Чтение Studio',
  'rights-check': 'Проверка прав',
  'batch-start': 'Старт батча',
  'pool-maintenance': 'Уход за пулом футажа',
  'trend-hunter': 'Поиск трендов',
  'compliance-shortlist': 'Проверка тем на риски',
  'footage-indexer': 'Разметка футажа',
  'content-researcher': 'Исследование и сценарии',
  'footage-indexer-reserve': 'Резерв футажа',
  'content-researcher-reserve': 'Резерв сценариев',
  'thin-pool-supplement': 'Добор тонкого пула',
  'plan-check-after-supplement': 'Проверка плана после добора',
  'compliance-scripts': 'Проверка сценариев',
  'video-editor': 'Монтаж',
  'frame-judge': 'Проверка кадров',
  [JUDGE_EMPTY]: 'Проверка кадров: нечего проверять',
  'batch-done': 'Закрытие батча',
  monitors: 'Мониторы',
  triage: 'Разбор итогов',
  'rotation-backfill': 'Добор ротации',
  'footage-wanted': 'Список нужного футажа',
  'commit-records': 'Запись итогов',
};

/**
 * Стадия известна по имени (не только по кадру киноленты), повтор известной (`*-late`,
 * `*-judge`) — тоже (CC-0116, CC-0118, CC-0150).
 */
export function isKnownStage(id: string | null | undefined): boolean {
  if (!id) return false;
  if (Object.hasOwn(STAGE_NAME, id)) return true;
  const r = repeatOf(id);
  return !!r && Object.hasOwn(STAGE_NAME, r.base);
}

/** Имя стадии подобрано по виду кадра (правила `RULES`), а не угадано по умолчанию. */
export const hasKind = (id: string | null | undefined): boolean =>
  !!id && (isConditional(id) || RULES.some(([re]) => re.test(id)));

export function stageName(id: string | null | undefined): string {
  if (!id) return stageTitle(id);
  const r = repeatOf(id);
  if (r && Object.hasOwn(STAGE_NAME, r.base)) return `${STAGE_NAME[r.base]} (${r.label})`;
  return STAGE_NAME[id] ?? stageTitle(id);
}
