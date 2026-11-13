// «Пересобрать…» ролика (CC-0063, API CC-0048/0049). Подготовка — только чтение: режим из плана
// канала (`…/rebuild/modes`, названия — его), замечания текстом, секунды ролика («12 18 24») →
// `…/blocks?at=` → что на экране в эти моменты: блок, окно, кадры. У каждого момента —
// исключение кадра (оставить или убрать), у склейки — соседний блок (`near`) как вариант, где
// исключить нельзя (`exclude: null`) — почему (`note` фабрики). Исключения — только в режиме,
// который их берёт (`reedit`); в остальных секунды уходят замечанием. Запись — «Проверить и
// пересобрать…»: план фабрики (`…/rebuild/plan`) с токеном и подтверждение с отсчётом
// (`useConfirmFlow`, `ConfirmDialog` → `WriteButton`); «да» шлёт только `{confirm}`.
// `confirm_*`/`check_changed` — план заново сам; `busy` — идёт запуск или другая пересборка,
// токен цел. Итог: запущена — `rebuild_id` и ссылка в «Батчи»; каталог есть, исполнитель не
// стартовал (200 `ok:false`) — «Продолжить» там же. Ролик, отказанный после монтажа (CC-0116):
// сверху — что исходный ролик отказан и почему (`video.refused`, ворота — и из режимов), в плане
// у такого ролика — та же пометка (`refused` плана); нет плана монтажа (`plan: false`) — что
// перемонтажу не с чего начать.
import { useQueryClient } from '@tanstack/react-query';
import { useId, useMemo, useState } from 'react';
import { Link } from 'react-router';

import { useAfterAction } from '@/api/batchActions';
import {
  EXCLUDE_MODES,
  parseSeconds,
  planBody,
  planRebuild,
  startRebuild,
  useBlocks,
  useRebuildModes,
  type BlockMoment,
  type RebuildMode,
  type RebuildPlan,
  type RebuildPlanIn,
  type RebuildResult,
} from '@/api/rebuild';
import { humanReason } from '@/api/humanText';
import { readableSlug, videoKeys, videoTitle, type Video, type VideoRefusal } from '@/api/videos';
import { useWrites } from '@/api/writes';
import { Card, CardHead } from '@/components/common/Card';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { confirmText } from '@/pages/batches/actions';
import { FlowNotes, Outcome, ReplanButton } from '@/pages/batches/ActionParts';
import { stageTitle } from '@/pages/batches/going';
import { isKnownStage, stageName } from '@/pages/batches/stages';
import { Refusal } from '@/pages/batches/parts';
import { useConfirmFlow } from '@/pages/batches/useConfirmFlow';
import { inputBase } from '@/pages/channels/styles';

import { refusalKind, refusalLine } from './refusal';
import { SkeletonRows } from '@/components/common/Skeletons';

const sec = (s: number) => `${String(Math.round(s * 10) / 10).replace('.', ',')} с`;
const windowText = (w: number[] | null | undefined) =>
  w && w.length === 2 ? `${sec(w[0]!).replace(' с', '')}–${sec(w[1]!)}` : null;

const KIND: Record<string, string> = {
  clip: 'видео',
  still: 'кадр-фото',
  sequence: 'серия кадров',
  split: 'сплит-экран',
  card: 'карточка',
  end_card: 'концовка',
};

/** Стадии фабрики → шаги экрана «Батчи» (Монтаж, Проверка кадров…), без повторов. */
function framesOf(ids: string[] | null | undefined): string {
  const out: string[] = [];
  for (const id of ids ?? []) {
    const t = stageTitle(id);
    if (out[out.length - 1] !== t) out.push(t);
  }
  return out.join(' → ') || '—';
}

/** Что выбрано: исключения из ответа фабрики минус снятые, плюс взятые соседние блоки. */
type Choice = { dropped: Set<string>; extra: Set<string> };

function chosen(top: string[], c: Choice): string[] {
  const out = top.filter((x) => !c.dropped.has(x));
  for (const x of c.extra) if (!out.includes(x)) out.push(x);
  return out;
}

