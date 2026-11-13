// «Расход» (CC-0033): токены батча по стадиям (`usage_report.py`) и сравнение батча вручную с
// батчем исполнителя (`compare_runs.py`). Батчи — из истории прогонов, каналом и временем по МСК;
// id батча, команды и строки фабрики — под «Подробнее». Денег в отчёте фабрики нет — только токены.
import { useState } from 'react';

import { useBatchHistory, type BatchHistory } from '@/api/batches';
import { useCompare, useUsage, type CompareRuns, type UsageReport } from '@/api/maintenance';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { Pending, SkeletonRows, SkeletonText } from '@/components/common/Skeletons';
import { EmptyState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { durationText } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { Loaded } from '@/components/common/Loaded';

import {
  batchText,
  byStage,
  callsWord,
  countLabel,
  defectsWord,
  defectText,
  modelName,
  tokensText,
  wallSum,
} from './format';
import { BatchSelect, Tile } from './parts';

type Run = BatchHistory['runs'][number];
type Option = { value: string; label: string; byHand: boolean };

/** Прошлые батчи каналов (без пересборок) для выбора: новые сверху. */
function runOptions(runs: Run[], name: (id: string) => string): Option[] {
  const out: Option[] = [];
  for (const r of runs) {
    if (!r.batch || r.batch.startsWith('rebuilds/') || out.some((o) => o.value === r.batch))
      continue;
    out.push({ value: r.batch, label: batchText(r.batch, name), byHand: !r.launch });
  }
  return out;
}

const TIPS = {
  total: 'Все токены батча: ввод, запись в кэш, чтение из кэша и ответ моделей',
  fresh:
    'То, что модели обработали заново: ввод, запись в кэш и ответ. Чтение из кэша сюда не входит',
  cache: 'Повторно прочитанное из кэша — самая дешёвая часть расхода',
  calls: 'Сколько раз агенты батча обращались к моделям',
  money:
    'В отчёте фабрики только токены: цену в деньгах она не пишет, поэтому центр её не показывает',
};

const UsageSkeleton = () => (
  <Pending label="Фабрика считает расход…" className="gap-3">
    <span className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-[74px] rounded-sm" />
      ))}
    </span>
    <SkeletonRows bare rows={5} height={40} gap={6} bordered={false} />
  </Pending>
);

function UsageView({ r }: { r: UsageReport }) {
  if (!r.ok)
    return (
      <div className="grid gap-2" data-testid="usage-none">
        <EmptyState title="Расход этого батча ещё не посчитан">
          Батч шёл до учёта расхода — фабрика посчитает его по записям агентов, когда её попросят.
        </EmptyState>
        <More className="mt-0">
          {r.why ? <span>{r.why}</span> : null}
          <span>
            {r.batch} · {r.events}
          </span>
        </More>
      </div>
    );
  const t = r.totals;
  const stages = byStage(r.rows);
  const max = Math.max(1, ...stages.map((s) => s.total));
  return (
    <div className="grid gap-3" data-testid="usage-view">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile
          label="Всего токенов"
          value={tokensText(t.total)}
          tip={TIPS.total}
          testId="usage-total"
        />
        <Tile
          label="Новые"
          value={tokensText(t.fresh)}
          sub={`${Math.round(t.fresh_pct)}% расхода`}
          tip={TIPS.fresh}
          testId="usage-fresh"
        />
        <Tile
          label="Из кэша"
          value={tokensText(t.cache_read)}
          sub={`${Math.round(t.cache_read_pct)}% расхода`}
          tip={TIPS.cache}
        />
        <Tile label="Вызовы моделей" value={tokensText(t.calls)} tip={TIPS.calls} />
      </div>
      <Tip content={TIPS.money} wide>
        <span
          tabIndex={0}
          className="w-max text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          data-testid="usage-money"
        >
          Деньги: фабрика их не считает — только токены
        </span>
      </Tip>
      <ul className="m-0 grid list-none gap-1.5 p-0" data-testid="usage-stages">
        {stages.map((s) => (
          <li
            key={s.stage}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1"
            data-testid="usage-stage"
          >
            <span className="min-w-0 text-[13px]">
              <b className="font-semibold">{s.title}</b>{' '}
              <span className="text-xs text-muted-foreground">
                {s.models.join(', ')} · {callsWord(s.calls)}
              </span>
            </span>
            <span className="self-start text-[13px] whitespace-nowrap tabular-nums">
              {tokensText(s.total)}{' '}
              <span className="text-xs text-muted-foreground">
                {Math.round((s.total / Math.max(1, t.total)) * 100)}%
              </span>
            </span>
            <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full bg-primary"
                style={{ width: `${Math.max(2, (s.total / max) * 100)}%` }}
              />
            </span>
          </li>
        ))}
      </ul>
      <More className="mt-0">
        <span>{r.command}</span>
        <span>
          {r.batch} · {r.events} · посчитано {r.computed ?? '—'}
        </span>
        <span>
          ввод {t.input} · запись в кэш {t.cache_write} · чтение из кэша {t.cache_read} · ответ{' '}
          {t.output} · размышления {t.thinking}
        </span>
        {r.rows.map((row, i) => (
          <span key={i}>
            {row.stage ?? '—'} · {row.model ?? '—'} ({modelName(row.model)}) · {row.role ?? '—'} ·{' '}
            {row.calls ?? 0} calls · {row.minutes ?? 0} min
          </span>
        ))}
      </More>
    </div>
  );
}

