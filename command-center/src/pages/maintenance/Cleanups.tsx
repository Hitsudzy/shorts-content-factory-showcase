// «Уборки и архивы» (CC-0033; записи — CC-0104, CC-0105, CC-0117): пул футажа, журналы батчей и
// месячный архив. Каждая запись — план фабрики с токеном (ничего не тронуто) и ваше «да»: поле
// пустое, «да» набираете вы, кнопка подтверждения включается только после него. Пока идёт батч —
// фабрика токена не даёт (план говорит почему), «да» по старому токену — отказ `batch_open`.
// Видео-id, пути, команды и строки фабрики — под «Подробнее».
import { useState, type ReactNode } from 'react';

import { humanDashes } from '@/api/humanText';
import {
  cleanJournals,
  maintenanceProblemText,
  planArchive,
  planJournals,
  planPoolRelease,
  releasePool,
  runArchive,
  STALE_DAYS,
  useAfterMaintenance,
  useArchive,
  useMaintenance,
  usePool,
  type ArchiveDryRun,
  type ArchivePlan,
  type ArchiveResult,
  type JournalsPlan,
  type JournalsResult,
  type PoolReleasePlan,
  type PoolReleaseResult,
  type PoolSource,
  type PoolView,
} from '@/api/maintenance';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { Pending, SkeletonText } from '@/components/common/Skeletons';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Skeleton } from '@/components/ui/skeleton';
import { useChannelNames, useChannelText } from '@/pages/batches/names';
import { Check, Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';
import { Loaded } from '@/components/common/Loaded';

import {
  batchText,
  bytesText,
  filesWord,
  journalBatch,
  journalsWord,
  keepWhy,
  linesWord,
  monthText,
  saidYes,
  sourcesWord,
  topicStatus,
  variantText,
} from './format';
import { Tile, YesField } from './parts';

/**
 * Поле «да» окна записи: пустое при открытии и после каждого нового плана (переплан после
 * устаревшего подтверждения тоже) — «да» относится к плану, который вы прочитали.
 */
function useYes() {
  const [yes, setYes] = useState('');
  const reset = () => setYes('');
  return {
    yes,
    setYes,
    ready: saidYes(yes),
    reset,
    fresh: <P,>(plan: Promise<P>) =>
      plan.then((p) => {
        reset();
        return p;
      }),
  };
}

function Going({ batches, testId }: { batches: string[]; testId: string }) {
  const name = useChannelNames();
  if (!batches.length) return null;
  return (
    <p
      role="status"
      data-testid={testId}
      className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] px-3 py-2 text-[13px]"
    >
      <b className="font-semibold">Идёт батч</b> —{' '}
      {batches.map((b) => batchText(b, name)).join(', ')}. Уборки ждут, пока он закончится.
    </p>
  );
}

const Who = () => (
  <p className="m-0 text-xs text-muted-foreground">
    Делаете вы, из центра — так фабрика и запишет в свой журнал.
  </p>
);

// ---------------------------------------------------------------- пул футажа
/** Строка фабрики экраном: каналы именами, « - » — тире (CC-0131: «Открыт батч (…) — запись подождёт»). */
function useFactoryText() {
  const say = useChannelText();
  return (text: string) => humanDashes(say(text));
}

const POOL_TIPS = {
  pool: 'Весь футаж, скачанный под темы батчей',
  release: 'Источники, все темы которых закончены: ролик опубликован или снят',
  keep: 'Источники, на которые ссылается живая тема — ролик ещё ждёт публикации или решения',
  orphan: 'Ни один батч на диске на них не ссылается — уборка пула их не трогает',
  stale: `Тема без ролика из батча старше ${STALE_DAYS} дней считается законченной — так же решает месячный архив`,
  variants:
    'Сколько освободило бы ещё одно правило — только цифры. Правилом вариант станет только по вашему слову',
};

function Source({ s }: { s: PoolSource }) {
  const name = useChannelNames();
  const topics = Object.values(s.topics ?? {});
  const batch = s.newest_batch;
  return (
    <li className="grid gap-0.5 border-t py-1.5 first:border-t-0" data-testid="pool-source">
      <span className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span>
          {topics.length
            ? [
                ...new Set(
                  topics.map((t) => (t.stale ? 'тема без ролика, давняя' : topicStatus(t.status))),
                ),
              ].join(', ')
            : 'источник'}
        </span>
        <span className="tabular-nums">{bytesText(s.bytes)}</span>
      </span>
      {batch ? (
        <span className="text-xs text-muted-foreground">{batchText(batch, name)}</span>
      ) : null}
    </li>
  );
}