function Moment({
  m,
  top,
  choice,
  canExclude,
  onToggle,
}: {
  m: BlockMoment;
  top: string[];
  choice: Choice;
  canExclude: boolean;
  onToggle: (exclude: string, on: boolean, fromTop: boolean) => void;
}) {
  const id = useId();
  const on = (x: string) =>
    top.includes(x) ? !choice.dropped.has(x) : choice.extra.has(x) && !choice.dropped.has(x);
  const kind = m.kind ? (KIND[m.kind] ?? m.kind) : null;
  return (
    <li
      data-testid="moment"
      data-at={m.at}
      data-block={m.block ?? ''}
      className="grid gap-1.5 rounded-sm border p-2.5 text-[13px]"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <b className="font-mono font-semibold">{sec(m.at)}</b>
        <span data-testid="moment-block">
          {m.block != null ? `блок ${m.block}` : m.ending ? 'концовка канала' : 'вне ролика'}
          {windowText(m.window) ? ` · ${windowText(m.window)}` : ''}
          {kind ? ` · ${kind}` : ''}
        </span>
        {m.ending ? <StatusBadge tone="idle">концовка</StatusBadge> : null}
      </div>
      {m.shots.length ? (
        <span className="font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {m.shots.join(' · ')}
        </span>
      ) : null}
      {m.exclude ? (
        <label htmlFor={`${id}-x`} className="flex items-start gap-2">
          <input
            id={`${id}-x`}
            type="checkbox"
            data-testid="moment-exclude"
            data-exclude={m.exclude}
            disabled={!canExclude}
            checked={canExclude && on(m.exclude)}
            onChange={(e) => onToggle(m.exclude!, e.target.checked, top.includes(m.exclude!))}
            className="mt-0.5"
          />
          <span>
            Убрать этот кадр{' '}
            <span className="font-mono text-xs text-muted-foreground">{m.exclude}</span>
          </span>
        </label>
      ) : (
        <p className="m-0 text-muted-foreground" data-testid="moment-note">
          Исключить нельзя{m.note ? `: ${m.note}` : '.'}
        </p>
      )}
      {m.near.map((n) =>
        n.exclude ? (
          <label
            key={n.block}
            htmlFor={`${id}-n${n.block}`}
            className="flex items-start gap-2 text-muted-foreground"
          >
            <input
              id={`${id}-n${n.block}`}
              type="checkbox"
              data-testid="moment-near"
              data-exclude={n.exclude}
              disabled={!canExclude}
              checked={canExclude && on(n.exclude)}
              onChange={(e) => onToggle(n.exclude!, e.target.checked, top.includes(n.exclude!))}
              className="mt-0.5"
            />
            <Tip content="Секунда у самой склейки: кадр, который вы имели в виду, может быть в соседнем блоке">
              <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
                И соседний блок {n.block}
              </span>
            </Tip>
            <span className="font-mono text-xs">{n.exclude}</span>
          </label>
        ) : (
          <p
            key={n.block}
            className="m-0 text-xs text-muted-foreground"
            data-testid="moment-near-no"
          >
            Соседний блок {n.block} исключить нельзя.
          </p>
        ),
      )}
    </li>
  );
}

const lowerFirst = (s: string) => (s ? s[0]!.toLowerCase() + s.slice(1) : s);
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Строка плана фабрики для основного вида: имена роликов — их названиями, стадии в «…» —
 * по-русски («video-editor» → «Монтаж»), без путей и кодов. Сама строка — под «подробнее».
 */
function planReasonText(reason: string, titles: Map<string, string>): string {
  let out = reason;
  for (const [slug, title] of titles)
    out = out.replace(
      new RegExp(`(^|[\\s«(])${escapeRe(slug)}(?=$|[\\s,.;:»)])`, 'g'),
      `$1«${title}»`,
    );
  out = out.replace(/««/g, '«').replace(/»»/g, '»');
  out = out.replace(/«([a-z][a-z0-9-]*)»/g, (m, id: string) =>
    isKnownStage(id) ? `«${stageName(id)}»` : m,
  );
  return humanReason(out);
}

