// Список задач «Разработки» (CC-0124): поиск, фильтры и сортировка — в адресе; группы по вехам
// (текущая сверху, сделанные свёрнуты), прогресс вехи, «показать ещё» вместо тысячи строк.
import { useEffect, useEffectEvent, useId, useMemo, useState, type CSSProperties } from 'react';

import { useDevRoadmap, useDevTasks, type DevSource, type DevTaskRow } from '@/api/dev';
import { Card } from '@/components/common/Card';
import { CheckIcon } from '@/components/common/icons';
import { SkeletonList } from '@/components/common/Skeletons';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { inputBase } from '@/pages/channels/styles';

import {
  applyFilters,
  EMPTY_FILTERS,
  hasFilters,
  NONE,
  optionsOf,
  SORT_LABEL,
  SORTS,
  toggle,
  type DevFilters,
  type ListKey,
  type Sort,
} from './filters';
import { groupTasks, type Group } from './groups';
import { Bar, IdText, TaskLink, TaskStatus } from './parts';
import { useFilters, type FiltersUpdate } from './useFilters';
import {
  dayText,
  milestoneText,
  PROJECTS,
  projectLabel,
  shortSha,
  statusWord,
  tasksWord,
  TONE_COLOR,
  typeLabel,
} from './words';

/** Строк в группе сразу; дальше — «показать ещё». */
const PAGE = 25;