function UsagePick({ options }: { options: Option[] }) {
  const [batch, setBatch] = useState(options[0]!.value);
  const q = useUsage(batch);
  return (
    <div className="grid gap-3">
      <BatchSelect
        label="Батч"
        value={batch}
        onChange={setBatch}
        options={options}
        testId="usage-batch"
      />
      <Loaded
        q={q}
        reading="Фабрика считает расход…"
        failed="Расход не прочитан"
        skeleton={<UsageSkeleton />}
      >
        {(r) => <UsageView r={r} />}
      </Loaded>
    </div>
  );
}

function useRuns() {
  const q = useBatchHistory();
  const name = useChannelNames();
  return { q, options: q.data ? runOptions(q.data.runs, name) : [] };
}

export function UsageCard() {
  const { q, options } = useRuns();
  return (
    <Card aria-labelledby="usage-title" data-testid="usage">
      <CardHead eyebrow="Расход токенов" title="Расход батча" titleId="usage-title" />
      <Loaded
        q={q}
        reading="Читаю прошлые батчи…"
        failed="Прошлые батчи не прочитаны"
        skeleton={
          <Pending label="Читаю прошлые батчи…" className="gap-3">
            <Skeleton className="h-[52px] rounded-sm" />
            <UsageSkeleton />
          </Pending>
        }
      >
        {() =>
          options.length ? (
            <UsagePick options={options} />
          ) : (
            <EmptyState title="Прошлых батчей ещё нет">
              Расход появится, когда фабрика закончит первый батч.
            </EmptyState>
          )
        }
      </Loaded>
    </Card>
  );
}

// ---------------------------------------------------------------- сравнение прогонов
const COMPARE_TIP =
  'Батч, прогнанный вручную, против батча исполнителя: те же ли стадии, в том же ли порядке и те же ли файлы результата. Темы и ролики у двух батчей всегда разные — их количество показано, не оценено';

function CompareView({ c, name }: { c: CompareRuns; name: (id: string) => string }) {
  const keys = [...new Set([...Object.keys(c.counts.manual), ...Object.keys(c.counts.executor)])];
  const wait = c.wall.operator_wait_s;
  return (
    <div className="grid gap-3" data-testid="compare-view" data-same={c.same ? '1' : '0'}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          tone={c.same ? 'ok' : 'warn'}
          tip={
            c.same
              ? 'Стадии, порядок и файлы совпадают'
              : 'Исполнитель прошёл батч не так, как вручную'
          }
        >
          {c.same ? 'ход прогона одинаков' : defectsWord(c.defects.length)}
        </StatusBadge>
        <span className="text-[13px]" data-testid="compare-verdict">
          {c.same
            ? 'Исполнитель проходит батч так же, как вручную: те же стадии, тот же порядок, те же файлы.'
            : 'Исполнитель прошёл батч не так, как вручную, — вот где:'}
        </span>
      </div>
      {c.defects.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-[13px]" data-testid="compare-defects">
          {c.defects.map((d, i) => (
            <li key={i}>{defectText(d)}</li>
          ))}
        </ul>
      ) : null}
      {c.notes.length ? (
        <ul
          className="m-0 grid list-none gap-1 p-0 text-xs text-muted-foreground"
          data-testid="compare-notes"
        >
          {c.notes.map((d, i) => (
            <li key={i}>{defectText(d)}</li>
          ))}
        </ul>
      ) : null}
      <div className="overflow-x-auto">
        <table
          className="w-full min-w-[300px] border-collapse text-[13px]"
          data-testid="compare-counts"
        >
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-2 font-normal">Что вышло</th>
              <th className="py-1 pr-3 pl-3 text-right font-normal">Вручную</th>
              <th className="py-1 pl-3 text-right font-normal">Исполнитель</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k} className="border-t">
                <td className="py-1.5 pr-2">{countLabel(k)}</td>
                <td className="py-1.5 pr-3 pl-3 text-right whitespace-nowrap tabular-nums">
                  {c.counts.manual[k] ?? '—'}
                </td>
                <td className="py-1.5 pl-3 text-right whitespace-nowrap tabular-nums">
                  {c.counts.executor[k] ?? '—'}
                </td>
              </tr>
            ))}
            <tr className="border-t">
              <td className="py-1.5 pr-2">Время батча</td>
              <td className="py-1.5 pr-3 pl-3 text-right whitespace-nowrap tabular-nums">
                {durationText(wallSum(c.wall.manual)) ?? '—'}
              </td>
              <td className="py-1.5 pl-3 text-right whitespace-nowrap tabular-nums">
                {durationText(wallSum(c.wall.executor)) ?? '—'}
              </td>
            </tr>
            <tr className="border-t">
              <td className="py-1.5 pr-2">
                <Tip content="Ожидание человека, простой оператора и неучтённое время">
                  <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
                    Из них ожидание
                  </span>
                </Tip>
              </td>
              <td className="py-1.5 pr-3 pl-3 text-right whitespace-nowrap tabular-nums">
                {durationText(wait.manual) ?? '—'}
              </td>
              <td className="py-1.5 pl-3 text-right whitespace-nowrap tabular-nums">
                {durationText(wait.executor) ?? '—'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <More className="mt-0">
        <span>{c.command}</span>
        <span>
          {batchText(c.manual, name)} = {c.manual} · {batchText(c.executor, name)} = {c.executor}
        </span>
        <span>вручную: {c.stages.manual.join(' > ')}</span>
        <span>исполнитель: {c.stages.executor.join(' > ')}</span>
        {[...c.defects, ...c.notes].map((d, i) => (
          <span key={i}>{d}</span>
        ))}
        <span>exit {c.exit_code}</span>
      </More>
    </div>
  );
}