function PlanView({
  plan,
  video,
  refusal,
}: {
  plan: RebuildPlan;
  /** Ролик панели (его название — в строках плана) и его отказ после монтажа (CC-0116). */
  video: Video;
  refusal: VideoRefusal | null;
}) {
  const videos = plan.videos ?? [];
  const slug = video.slug;
  const titleOf = (s: string | null | undefined, id: string) =>
    s === slug || id === video.script_id ? videoTitle(video) : readableSlug(s ?? id);
  // Ролик панели — всегда: в отказе плана (`videos: []`) фабрика называет его по имени.
  const titles = new Map([
    [slug, videoTitle(video)],
    ...videos.map((v) => [v.slug ?? v.script_id, titleOf(v.slug, v.script_id)] as const),
  ]);
  // «Можно пересобрать: <ролик> — <режим>, с шага «<стадия>»» говорят плашка и строка режима —
  // строка фабрики целиком уходит под «подробнее». Отказ — её словами, но для человека.
  return (
    <div className="grid gap-3 text-[13px]" data-testid="rebuild-plan">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={plan.ok ? 'ok' : 'danger'}>
          {plan.ok ? 'можно пересобрать' : 'пересобрать нельзя'}
        </StatusBadge>
        {!plan.ok ? (
          <span data-testid="rebuild-reason">{planReasonText(plan.reason, titles)}</span>
        ) : null}
      </div>
      {plan.title ? (
        <p className="m-0" data-testid="rebuild-mode">
          <b className="font-semibold">{plan.title}</b>
          {plan.from_stage ? ` — с шага «${stageName(plan.from_stage)}»` : ''}
        </p>
      ) : null}
      {plan.layout ? (
        <dl className="m-0 grid gap-1" data-testid="rebuild-layout">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Заново:</dt>
            <dd className="m-0" data-testid="layout-run">
              {framesOf(plan.layout.run)}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Берётся из батча:</dt>
            <dd className="m-0" data-testid="layout-copied">
              {framesOf(plan.layout.copied)}
            </dd>
          </div>
          {plan.layout.skipped.length ? (
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-muted-foreground">Пропускается:</dt>
              <dd className="m-0" data-testid="layout-skipped">
                {lowerFirst(framesOf(plan.layout.skipped))}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {videos.length ? (
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {videos.map((v) => (
            <li
              key={v.script_id}
              data-testid="rebuild-video"
              data-slug={v.slug ?? v.script_id}
              className="grid gap-0.5 rounded-sm border p-2"
            >
              <b className="font-semibold">{titleOf(v.slug, v.script_id)}</b>
              {v.refused ? (
                <span className="flex flex-wrap items-center gap-1.5" data-testid="plan-refused">
                  <StatusBadge tone="danger">отказан после монтажа</StatusBadge>
                  <span>
                    {refusal && v.slug === slug ? refusalLine(refusal) : refusalKind(v.refused)}
                  </span>
                </span>
              ) : null}
              <span data-testid="rebuild-video-exclude">
                {v.exclude?.length ? (
                  <>
                    Убрать кадры:{' '}
                    <span className="font-mono text-xs [overflow-wrap:anywhere]">
                      {v.exclude.join(', ')}
                    </span>
                  </>
                ) : (
                  'Без исключений кадров'
                )}
              </span>
              {v.note ? (
                <span className="text-muted-foreground" data-testid="rebuild-video-note">
                  {v.note}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {plan.notes ? (
        <p className="m-0" data-testid="rebuild-notes">
          Замечание: {plan.notes}
        </p>
      ) : null}
      <More className="mt-0">
        <span data-testid={plan.ok ? 'rebuild-reason' : 'rebuild-reason-raw'}>
          фабрика: {plan.reason}
        </span>
        {videos.map((v) => (
          <span key={`slug-${v.script_id}`}>
            ролик: {v.slug ?? '—'} (сценарий {v.script_id})
          </span>
        ))}
        <span>батч {plan.batch}</span>
        {plan.from_stage ? <span>с шага {plan.from_stage}</span> : null}
        {plan.layout ? <span>заново: {plan.layout.run.join(', ')}</span> : null}
        {plan.layout ? <span>копируются: {plan.layout.copied.join(', ')}</span> : null}
        {plan.layout?.skipped.length ? (
          <span>пропускаются: {plan.layout.skipped.join(', ')}</span>
        ) : null}
        {plan.copy?.length ? (
          <span data-testid="rebuild-copy">записи из батча: {plan.copy.join(', ')}</span>
        ) : null}
        {plan.only_videos?.length ? (
          <span>урезаются до выбранных роликов: {plan.only_videos.join(', ')}</span>
        ) : null}
        {plan.work?.length ? <span>work/: {plan.work.join(', ')}</span> : null}
        {videos
          .filter((v) => v.refused)
          .map((v) => (
            <span key={`refused-${v.script_id}`}>
              {v.slug ?? v.script_id}: отказан после монтажа ({v.refused})
            </span>
          ))}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </div>
  );
}

function Done({ r, onClose }: { r: RebuildResult; onClose: () => void }) {
  const batch = r.rebuild_id ? `rebuilds/${r.rebuild_id}` : null;
  if (r.ok && r.started)
    return (
      <Outcome tone="ok" title="Пересборка запущена" testId="rebuild-done" onClose={onClose}>
        <span data-testid="rebuild-done-reason">{r.reason}</span>
        {batch ? (
          <Link
            to="/batches"
            data-testid="rebuild-batch-link"
            data-batch={batch}
            className="w-max text-primary-text underline underline-offset-4"
          >
            Следить в «Батчах» →
          </Link>
        ) : null}
        <More className="mt-0">
          {batch ? <span>пересборка {batch}</span> : null}
          {r.rebuild_dir ? <span>каталог {r.rebuild_dir}</span> : null}
          {r.pid != null ? <span>исполнитель pid {r.pid}</span> : null}
          {r.log ? <span>журнал {r.log}</span> : null}
        </More>
      </Outcome>
    );
  return (
    <Outcome tone="warn" title="Пересборка не стартовала" testId="rebuild-failed" onClose={onClose}>
      <span data-testid="rebuild-failed-reason">{r.reason}</span>
      {batch && r.state ? (
        <>
          <span>
            Каталог пересборки уже есть, исполнитель не запустился. Её можно продолжить кнопкой
            «Продолжить…» в «Батчах».
          </span>
          <Link
            to="/batches"
            data-testid="rebuild-resume-link"
            data-batch={batch}
            className="w-max text-primary-text underline underline-offset-4"
          >
            Продолжить в «Батчах» →
          </Link>
        </>
      ) : null}
      <More className="mt-0">
        {batch ? <span>пересборка {batch}</span> : null}
        {r.state ? <span>состояние {r.state}</span> : null}
        {r.exit != null ? <span>код выхода {r.exit}</span> : null}
      </More>
    </Outcome>
  );
}

function ModePicker({
  modes,
  mode,
  onPick,
}: {
  modes: RebuildMode[];
  mode: string | null;
  onPick: (id: string) => void;
}) {
  return (
    <fieldset className="m-0 grid gap-1.5 border-0 p-0" data-testid="rebuild-modes">
      <legend className="mb-1 text-xs text-muted-foreground">Как пересобрать</legend>
      {modes.map((m) => (
        <label
          key={m.id}
          className={cn(
            'flex cursor-pointer items-start gap-2 rounded-sm border p-2 text-[13px]',
            mode === m.id && 'border-primary',
          )}
        >
          <input
            type="radio"
            name="rebuild-mode"
            value={m.id}
            data-testid="rebuild-mode-option"
            checked={mode === m.id}
            onChange={() => onPick(m.id)}
            className="mt-0.5"
          />
          <span className="grid gap-0.5">
            <span className="font-medium">{m.title}</span>
            {m.doc ? <span className="text-xs text-muted-foreground">{m.doc}</span> : null}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

export function RebuildPanel({
  batch,
  video,
  refusal = null,
  onClose,
}: {
  batch: string;
  video: Video;
  /** Ролик отказан после монтажа (CC-0116, `video.refused`). */
  refusal?: VideoRefusal | null;
  onClose: () => void;
}) {
  const slug = video.slug;
  const modes = useRebuildModes(batch, true);
  // Что о ролике знают режимы (CC-0116): отказан ли (ворота) и есть ли план монтажа.
  const source = modes.data?.videos?.find(
    (v) => v.slug === slug || (!!video.script_id && v.script_id === video.script_id),
  );
  const refusedGate = source?.refused ?? null;
  const writes = useWrites();
  const [picked, setPicked] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [secText, setSecText] = useState('');
  const [asked, setAsked] = useState<number[] | null>(null);
  const [secError, setSecError] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice>({ dropped: new Set(), extra: new Set() });
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<RebuildResult | null>(null);
  const blocks = useBlocks(batch, slug, asked);
  const qc = useQueryClient();
  const after = useAfterAction();
  const ids = { notes: useId(), secs: useId() };

  const list = modes.data?.modes ?? [];
  const mode = picked ?? list[0]?.id ?? null;
  const modeTitle = list.find((m) => m.id === mode)?.title ?? mode;
  const excluder = list.find((m) => EXCLUDE_MODES.has(m.id));
  const canExclude = !!mode && EXCLUDE_MODES.has(mode);
  const top = useMemo(() => blocks.data?.exclude ?? [], [blocks.data]);
  const exclude = canExclude ? chosen(top, choice) : [];

  const flow = useConfirmFlow({
    plan: (body: RebuildPlanIn) => planRebuild(batch, body),
    act: (confirm: string) => startRebuild(batch, confirm),
    onDone: (r: RebuildResult) => {
      setDone(r);
      setOpen(false);
    },
    onSettled: () => {
      after(batch);
      void qc.invalidateQueries({ queryKey: [...videoKeys.all, 'list'] });
    },
  });

  const ask = () => {
    const p = parseSeconds(secText);
    if ('error' in p) {
      setSecError(p.error);
      return;
    }
    setSecError(null);
    setChoice({ dropped: new Set(), extra: new Set() });
    setAsked(p.at);
  };

  const toggle = (x: string, on: boolean, fromTop: boolean) =>
    setChoice((c) => {
      const dropped = new Set(c.dropped);
      const extra = new Set(c.extra);
      if (on) {
        dropped.delete(x);
        if (!fromTop) extra.add(x);
      } else {
        if (fromTop) dropped.add(x);
        extra.delete(x);
      }
      return { dropped, extra };
    });

  const body = mode
    ? planBody({ slug, mode, text, exclude, seconds: asked && blocks.data ? asked : [] })
    : null;

  return (
    <Card aria-labelledby="rebuild-title" data-testid="rebuild" className="max-sm:p-3">
      <CardHead
        eyebrow="Пересборка"
        title="Пересобрать ролик"
        titleId="rebuild-title"
        actions={
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="rebuild-close">
            Скрыть
          </Button>
        }
      />
      <div className="grid gap-4 text-[13px]">
        {refusal || refusedGate ? (
          <div
            data-testid="rebuild-refused"
            className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-2.5"
          >
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge tone="danger">исходный ролик отказан</StatusBadge>
              <span className="font-medium" data-testid="rebuild-refused-reason">
                {refusal ? refusalLine(refusal) : refusalKind(refusedGate)}
              </span>
            </span>
            <span className="text-muted-foreground">
              Фабрика отклонила его после монтажа. Пересборка соберёт ролик заново — вердикт дадите
              новой версии.
            </span>
            {source && source.plan === false ? (
              <span className="text-warning" data-testid="rebuild-no-plan">
                Плана монтажа у ролика нет — перемонтажу не с чего начать, нужен новый сценарий.
              </span>
            ) : null}
          </div>
        ) : null}
        {modes.isPending ? (
          <SkeletonRows rows={3} height={44} label="Читаю режимы пересборки…" />
        ) : modes.isError ? (
          <Refusal error={modes.error} title="Режимы пересборки не прочитать" />
        ) : !list.length ? (
          <p className="m-0 text-muted-foreground" data-testid="rebuild-no-modes">
            {modes.data.reason ?? 'В плане канала нет режимов пересборки.'}
          </p>
        ) : (
          <ModePicker
            modes={list}
            mode={mode}
            onPick={(id) => {
              setPicked(id);
              flow.reset();
            }}
          />
        )}

        <label htmlFor={ids.notes} className="grid gap-1">
          <span className="text-xs text-muted-foreground">Замечания</span>
          <textarea
            id={ids.notes}
            data-testid="rebuild-text"
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Что не так и что поменять — словами"
            className={cn(inputBase, 'h-auto min-h-16 py-2')}
          />
        </label>

        <div className="grid gap-2">
          <label htmlFor={ids.secs} className="grid gap-1">
            <span className="text-xs text-muted-foreground">Секунды ролика, где что-то не так</span>
            <span className="flex flex-wrap gap-2">
              <input
                id={ids.secs}
                data-testid="rebuild-seconds"
                inputMode="decimal"
                value={secText}
                onChange={(e) => setSecText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    ask();
                  }
                }}
                placeholder="12 18 24"
                aria-invalid={secError ? true : undefined}
                className={cn(inputBase, 'w-auto min-w-0 flex-1')}
              />
              <Button size="sm" variant="outline" onClick={ask} data-testid="rebuild-find">
                Что там на экране
              </Button>
            </span>
          </label>
          {secError ? (
            <p role="alert" className="m-0 text-danger" data-testid="seconds-error">
              {secError}
            </p>
          ) : null}
          {blocks.isFetching ? (
            <p role="status" className="m-0 animate-pulse text-muted-foreground">
              Ищу кадры в раскадровке…
            </p>
          ) : blocks.isError ? (
            <Refusal error={blocks.error} title="Секунды не перевести в кадры" />
          ) : blocks.data && !blocks.data.ok ? (
            <p className="m-0 text-warning" data-testid="blocks-reason">
              {blocks.data.reason}
            </p>
          ) : null}
          {blocks.data?.moments.length ? (
            <>
              {!canExclude ? (
                <p
                  className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] p-2 text-muted-foreground"
                  data-testid="no-exclude"
                >
                  Убирать кадры можно только в режиме «{excluder?.title ?? 'перемонтаж'}»: «
                  {modeTitle}» пишет сценарий заново — кадров этого монтажа в нём не будет. Секунды
                  уйдут замечанием.
                </p>
              ) : null}
              <ul className="m-0 grid list-none gap-2 p-0" data-testid="moments">
                {blocks.data.moments.map((m, i) => (
                  <Moment
                    key={`${m.at}-${i}`}
                    m={m}
                    top={top}
                    choice={choice}
                    canExclude={canExclude}
                    onToggle={toggle}
                  />
                ))}
              </ul>
            </>
          ) : null}
        </div>

        <p className="m-0" data-testid="rebuild-summary">
          {canExclude && exclude.length ? (
            <>
              Уберём кадры:{' '}
              <span className="font-mono text-xs [overflow-wrap:anywhere]">
                {exclude.join(', ')}
              </span>
            </>
          ) : (
            'Без исключений кадров.'
          )}
        </p>

        {!writes.allowed ? (
          <p className="m-0 text-xs text-muted-foreground" data-testid="rebuild-readonly">
            Только смотреть: подготовить можно, а план и пересборку фабрика даёт только на рабочей
            копии.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <ConfirmDialog
            open={open}
            onOpenChange={(v) => {
              setOpen(v);
              if (v && body) {
                setDone(null);
                flow.start(body);
              } else flow.reset();
            }}
            tip="Фабрика проверит пересборку и покажет план; запуск — после вашего «да»"
            trigger={
              <Button size="sm" data-testid="rebuild-open" disabled={!body}>
                Проверить и пересобрать…
              </Button>
            }
            title={`Пересобрать «${videoTitle(video)}»?`}
            description="Фабрика проверила, что будет сделано. Пересборка откроет новый батч; исходный ролик и его приёмка не меняются."
            confirmLabel={confirmText('Пересобрать', flow)}
            pendingLabel="Запускаю…"
            pending={flow.acting}
            confirmDisabled={!flow.canConfirm}
            confirmTestId="rebuild-confirm"
            onConfirm={() => void flow.confirm()}
            extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
          >
            {flow.plan ? <PlanView plan={flow.plan} video={video} refusal={refusal} /> : null}
            <FlowNotes
              flow={flow}
              busyTitle="Идёт запуск или другая пересборка"
              timeoutText="Фабрика не ответила за 30 секунд. Посмотрите «Батчи» — пересборка могла открыться."
            />
          </ConfirmDialog>
        </div>
        {done ? <Done r={done} onClose={() => setDone(null)} /> : null}
      </div>
    </Card>
  );
}