function Search({ f, onChange }: { f: DevFilters; onChange: (q: string) => void }) {
  const [text, setText] = useState(f.q);
  const [seen, setSeen] = useState(f.q);
  // Адрес поменялся не отсюда (назад, ссылка) — поле следом.
  if (seen !== f.q) {
    setSeen(f.q);
    setText(f.q);
  }
  const commit = useEffectEvent((q: string) => onChange(q));
  useEffect(() => {
    if (text.trim() === f.q) return;
    const t = setTimeout(() => commit(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text, f.q]);
  return (
    <input
      type="search"
      aria-label="Поиск задач"
      data-testid="dev-search"
      value={text}
      onChange={(e) => setText(e.target.value)}
      placeholder="Номер, заголовок или текст задачи"
      className={cn(inputBase, 'h-[34px] min-w-0 flex-1 basis-60 sm:max-w-[26rem]')}
    />
  );
}

const SELECT_LABEL: Record<Exclude<ListKey, 'project' | 'status'>, [string, string]> = {
  milestone: ['Веха', 'все вехи'],
  type: ['Тип', 'все типы'],
  repo: ['Репозиторий', 'все репозитории'],
};

function valueLabel(key: ListKey, v: string): string {
  if (key === 'milestone') return v === NONE ? 'без вехи' : v;
  if (key === 'repo') return v === NONE ? 'без репозитория' : v;
  if (key === 'type') return v === NONE ? 'без типа' : typeLabel(v);
  if (key === 'status') return v === NONE ? 'без статуса' : statusWord(v).label;
  return projectLabel(v);
}

function Picker({
  k,
  f,
  rows,
  onChange,
}: {
  k: Exclude<ListKey, 'project' | 'status'>;
  f: DevFilters;
  rows: readonly DevTaskRow[];
  onChange: (update: FiltersUpdate) => void;
}) {
  const id = useId();
  const [label, all] = SELECT_LABEL[k];
  const options = optionsOf(rows, k);
  const many = f[k].length > 1 ? f[k].join(',') : null;
  const value = many ?? f[k][0] ?? '';
  // Значение из ссылки, которого нет среди задач, — всё равно видно в поле.
  const missing = !many && value && !options.some((o) => o.value === value);
  const owners = (v: string) =>
    k === 'milestone' && !f.project.length
      ? [...new Set(rows.filter((t) => (t.milestone ?? NONE) === v).map((t) => t.project))]
          .map((p) => projectLabel(p).toLowerCase())
          .join(', ')
      : '';
  return (
    <label htmlFor={id} className="grid min-w-0 gap-1 text-xs text-muted-foreground">
      {label}
      <select
        id={id}
        data-testid={`dev-${k}`}
        value={value}
        onChange={(e) => {
          const v = e.target.value ? e.target.value.split(',') : [];
          onChange((cur) => ({ ...cur, [k]: v }));
        }}
        className={cn(inputBase, 'h-[34px]')}
      >
        <option value="">{all}</option>
        {many ? <option value={many}>{f[k].map((v) => valueLabel(k, v)).join(', ')}</option> : null}
        {missing ? <option value={value}>{valueLabel(k, value)} · 0</option> : null}
        {options.map((o) => {
          const who = owners(o.value);
          return (
            <option key={o.value} value={o.value}>
              {valueLabel(k, o.value)}
              {who ? ` (${who})` : ''} · {o.n}
            </option>
          );
        })}
      </select>
    </label>
  );
}

/** Фабрика / центр / оба — как переключатель «Вопросы / Просьбы». */
export function ProjectSwitch({
  f,
  onChange,
}: {
  f: DevFilters;
  onChange: (update: FiltersUpdate) => void;
}) {
  const one = f.project.length === 1 ? f.project[0] : null;
  const item = (p: string | null, label: string) => (
    <button
      key={p ?? 'all'}
      type="button"
      data-testid={`dev-project-${p ?? 'all'}`}
      aria-pressed={one === p}
      onClick={() => onChange((cur) => ({ ...cur, project: p ? [p] : [] }))}
      className={cn(
        'inline-flex h-[30px] items-center rounded-sm px-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground',
        one === p && 'bg-card font-semibold text-foreground shadow-[inset_0_0_0_1px_var(--border)]',
      )}
    >
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label="Чьи задачи"
      className="inline-flex w-max gap-1 rounded-md border bg-[color-mix(in_srgb,var(--muted-foreground)_6%,transparent)] p-1"
    >
      {item(null, 'Все')}
      {PROJECTS.map((p) => item(p, projectLabel(p)))}
    </div>
  );
}

function StatusChips({
  f,
  rows,
  onChange,
}: {
  f: DevFilters;
  rows: readonly DevTaskRow[];
  onChange: (update: FiltersUpdate) => void;
}) {
  const options = optionsOf(rows, 'status');
  for (const s of f.status)
    if (!options.some((o) => o.value === s)) options.push({ value: s, n: 0 });
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Статус">
      {options.map((o) => {
        const on = f.status.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            data-testid="dev-status"
            data-status={o.value}
            onClick={() => onChange((cur) => toggle(cur, 'status', o.value))}
            style={
              {
                '--chip': TONE_COLOR[statusWord(o.value).tone].text,
                '--chip-dot': TONE_COLOR[statusWord(o.value).tone].dot,
              } as CSSProperties
            }
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs whitespace-nowrap',
              on
                ? 'border-[var(--chip)] bg-[color-mix(in_srgb,var(--chip)_6%,var(--card))] font-semibold text-[var(--chip)] shadow-[inset_0_0_0_1px_var(--chip)]'
                : 'text-muted-foreground hover:border-muted-foreground',
            )}
          >
            {on ? (
              <CheckIcon aria-hidden className="size-3" data-testid="dev-status-on" />
            ) : (
              <span aria-hidden className="size-[7px] rounded-full bg-[var(--chip-dot)]" />
            )}
            {valueLabel('status', o.value)} · {o.n}
          </button>
        );
      })}
    </div>
  );
}

function TaskRow({ t }: { t: DevTaskRow }) {
  const meta = [
    t.type ? typeLabel(t.type) : null,
    t.repo,
    t.created ? `заведена ${dayText(t.created)}` : null,
    t.closed ? `закрыта ${dayText(t.closed)}` : null,
    t.checklist.total ? `чеклист ${t.checklist.done} из ${t.checklist.total}` : null,
    t.archive ? `архив ${t.archive}` : null,
  ].filter(Boolean);
  return (
    <li
      data-testid="task-row"
      data-id={t.id}
      className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 border-t py-2.5 first:border-t-0 sm:grid-cols-[5.5rem_minmax(0,1fr)_auto]"
    >
      <span className="pt-px font-mono text-[13px] whitespace-nowrap text-muted-foreground">
        {t.id}
      </span>
      <div className="min-w-0">
        <TaskLink
          id={t.id}
          className="font-sans text-[13.5px] whitespace-normal text-foreground [overflow-wrap:anywhere]"
        >
          <IdText text={t.title ?? t.id} />
        </TaskLink>
        <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
          {meta.map((m, i) => (
            <span key={i}>{m}</span>
          ))}
          {t.blocked_by.length ? (
            <span>
              ждёт{' '}
              {t.blocked_by.map((b, i) => (
                <span key={b}>
                  {i ? ', ' : ''}
                  <TaskLink id={b} />
                </span>
              ))}
            </span>
          ) : null}
        </div>
      </div>
      <TaskStatus status={t.status} className="col-start-2 w-max sm:col-start-3 sm:row-start-1" />
    </li>
  );
}

