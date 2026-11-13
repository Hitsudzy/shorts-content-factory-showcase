// Группы списка «Разработки» по вехам (CC-0124): текущая веха каждого проекта сверху, потом
// следующие по дорожной карте, вехи вне карты, «без вехи», а сделанные — в конце (свежие первыми).
// Прогресс вехи — «сделано N из M» (без «не делаем») и пункты чеклистов её задач.
import type { DevRoadmap, DevTaskRow } from '@/api/dev';

import { compareVersions, sortRows, type Sort } from './filters';

export type Progress = {
  /** Сделано (`done`). */
  done: number;
  /** Задач в счёт: все, кроме «не делаем». */
  total: number;
  /** «Не делаем» — отдельно. */
  wontfix: number;
  checklist: { done: number; total: number };
};

export type Group = {
  key: string;
  project: string;
  milestone: string | null;
  /** Название вехи из ROADMAP (без версии), если веха там есть. */
  title: string | null;
  /** Дата «DONE» из ROADMAP; нет карты — сделана, если закрыты все задачи. */
  done: string | null;
  current: boolean;
  tasks: DevTaskRow[];
  progress: Progress;
};

export function progressOf(tasks: readonly DevTaskRow[]): Progress {
  const p: Progress = { done: 0, total: 0, wontfix: 0, checklist: { done: 0, total: 0 } };
  for (const t of tasks) {
    if (t.status === 'wontfix') p.wontfix++;
    else p.total++;
    if (t.status === 'done') p.done++;
    p.checklist.done += t.checklist.done;
    p.checklist.total += t.checklist.total;
  }
  return p;
}

/** Текущая веха проекта — первая не сделанная в его дорожной карте. */
export function currentMilestone(roadmap: DevRoadmap | undefined): string | null {
  return roadmap?.milestones.find((m) => !m.done && m.version)?.version ?? null;
}

const projectRank = (p: string) => (p === 'factory' ? 0 : p === 'center' ? 1 : 2);

export function groupTasks(
  rows: readonly DevTaskRow[],
  roadmaps: readonly DevRoadmap[] | undefined,
  sort: Sort,
): Group[] {
  const map = new Map<string, DevTaskRow[]>();
  for (const t of rows) {
    const key = `${t.project}|${t.milestone ?? ''}`;
    const list = map.get(key);
    if (list) list.push(t);
    else map.set(key, [t]);
  }
  const groups: { g: Group; rank: number; order: number }[] = [];
  for (const [key, tasks] of map) {
    const { project, milestone } = tasks[0]!;
    const rm = roadmaps?.find((r) => r.project === project && !r.error);
    const index = rm && milestone ? rm.milestones.findIndex((m) => m.version === milestone) : -1;
    const ms = index >= 0 ? rm!.milestones[index]! : null;
    const progress = progressOf(tasks);
    const allClosed = progress.done === progress.total;
    const done = ms
      ? (ms.done ?? null)
      : !rm && milestone && allClosed
        ? (lastClosed(tasks) ?? '')
        : null;
    const current = !!milestone && currentMilestone(rm) === milestone;
    const rank = current ? 0 : done !== null ? 4 : ms ? 1 : milestone ? 2 : 3;
    groups.push({
      g: {
        key,
        project,
        milestone: milestone ?? null,
        title: ms?.title ?? null,
        done,
        current,
        tasks: sortRows(tasks, sort),
        progress,
      },
      rank,
      order: index,
    });
  }
  groups.sort(
    (a, b) =>
      a.rank - b.rank ||
      (a.rank === 4 ? (b.g.done ?? '').localeCompare(a.g.done ?? '') : 0) ||
      (a.rank === 1 && a.g.project === b.g.project ? a.order - b.order : 0) ||
      projectRank(a.g.project) - projectRank(b.g.project) ||
      compareVersions(b.g.milestone ?? '', a.g.milestone ?? ''),
  );
  return groups.map((x) => x.g);
}

const lastClosed = (tasks: readonly DevTaskRow[]) =>
  tasks.reduce<string | null>((m, t) => (t.closed && (!m || t.closed > m) ? t.closed : m), null);
