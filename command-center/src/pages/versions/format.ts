// Слова экрана «Версии и агенты» (CC-0031): что значат поля `GET /api/versions` для человека.
// Строка фабрики (`why`, строки `scripts/agents status`), коммиты и пути — только под «Подробнее».
import type { AgentState, ModuleState, StatusLine, Versions } from '@/api/versions';
import { plural } from '@/pages/batches/format';

/** Агенты фабрики: имя, как его пишет фабрика, и что он делает. */
export const AGENT: Record<string, { name: string; role: string }> = {
  'compliance-checker': { name: 'Compliance Checker', role: 'проверяет ролик на правила и права' },
  'content-researcher': { name: 'Content Researcher', role: 'ищет темы и факты для сценария' },
  'footage-indexer': { name: 'Footage Indexer', role: 'собирает и размечает футаж' },
  'trend-hunter': { name: 'Trend Hunter', role: 'ищет, о чём сейчас говорят' },
  'video-editor': { name: 'Video Editor', role: 'монтирует ролик' },
};

/** «footage-indexer» → «Footage Indexer» (незнакомый агент — по словам имени). */
export function agentName(agent: string): string {
  return (
    AGENT[agent]?.name ??
    agent
      .split(/[-_\s]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  );
}

export function initials(agent: string): string {
  const [a, b] = agent.split(/[-_\s]+/).filter(Boolean);
  return (a && b ? a.charAt(0) + b.charAt(0) : agent.slice(0, 2)).toUpperCase();
}

/** «release/2.4» → «2.4»; не ветка выпуска — null. */
export function releaseOf(branch: string | null | undefined): string | null {
  const m = /^release\/(.+)$/.exec(branch ?? '');
  return m ? m[1]! : null;
}

/** «v2.3.4» → «2.3.4». */
export const bare = (tag: string) => tag.replace(/^v(?=\d)/, '');

/** Где стоит копия: словами, без имени ветки (оно — под «Подробнее»). */
export function branchText(branch: string | null | undefined, head?: string | null): string {
  if (branch === 'main') return 'основная ветка';
  const rel = releaseOf(branch);
  if (rel) return `ветка выпуска ${rel}`;
  if (branch) return 'своя ветка';
  return head === null ? 'не скачан' : 'без ветки, на отдельной версии кода';
}

/** «в 2 файлах» — где правки не зафиксированы. */
const inFiles = (n: number) => `в ${n} ${plural(n, 'файле', 'файлах', 'файлах')}`;

/**
 * Почему агент (или модуль) не на пине — словами, по полям строки фабрики, а не по её тексту
 * (`why` — под «Подробнее»). Агент на пине — null.
 */
export function driftText(r: AgentState | ModuleState): string | null {
  if (r.ok) return null;
  if (r.head === null) {
    if (r.sha === null) return `версии ${r.rev} нет в истории агента — её не скачать`;
    return 'не скачан в эту копию фабрики';
  }
  if (r.sha === null) return `версии ${r.rev} нет в истории агента — нужно подтянуть выпуски`;
  if (r.head !== r.sha) {
    const rel = releaseOf(r.branch);
    if (rel) return `стоит на ветке выпуска ${rel}, а не на ${r.rev}`;
    if (r.branch === 'main') return `стоит на основной ветке, а не на ${r.rev}`;
    if (r.branch) return `стоит на своей ветке, а не на ${r.rev}`;
    return `стоит на другой версии кода, а не на ${r.rev}`;
  }
  if (r.dirty === null) return 'не проверить, есть ли незафиксированные правки';
  if (r.dirty.length) return `${inFiles(r.dirty.length)} правки не зафиксированы`;
  if ('built' in r && !r.built) return 'собран не из пина — пересоберите';
  return 'ссылки на общие файлы не в порядке';
}

/** Что сделать, чтобы агент вернулся на пин. */
export const SYNC_COMMAND = 'scripts/agents sync';

/** Чинит ли расхождение синхронизация агентов: не чинит незафиксированные правки. */
export function syncFixes(r: AgentState | ModuleState): boolean {
  return !r.ok && !(r.head !== null && r.head === r.sha && r.dirty?.length);
}

export function fixText(r: AgentState | ModuleState): string | null {
  if (r.ok) return null;
  if (!syncFixes(r))
    return 'Синхронизация тут не поможет: зафиксируйте или отмените правки в папке агента, потом проверьте заново.';
  return 'Вернётся на пин синхронизацией агентов (команда — в полосе сверху).';
}

/** Замечание проверки вне агентов (строка `of: root`) — словами. */
export function rootLineText(l: StatusLine): string {
  if (/target is missing|points at itself|broken/i.test(l.text))
    return 'Битая ссылка на общий файл фабрики';
  if (/not linked yet/i.test(l.text)) return 'Общие файлы ещё не связаны с этой копией';
  return l.mark === 'WARN' ? 'Предупреждение проверки' : 'Расхождение с пинами';
}

/** Сколько агентов не на пине — и одна строка для шапки экрана. */
export function driftSummary(v: Versions): { off: number; total: number } {
  return { off: v.agents.filter((a) => !a.ok).length, total: v.agents.length };
}

export function agentsTitle(off: number, total: number): string {
  if (!total) return 'Агентов нет';
  if (!off) return total === 1 ? 'Агент на своём пине' : `Все ${total} на своих пинах`;
  return `${off} из ${total} ${plural(off, 'расходится', 'расходятся', 'расходятся')} с пином`;
}

/** Замечания проверки, которых нет у строк агентов и модулей. */
export const rootLines = (v: Versions) =>
  v.status.lines.filter((l) => l.of === 'root' && l.mark && l.mark !== 'ok');

/** Слово с подсказкой: пунктир снизу — «наведите, тут пояснение». */
export const DOTTED = 'cursor-help underline decoration-dotted underline-offset-4';

/** Подсказки к словам экрана — простыми словами. */
export const TIP = {
  pin: 'Пин — версия, закреплённая за агентом (или центром) в фабрике. Батч берёт агентов ровно на их пинах.',
  main: 'Основная ветка — то, на чём работает фабрика: последний готовый выпуск.',
  release:
    'Ветка выпуска — отдельная линия, где собирают следующую версию фабрики. Готовый выпуск переходит на основную ветку.',
  contract:
    'Договор API — общее описание того, какими данными обмениваются центр и фабрика. Если у них разные версии, часть экранов может не открыться.',
  readme: 'Версия, которую фабрика пишет в своём описании и в шапке каждого прогона.',
} as const;

/** Подсказка к месту, где стоит копия: основная ветка или ветка выпуска. */
export function branchTip(branch: string | null | undefined): string | null {
  if (branch === 'main') return TIP.main;
  return releaseOf(branch) ? TIP.release : null;
}

/** Подсветка расхождения: рамка и лёгкая заливка тоном «внимание». */
export const DRIFT_STYLE = {
  borderColor: 'color-mix(in srgb, var(--warning) 40%, var(--border))',
  background: 'color-mix(in srgb, var(--warning) 6%, var(--card))',
} as const;