function groupChip(g: Group) {
  if (g.current) return <StatusBadge tone="live">текущая</StatusBadge>;
  if (g.done !== null)
    return <StatusBadge tone="ok">{g.done ? `сделана ${dayText(g.done)}` : 'сделана'}</StatusBadge>;
  if (g.milestone) return <StatusBadge tone="idle">впереди</StatusBadge>;
  return null;
}

function GroupCard({
  g,
  open,
  filtered,
  onToggle,
}: {
  g: Group;
  open: boolean;
  /** Активен фильтр: прогресс — по выборке, и подпись это говорит. */
  filtered: boolean;
  onToggle: () => void;
}) {
  const [shown, setShown] = useState(PAGE);
  const p = g.progress;
  const bodyId = useId();
  const rest = g.tasks.length - shown;
  return (
    <Card data-testid="dev-group" data-key={g.key} data-open={open || undefined} className="p-0">
      <h2 className="m-0">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={onToggle}
          className="grid w-full gap-2 px-card py-3 text-left"
        >
          <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <span aria-hidden className="text-muted-foreground">
              {open ? '▾' : '▸'}
            </span>
            <span className="eyebrow">{projectLabel(g.project)}</span>
            <span className="text-[15px] font-semibold">
              {g.milestone ? milestoneText(g.milestone) : 'Без вехи'}
              {g.title ? (
                <>
                  {' — '}
                  <IdText text={g.title} />
                </>
              ) : null}
            </span>
            {groupChip(g)}
          </span>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span data-testid="group-progress">
              {filtered ? `в выборке: ${g.tasks.length} · ` : ''}
              сделано {p.done} из {p.total}
              {p.wontfix ? ` · не делаем ${p.wontfix}` : ''}
            </span>
            {p.checklist.total ? (
              <span data-testid="group-checklist">
                пункты чеклистов{filtered ? ' в выборке' : ''}: {p.checklist.done} из{' '}
                {p.checklist.total}
              </span>
            ) : null}
            <span className="w-28 max-sm:w-full">
              <Bar done={p.done} total={p.total} label={`Сделано ${p.done} из ${p.total}`} />
            </span>
          </span>
        </button>
      </h2>
      {open ? (
        <div id={bodyId} className="border-t px-card pb-2">
          <ul className="m-0 list-none p-0">
            {g.tasks.slice(0, shown).map((t) => (
              <TaskRow key={t.id} t={t} />
            ))}
          </ul>
          {rest > 0 ? (
            <div className="border-t pt-2">
              <Button
                size="sm"
                variant="ghost"
                data-testid="dev-more"
                onClick={() => setShown(shown + PAGE * 4)}
              >
                Показать ещё {Math.min(rest, PAGE * 4)} из {rest}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

/** Откуда прочитаны задачи: ветка и коммит каждого репо; ошибка источника — заметно. */
export function Sources({ sources }: { sources: readonly DevSource[] }) {
  const broken = sources.filter((s) => s.error);
  return (
    <>
      {broken.map((s) => (
        <div
          key={s.project}
          role="status"
          data-testid="dev-source-error"
          className="rounded-lg border border-l-[3px] border-l-warning px-4 py-3 text-[13px]"
        >
          <b className="font-semibold">
            {s.project === 'center' ? 'Задачи центра' : 'Задачи фабрики'} сейчас не прочитать
          </b>{' '}
          <span className="text-muted-foreground">
            — git не отдал ветку {s.branch}; в списке их нет. Причина: {s.error}
          </span>
        </div>
      ))}
    </>
  );
}

export function SourcesLine({ sources }: { sources: readonly DevSource[] }) {
  if (!sources.length) return null;
  return (
    <p className="m-0 text-xs text-muted-foreground" data-testid="dev-sources">
      Прочитано из git:{' '}
      {sources.map((s, i) => (
        <span key={s.project}>
          {i ? ' · ' : ''}
          {projectLabel(s.project).toLowerCase()} — {s.branch}{' '}
          <span className="font-mono">{s.error ? 'не прочитано' : shortSha(s.sha)}</span>
        </span>
      ))}
    </p>
  );
}

export function TaskList() {
  const [f, setF] = useFilters();
  const all = useDevTasks('');
  const found = useDevTasks(f.q);
  const roadmap = useDevRoadmap();
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const base = f.q ? found.data : all.data;
  const searching = !!f.q && (found.isPlaceholderData || found.isPending);
  const rows = useMemo(() => base?.tasks ?? [], [base]);
  const shown = useMemo(() => applyFilters(rows, f), [rows, f]);
  const groups = useMemo(
    () => groupTasks(shown, roadmap.data, f.sort),
    [shown, roadmap.data, f.sort],
  );
  // Варианты выбора и счёт — по найденному, без своего же ключа: видно, сколько даст выбор.
  const without = (k: ListKey) => applyFilters(rows, { ...f, [k]: [] });
  const filtered = hasFilters(f);

  const onQ = (q: string) => setF((cur) => ({ ...cur, q }));
  const isOpen = (g: Group) => toggled[g.key] ?? (filtered || g.done === null);

  return (
    <>
      <div className="grid gap-2.5" data-testid="dev-filters">
        <div className="flex flex-wrap items-center gap-2">
          <Search f={f} onChange={onQ} />
          <ProjectSwitch f={f} onChange={setF} />
        </div>
        <StatusChips f={f} rows={without('status')} onChange={setF} />
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-end">
          <Picker k="milestone" f={f} rows={without('milestone')} onChange={setF} />
          <Picker k="type" f={f} rows={without('type')} onChange={setF} />
          <Picker k="repo" f={f} rows={without('repo')} onChange={setF} />
          <SortPicker sort={f.sort} onChange={(sort) => setF((cur) => ({ ...cur, sort }))} />
        </div>
      </div>
      {all.isPending && !base ? (
        <SkeletonList rows={6} label="Читаю задачи из git…" data-testid="dev-pending" />
      ) : all.isError && !base ? (
        <Card>
          <ErrorState
            title="Задачи не прочитать"
            error={all.error}
            onRetry={() => void all.refetch()}
          >
            API не ответил на список задач. Проверьте, что API центра запущен.
          </ErrorState>
        </Card>
      ) : found.isError && f.q ? (
        <Card>
          <ErrorState
            title="Поиск не удался"
            error={found.error}
            onRetry={() => void found.refetch()}
          >
            API не ответил на поиск по задачам.
          </ErrorState>
        </Card>
      ) : (
        <>
          <Sources sources={base?.sources ?? []} />
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground"
            aria-live="polite"
          >
            <span data-testid="dev-count" data-n={shown.length}>
              {searching
                ? 'Ищу…'
                : filtered
                  ? `Нашлось ${tasksWord(shown.length)} из ${base?.total ?? rows.length}`
                  : `Всего ${tasksWord(shown.length)}`}
            </span>
            {filtered ? (
              <Button
                size="sm"
                variant="link"
                className="h-auto px-0"
                data-testid="dev-reset"
                onClick={() => setF((cur) => ({ ...EMPTY_FILTERS, sort: cur.sort }))}
              >
                Сбросить фильтры
              </Button>
            ) : null}
          </div>
          {groups.length ? (
            <div className="grid gap-gap" data-testid="dev-groups">
              {groups.map((g) => (
                <GroupCard
                  key={g.key}
                  g={g}
                  open={isOpen(g)}
                  filtered={filtered}
                  onToggle={() => setToggled({ ...toggled, [g.key]: !isOpen(g) })}
                />
              ))}
            </div>
          ) : (
            <EmptyState title="Ничего не нашлось">
              Ни одна задача не подходит под поиск и фильтры. Попробуйте другое слово или сбросьте
              фильтры.
            </EmptyState>
          )}
          <SourcesLine sources={base?.sources ?? []} />
        </>
      )}
    </>
  );
}

function SortPicker({ sort, onChange }: { sort: Sort; onChange: (s: Sort) => void }) {
  const id = useId();
  return (
    <label htmlFor={id} className="grid min-w-0 gap-1 text-xs text-muted-foreground">
      Порядок
      <select
        id={id}
        data-testid="dev-sort"
        value={sort}
        onChange={(e) => onChange(e.target.value as Sort)}
        className={cn(inputBase, 'h-[34px]')}
      >
        {SORTS.map((s) => (
          <option key={s} value={s}>
            {SORT_LABEL[s]}
          </option>
        ))}
      </select>
    </label>
  );
}