function ComparePick({ options }: { options: Option[] }) {
  const name = useChannelNames();
  const hand = options.find((o) => o.byHand) ?? options[0]!;
  const exec = options.find((o) => !o.byHand && o.value !== hand.value) ?? options[1] ?? hand;
  const [manual, setManual] = useState(hand.value);
  const [executor, setExecutor] = useState(exec.value);
  const [pair, setPair] = useState<{ manual: string; executor: string } | null>(null);
  const q = useCompare(pair);
  const label = (o: Option) => ({
    value: o.value,
    // Подпись поля уже говорит «вручную/исполнителем»: в пункте — только метка ручного прогона,
    // иначе на телефоне выбранный батч обрезается (CC-0131).
    label: o.byHand ? `${o.label} · вручную` : o.label,
  });
  const same = manual === executor;
  return (
    <div className="grid gap-3">
      <div className="grid gap-2">
        <BatchSelect
          label="Вручную"
          value={manual}
          onChange={setManual}
          options={options.map(label)}
          testId="compare-manual"
        />
        <BatchSelect
          label="Исполнителем"
          value={executor}
          onChange={setExecutor}
          options={options.map(label)}
          testId="compare-executor"
        />
        <Button
          size="sm"
          className="justify-self-start"
          data-testid="compare-run"
          disabled={same}
          title={same ? 'Выберите два разных батча' : undefined}
          onClick={() => setPair({ manual, executor })}
        >
          Сравнить
        </Button>
      </div>
      {pair ? (
        <Loaded
          q={q}
          reading="Фабрика сравнивает прогоны…"
          failed="Прогоны не сравнились"
          skeleton={<SkeletonText lines={6} label="Фабрика сравнивает прогоны…" />}
        >
          {(c) => <CompareView c={c} name={name} />}
        </Loaded>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="compare-hint">
          Выберите батч, прогнанный вручную, и батч исполнителя — фабрика сверит стадии, порядок и
          файлы.
        </p>
      )}
    </div>
  );
}

export function CompareCard() {
  const { q, options } = useRuns();
  return (
    <Card aria-labelledby="compare-title" data-testid="compare">
      <CardHead
        eyebrow="Сравнение прогонов"
        title={
          <Tip content={COMPARE_TIP} wide>
            <span tabIndex={0}>Вручную и исполнителем</span>
          </Tip>
        }
        titleId="compare-title"
      />
      <Loaded
        q={q}
        reading="Читаю прошлые батчи…"
        failed="Прошлые батчи не прочитаны"
        skeleton={<SkeletonText lines={4} className="gap-[17px]" label="Читаю прошлые батчи…" />}
      >
        {() =>
          options.length > 1 ? (
            <ComparePick options={options} />
          ) : (
            <EmptyState title="Сравнивать пока нечего">
              Нужны хотя бы два прошлых батча — вручную и исполнителем.
            </EmptyState>
          )
        }
      </Loaded>
    </Card>
  );
}