function PoolPlanView({
  plan,
  yes,
  setYes,
}: {
  plan: PoolReleasePlan;
  yes: string;
  setYes: (v: string) => void;
}) {
  const say = useFactoryText();
  return (
    <>
      <PlanHead
        plan={{ ...plan, why: plan.why && say(plan.why) }}
        yes="можно освободить"
        no="освобождать нельзя"
      />
      {plan.ok ? (
        <>
          <p className="m-0" data-testid="pool-plan-total">
            Уйдёт {sourcesWord(plan.totals.sources)} — {bytesText(plan.totals.bytes)}. Останутся:
            живые темы — {sourcesWord(plan.kept.sources)}, без хозяина —{' '}
            {sourcesWord(plan.orphan.sources)}.
          </p>
          <ul className="m-0 grid list-none p-0 text-[13px]" data-testid="pool-plan-sources">
            {plan.release.map((s) => (
              <Source key={s.video_id} s={s} />
            ))}
          </ul>
          <p
            className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] px-3 py-2"
            data-testid="pool-irreversible"
          >
            <b className="font-semibold">Вернуть нельзя:</b> файлы футажа удалятся с диска;
            понадобятся снова — фабрика скачает их заново.
          </p>
          <Who />
          <YesField value={yes} onChange={setYes} testId="pool-yes" what="Освободить пул?" />
        </>
      ) : null}
      <More className="mt-0">
        <span>{plan.command}</span>
        <span>
          {plan.action} · by {plan.by} · via {plan.via} · журнал {plan.journal}
        </span>
        {plan.release.map((s) => (
          <span key={s.video_id}>
            {s.video_id} · {s.files.join(', ')}
          </span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function PoolDone({ r, onClose }: { r: PoolReleaseResult; onClose: () => void }) {
  return (
    <Done tone="ok" testId="pool-done" title="Пул освобождён" onClose={onClose}>
      <span data-testid="pool-done-total">
        Удалено {sourcesWord(r.deleted.length)} — {bytesText(r.totals.bytes)}. Фабрика записала в
        журнал освобождений: вы, из центра.
      </span>
      <More className="mt-0">
        <span>{r.deleted.join(', ')}</span>
        <span>журнал {r.journal}</span>
      </More>
    </Done>
  );
}

function PoolBody({
  p,
  staleDays,
  onDone,
}: {
  p: PoolView;
  staleDays: number | null;
  onDone: (r: PoolReleaseResult) => void;
}) {
  const say = useFactoryText();
  const after = useAfterMaintenance();
  const y = useYes();
  const keepWhyRows = new Map<string, number>();
  for (const s of p.keep)
    for (const b of s.blocked_by ?? []) keepWhyRows.set(b, (keepWhyRows.get(b) ?? 0) + 1);
  const variants = p.variants.filter((v) => v.sources > 0);
  const why = p.open_batches.length
    ? 'Идёт батч — освобождать пул можно, когда он закончится'
    : p.totals.release.sources
      ? null
      : 'Освобождать нечего — законченных тем в пуле нет';
  return (
    <div className="grid gap-3" data-testid="pool-view">
      <Going batches={p.open_batches} testId="pool-going" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile
          label="Весь пул"
          value={bytesText(p.pool.bytes)}
          sub={sourcesWord(p.pool.sources)}
          tip={POOL_TIPS.pool}
        />
        <Tile
          label="Освободит уборка"
          value={bytesText(p.totals.release.bytes)}
          sub={sourcesWord(p.totals.release.sources)}
          tip={POOL_TIPS.release}
          tone={p.totals.release.sources ? 'ok' : undefined}
          testId="pool-release"
        />
        <Tile
          label="Держат живые темы"
          value={bytesText(p.totals.keep.bytes)}
          sub={sourcesWord(p.totals.keep.sources)}
          tip={POOL_TIPS.keep}
        />
        <Tile
          label="Без хозяина"
          value={bytesText(p.totals.orphan.bytes)}
          sub={sourcesWord(p.totals.orphan.sources)}
          tip={POOL_TIPS.orphan}
        />
      </div>
      {keepWhyRows.size ? (
        <ul className="m-0 grid list-none gap-0.5 p-0 text-[13px]" data-testid="pool-keep-why">
          {[...keepWhyRows].map(([code, n]) => (
            <li key={code}>
              <span className="text-muted-foreground">Остаются:</span> {sourcesWord(n)} —{' '}
              {keepWhy(code)}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <WriteAction
          id="pool-release"
          label="Освободить пул…"
          title="Освободить пул футажа?"
          description="Фабрика составила план — ничего ещё не удалено. Удалит после вашего «да»."
          body={{ staleDays }}
          why={why}
          tip="Фабрика покажет, какой футаж уйдёт; удалит — после вашего «да»"
          confirmLabel="Освободить"
          pendingLabel="Освобождаю…"
          danger
          ready={y.ready}
          onOpen={y.reset}
          plan={(b) => y.fresh(planPoolRelease(b.staleDays))}
          act={releasePool}
          view={(plan) => <PoolPlanView plan={plan} yes={y.yes} setYes={y.setYes} />}
          problemText={maintenanceProblemText}
          problemSay={say}
          onSettled={after}
          onDone={(r) => {
            y.reset();
            onDone(r);
          }}
        />
      </div>
      {variants.length ? (
        <details className="text-[13px]" data-testid="pool-variants">
          <summary className="w-max cursor-pointer text-primary-text">
            <Tip content={POOL_TIPS.variants} wide>
              <span tabIndex={0}>Что освободило бы ещё одно правило</span>
            </Tip>
          </summary>
          <ul className="mt-1.5 grid list-none gap-0.5 p-0">
            {variants.map((v) => (
              <li key={v.rule} className="flex flex-wrap justify-between gap-x-3">
                <span>{variantText(v.rule)}</span>
                <span className="text-muted-foreground tabular-nums">
                  {sourcesWord(v.sources)} · {bytesText(v.bytes)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <More className="mt-0">
        <span>{p.command}</span>
        <span>
          план на {p.at} · журнал {p.journal}
        </span>
        {p.variants.map((v) => (
          <span key={v.rule}>
            {v.rule}: {v.sources} · {v.bytes}
          </span>
        ))}
        {p.unresolved.map((u) => (
          <span key={u.entry}>
            не найден батч: {u.kind} · {u.entry}
          </span>
        ))}
      </More>
    </div>
  );
}

const PoolSkeleton = () => (
  <Pending label="Фабрика считает пул…" className="gap-3">
    <span className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-[74px] rounded-sm" />
      ))}
    </span>
    <SkeletonText bare lines={2} />
    <Skeleton className="h-8 w-36 rounded-sm" />
  </Pending>
);

export function PoolCard() {
  const [stale, setStale] = useState(false);
  const staleDays = stale ? STALE_DAYS : null;
  const q = usePool(staleDays);
  const [done, setDone] = useState<PoolReleaseResult | null>(null);
  return (
    <Card aria-labelledby="pool-title" data-testid="pool">
      <CardHead eyebrow="Футаж под темы батчей" title="Пул футажа" titleId="pool-title" />
      <div className="mb-3">
        <Check
          label={`Темы без ролика старше ${STALE_DAYS} дней — законченные`}
          checked={stale}
          onChange={setStale}
          testId="pool-stale"
          tip={POOL_TIPS.stale}
        />
      </div>
      <Loaded
        q={q}
        reading="Фабрика считает пул…"
        failed="Пул не прочитан"
        skeleton={<PoolSkeleton />}
      >
        {(p) => <PoolBody p={p} staleDays={staleDays} onDone={setDone} />}
      </Loaded>
      {done ? (
        <div className="mt-3">
          <PoolDone r={done} onClose={() => setDone(null)} />
        </div>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------- журналы батчей
function JournalsPlanView({
  plan,
  yes,
  setYes,
}: {
  plan: JournalsPlan;
  yes: string;
  setYes: (v: string) => void;
}) {
  const say = useFactoryText();
  const name = useChannelNames();
  const t = plan.totals;
  return (
    <>
      <PlanHead
        plan={{ ...plan, why: plan.why && say(plan.why) }}
        yes="можно почистить"
        no="чистить нельзя"
      />
      {plan.ok ? (
        <>
          <p className="m-0" data-testid="journals-plan-total">
            К уборке — {journalsWord(t.journals)}.
            {t.cut_journals ? ` Чужих строк уйдёт: ${linesWord(t.cut_lines)}.` : ''}
            {t.whole ? ` Целиком удалится: ${journalsWord(t.whole)}.` : ''}
          </p>
          <ul className="m-0 grid list-none p-0 text-[13px]" data-testid="journals-plan-rows">
            {plan.journals.map((r) => {
              const b = journalBatch(r.rel);
              return (
                <li key={r.rel} className="grid gap-0.5 border-t py-1.5 first:border-t-0">
                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span>{b ? batchText(b, name) : 'журнал'}</span>
                    <span className="tabular-nums">−{bytesText(r.drop_bytes)}</span>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {r.mode === 'whole'
                      ? 'удалится целиком — его учёт уже лежит в копии'
                      : `уйдёт ${linesWord(r.drop)} из ${r.lines.toLocaleString('ru-RU')}, останется ${r.after.toLocaleString('ru-RU')}`}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="m-0 text-xs text-muted-foreground">
            Перед уборкой фабрика сохранит копию оригиналов и сверит учёт; не сойдётся — вернёт как
            было.
          </p>
          <Who />
          <YesField value={yes} onChange={setYes} testId="journals-yes" what="Почистить журналы?" />
        </>
      ) : null}
      <More className="mt-0">
        <span>{plan.command}</span>
        <span>
          {plan.action} · by {plan.by} · via {plan.via} · журнал уборки {plan.log}
        </span>
        {plan.journals.map((r) => (
          <span key={r.rel}>
            {r.rel} · {r.mode} · {r.lines} → {r.after} · sha {r.sha.slice(0, 12)}
          </span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function JournalsDone({ r, onClose }: { r: JournalsResult; onClose: () => void }) {
  return (
    <Done tone="ok" testId="journals-done" title="Журналы почищены" onClose={onClose}>
      <span data-testid="journals-done-total">
        Почищено: {journalsWord(r.done.length)}. Копия оригиналов сохранена, учёт сверен.
      </span>
      <More className="mt-0">
        {r.backup ? <span>копия: {r.backup}</span> : null}
        <span>журнал уборки {r.log}</span>
        {r.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </More>
    </Done>
  );
}

export function JournalsCard() {
  const say = useFactoryText();
  const after = useAfterMaintenance();
  const y = useYes();
  const [done, setDone] = useState<JournalsResult | null>(null);
  return (
    <Card aria-labelledby="journals-title" data-testid="journals">
      <CardHead eyebrow="Журналы событий батчей" title="Уборка журналов" titleId="journals-title" />
      <div className="grid gap-3 text-[13px]">
        <p className="m-0">
          В журналы батчей попадают строки чужих батчей. Уборка вырезает их, а журнал, чей учёт уже
          лежит в копии, удаляет целиком. Что именно — фабрика покажет в плане.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <WriteAction
            id="journals"
            label="Почистить журналы…"
            title="Почистить журналы батчей?"
            description="Фабрика составила план — ничего ещё не тронуто. Почистит после вашего «да»."
            body={{}}
            tip="Фабрика покажет, какие строки уйдут; почистит — после вашего «да»"
            confirmLabel="Почистить"
            pendingLabel="Чищу…"
            danger
            ready={y.ready}
            onOpen={y.reset}
            plan={() => y.fresh(planJournals())}
            act={cleanJournals}
            view={(plan) => <JournalsPlanView plan={plan} yes={y.yes} setYes={y.setYes} />}
            problemText={maintenanceProblemText}
            problemSay={say}
            onSettled={after}
            onDone={(r) => {
              y.reset();
              setDone(r);
            }}
          />
        </div>
        {done ? <JournalsDone r={done} onClose={() => setDone(null)} /> : null}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- месячный архив
function Space({ plan }: { plan: ArchivePlan }) {
  if (plan.need_bytes == null) return null;
  return (
    <p className="m-0" data-testid="archive-space">
      Нужно {bytesText(plan.need_bytes)} на диске {plan.volume ?? 'архива'}
      {plan.free_bytes != null ? `, свободно ${bytesText(plan.free_bytes)}` : ''}
      {plan.enough_space === false ? ' — не хватает места' : ''}.
    </p>
  );
}

function ArchivePlanView({
  plan,
  yes,
  setYes,
}: {
  plan: ArchivePlan;
  yes: string;
  setYes: (v: string) => void;
}) {
  const say = useFactoryText();
  const name = useChannelNames();
  return (
    <>
      <PlanHead
        plan={{ ...plan, why: plan.why && say(plan.why) }}
        yes="можно архивировать"
        no="архивировать нельзя"
      />
      {plan.jobs.length ? (
        <ul className="m-0 grid list-none p-0 text-[13px]" data-testid="archive-plan-jobs">
          {plan.jobs.map((j) => (
            <li
              key={`${j.channel}/${j.month}`}
              className="grid gap-0.5 border-t py-1.5 first:border-t-0"
            >
              <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span>
                  <b className="font-semibold">{name(j.channel)}</b> · {monthText(j.month)}
                </span>
                <span className="tabular-nums">{bytesText(j.bytes)}</span>
              </span>
              <span className="text-xs text-muted-foreground">
                {filesWord(j.from_publish.length)} за {j.day_dirs.length} дн. →{' '}
                {j.action === 'extend'
                  ? 'допишутся в архив месяца'
                  : j.action === 'create'
                    ? 'новый архив месяца'
                    : 'диск не подключён'}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <Space plan={plan} />
      {plan.ok ? (
        <>
          <p className="m-0 text-xs text-muted-foreground">
            Фабрика запишет архив на диск, прочитает его обратно и только потом уберёт месяц из
            папки публикаций — одним коммитом. Это может занять до часа.
          </p>
          <Who />
          <YesField value={yes} onChange={setYes} testId="archive-yes" what="Архивировать месяц?" />
        </>
      ) : null}
      <More className="mt-0">
        <span>{plan.apply_command}</span>
        <span>
          {plan.action} · by {plan.by} · via {plan.via} · сегодня {plan.today ?? '—'}
        </span>
        {plan.jobs.map((j) => (
          <span key={j.zip}>
            {j.zip} · {j.action ?? '—'} · {j.old_members} → {j.members}
          </span>
        ))}
        {plan.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function ArchiveDone({ r, onClose }: { r: ArchiveResult; onClose: () => void }) {
  const name = useChannelNames();
  const moved = r.jobs.filter((j) => j.status === 'moved');
  const failed = r.jobs.filter((j) => j.status === 'failed');
  return (
    <Done
      tone={failed.length ? 'warn' : 'ok'}
      testId="archive-done"
      title={failed.length ? 'Архив — не всё перенесено' : 'Месяц в архиве'}
      onClose={onClose}
    >
      <ul className="m-0 grid list-none gap-0.5 p-0" data-testid="archive-done-jobs">
        {r.jobs.map((j) => (
          <li key={j.zip}>
            {name(j.channel)} · {monthText(j.month)} —{' '}
            {j.status === 'moved' ? 'перенесён' : 'не перенесён'}
          </li>
        ))}
      </ul>
      <span data-testid="archive-done-commit">
        {r.committed
          ? 'Коммит сделан: вы, из центра.'
          : 'Коммит отложен — фабрика сделает его, когда закончится батч.'}{' '}
        {moved.length ? `Перенесено: ${moved.length}.` : ''}
      </span>
      <More className="mt-0">
        <span>{r.command}</span>
        {r.commit ? <span>коммит: {JSON.stringify(r.commit)}</span> : null}
        {r.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </More>
    </Done>
  );
}

function ArchiveStatus({ a }: { a: ArchiveDryRun }) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="archive-status">
      <StatusBadge
        tone={a.ok ? 'ok' : 'warn'}
        tip={a.ok ? 'Сухой прогон фабрики прошёл: ничего не тронуто' : 'Сухой прогон не прошёл'}
      >
        {a.ok ? 'проверка прошла' : 'проверка не прошла'}
      </StatusBadge>
      <span className="text-[13px]">
        Диск архива: <b className="font-semibold">{a.volume ?? '—'}</b>
        {a.error ? <span className="text-warning"> — {a.error}</span> : null}
      </span>
    </div>
  );
}

function ArchiveBody({ a, onDone }: { a: ArchiveDryRun; onDone: (r: ArchiveResult) => void }) {
  const say = useFactoryText();
  const after = useAfterMaintenance();
  const y = useYes();
  return (
    <div className="grid gap-3" data-testid="archive-view">
      <ArchiveStatus a={a} />
      <div className="flex flex-wrap items-center gap-2">
        <WriteAction
          id="archive"
          label="Архивировать месяц…"
          title="Архивировать прошлый месяц?"
          description="Фабрика проверила сухим прогоном — ничего не тронуто. Перенесёт после вашего «да»."
          body={{}}
          why={a.confirm_available ? null : 'Фабрика не архивирует этот шаг из центра'}
          tip="Фабрика покажет, какие месяцы и сколько места; перенесёт — после вашего «да»"
          confirmLabel="Архивировать"
          pendingLabel="Архивирую…"
          ready={y.ready}
          onOpen={y.reset}
          plan={() => y.fresh(planArchive())}
          act={(c) => runArchive(c)}
          view={(plan) => <ArchivePlanView plan={plan} yes={y.yes} setYes={y.setYes} />}
          waiting={
            <span data-testid="archive-waiting">
              Фабрика пишет архив на диск и сверяет его — это может занять до часа. Окно ждёт
              ответа; второй раз архив не начнётся.
            </span>
          }
          problemText={maintenanceProblemText}
          problemSay={say}
          onSettled={after}
          onDone={(r) => {
            y.reset();
            onDone(r);
          }}
        />
      </div>
      <More className="mt-0">
        <span>{a.command}</span>
        <span>
          exit {a.exit_code ?? '—'} · confirm_available {String(a.confirm_available)}
        </span>
        {a.lines.map((l, i) => (
          <span key={i} className="whitespace-pre-wrap">
            {l}
          </span>
        ))}
        {a.stderr ? <span>{a.stderr}</span> : null}
      </More>
    </div>
  );
}

export function ArchiveCard() {
  const q = useArchive();
  const [done, setDone] = useState<ArchiveResult | null>(null);
  return (
    <Card aria-labelledby="archive-title" data-testid="archive">
      <CardHead eyebrow="Архив публикаций" title="Месячный архив" titleId="archive-title" />
      <div className="grid gap-3 text-[13px]">
        <p className="m-0">
          Прошлые месяцы уходят из папки публикаций в архив на внешнем диске. Остальные шаги
          месячной уборки (пул, старые батчи, временные файлы) фабрика из центра не запускает.
        </p>
        <Loaded
          q={q}
          reading="Фабрика проверяет архив сухим прогоном…"
          failed="Проверка архива не прочитана"
          skeleton={
            <Pending label="Фабрика проверяет архив сухим прогоном…" className="gap-3">
              <SkeletonText bare lines={1} />
              <Skeleton className="h-8 w-44 rounded-sm" />
            </Pending>
          }
        >
          {(a) => <ArchiveBody a={a} onDone={setDone} />}
        </Loaded>
        {done ? <ArchiveDone r={done} onClose={() => setDone(null)} /> : null}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- чего нет в центре
const SCRIPT_NAME: Record<string, string> = {
  'scripts/cleanup_tmpdir.sh': 'Чистка временных файлов машины',
  'scripts/cleanup_1_6_archive.sh': 'Разовый перенос архива',
};

export function NotHere() {
  const q = useMaintenance();
  if (!q.data) return null;
  const off = q.data.scripts.filter((s) => s.exposed === 'none');
  if (!off.length) return null;
  const items: ReactNode[] = off.map((s) => (
    <li key={s.script}>{SCRIPT_NAME[s.script] ?? 'Ещё одна уборка'}</li>
  ));
  return (
    <div className="text-[13px] text-muted-foreground" data-testid="maintenance-not-here">
      <Tip
        wide
        content="Эти уборки фабрика делает только сама: они чистят не дерево фабрики или не умеют сухой прогон. Почему — под «Подробнее»"
      >
        <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
          Только на самой фабрике:
        </span>
      </Tip>
      <ul className="mt-1 mb-0 grid list-disc gap-0.5 pl-5">{items}</ul>
      <More className="mt-1">
        {off.map((s) => (
          <span key={s.script}>
            {s.script}: {s.why}
          </span>
        ))}
      </More>
    </div>
  );
}
