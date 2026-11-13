// Слова «Разработки» (CC-0124): статусы, типы, проекты и даты задач — по-русски, цветом статуса.
import type { Tone } from '@/components/common/Status';

export type Project = 'factory' | 'center';

export const PROJECTS: readonly Project[] = ['factory', 'center'];

export const PROJECT_LABEL: Record<Project, string> = { factory: 'Фабрика', center: 'Центр' };

export const projectLabel = (p: string) => PROJECT_LABEL[p as Project] ?? p;

/** Статусы фронтматтера в порядке «что важнее сейчас» — так же сортирует «по статусу». */
export const STATUSES = ['needs-you', 'blocked', 'in-progress', 'open', 'done', 'wontfix'] as const;

const STATUS: Record<string, { label: string; tone: Tone; tip: string }> = {
  'needs-you': { label: 'ждёт вас', tone: 'warn', tip: 'Фабрике нужно ваше решение или действие' },
  blocked: {
    label: 'заблокирована',
    tone: 'danger',
    tip: 'Ждёт другую задачу или внешнее событие',
  },
  'in-progress': { label: 'в работе', tone: 'live', tip: 'Задачу сейчас делает фабрика' },
  open: { label: 'открыта', tone: 'idle', tip: 'Заведена, ещё не начата' },
  done: { label: 'сделана', tone: 'ok', tip: 'Сделана и закрыта' },
  wontfix: { label: 'не делаем', tone: 'idle', tip: 'Решили не делать — закрыта без работы' },
};

export function statusWord(s: string | null | undefined): {
  label: string;
  tone: Tone;
  tip: string;
} {
  if (!s) return { label: 'без статуса', tone: 'idle', tip: 'В фронтматтере нет статуса' };
  return STATUS[s] ?? { label: s, tone: 'idle', tip: `Статус «${s}» из фронтматтера` };
}

export const statusRank = (s: string | null | undefined) => {
  const i = (STATUSES as readonly string[]).indexOf(s ?? '');
  return i < 0 ? STATUSES.length : i;
};

/** Закрыта ли задача (сделана или решили не делать). */
export const isClosed = (s: string | null | undefined) => s === 'done' || s === 'wontfix';

const TYPE: Record<string, string> = {
  task: 'задача',
  bug: 'ошибка',
  chore: 'уборка',
  research: 'исследование',
  feature: 'возможность',
  spike: 'разведка',
  epic: 'эпик',
  'tech-debt': 'техдолг',
};

export const typeLabel = (t: string | null | undefined) => (t ? (TYPE[t] ?? t) : '—');

/**
 * Дата фронтматтера `YYYY-MM-DD` → «13.10» (этот год) или «13.10.2025»; не дата — как есть.
 * ISO со временем (коммиты) — тоже по дню.
 */
export function dayText(d: string | null | undefined, now = new Date()): string | null {
  if (!d) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return d;
  const [, y, mo, day] = m;
  return Number(y) === now.getFullYear() ? `${day}.${mo}` : `${day}.${mo}.${y}`;
}

/** «2.9» / «1.1» → «веха 2.9»; без вехи — «без вехи». */
export const milestoneText = (v: string | null | undefined) => (v ? `веха ${v}` : 'без вехи');

/** «N задач» по-русски. */
export function tasksWord(n: number): string {
  const d = n % 10;
  const h = n % 100;
  if (d === 1 && h !== 11) return `${n} задача`;
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return `${n} задачи`;
  return `${n} задач`;
}

/** Короткий sha для подписи. */
export const shortSha = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : '—');

/** Цвет статуса для чипа фильтра (CC-0124): текст и рамка — `text`, точка — `dot`. */
export const TONE_COLOR: Record<Tone, { text: string; dot: string }> = {
  ok: { text: 'var(--success)', dot: 'var(--success)' },
  warn: { text: 'var(--warning)', dot: 'var(--warning)' },
  danger: { text: 'var(--danger)', dot: 'var(--danger)' },
  live: { text: 'var(--primary-text)', dot: 'var(--primary)' },
  idle: { text: 'var(--foreground)', dot: 'var(--muted-foreground)' },
};
