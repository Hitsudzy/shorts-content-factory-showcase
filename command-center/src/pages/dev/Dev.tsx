// «Разработка» (CC-0124, API — cc/api, договор 0.66.0) — только чтение: задачи фабрики и центра
// с вехами, поиском и фильтрами (всё в адресе), карточка задачи `/dev/<id>` и дорожная карта
// `?view=roadmap`. Статусы меняет фабрика сама — у экрана нет ни одной кнопки записи.
import { useSearchParams } from 'react-router';

import { Tip } from '@/components/common/Tip';
import { useLiveSearchParams } from '@/lib/useLiveSearchParams';
import { cn } from '@/lib/utils';

import { Roadmap } from './Roadmap';
import { ProjectSwitch, TaskList } from './TaskList';
import { useFilters } from './useFilters';

type View = 'tasks' | 'roadmap';

function ViewSwitch({ view }: { view: View }) {
  // CC-0162: от текущего адреса — щелчок по виду сразу после фильтра его не сотрёт.
  const [, setParams] = useLiveSearchParams();
  const pick = (v: View) =>
    setParams((next) => {
      if (v === 'roadmap') next.set('view', 'roadmap');
      else next.delete('view');
      return next;
    });
  const item = (v: View, label: string, tip: string) => (
    <Tip content={tip}>
      <button
        type="button"
        data-testid={`dev-view-${v}`}
        aria-pressed={view === v}
        onClick={() => pick(v)}
        className={cn(
          'inline-flex h-9 items-center rounded-sm px-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground',
          view === v &&
            'bg-card font-semibold text-foreground shadow-[inset_0_0_0_1px_var(--border)]',
        )}
      >
        {label}
      </button>
    </Tip>
  );
  return (
    <div
      role="group"
      aria-label="Что показать"
      data-testid="dev-view"
      className="inline-flex w-max gap-1 rounded-md border bg-[color-mix(in_srgb,var(--muted-foreground)_6%,transparent)] p-1"
    >
      {item('tasks', 'Задачи', 'Все задачи фабрики и центра: поиск, фильтры, группы по вехам')}
      {item('roadmap', 'Дорожная карта', 'ROADMAP.md фабрики и центра: вехи, спринты и их задачи')}
    </div>
  );
}

export function Dev() {
  const [params] = useSearchParams();
  const view: View = params.get('view') === 'roadmap' ? 'roadmap' : 'tasks';
  const [f, setF] = useFilters();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">Задачи фабрики и центра: вехи, статусы, история</div>
          <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
            Разработка
          </h1>
          <p className="m-0 mt-1 text-xs text-muted-foreground" data-testid="dev-readonly">
            Только просмотр: статусы задач меняет фабрика сама, центр их не правит.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view === 'roadmap' ? <ProjectSwitch f={f} onChange={setF} /> : null}
          <ViewSwitch view={view} />
        </div>
      </div>
      {view === 'roadmap' ? <Roadmap /> : <TaskList />}
    </>
  );
}
