// Копилка канала (CC-0122): принятые ролики, которым ещё не дали слот (`publish/<канал>/_queue/`),
// — над лентой слотов. У каждого — превью, название и ссылка на экран «Ролики», батч, когда
// принят, возраст с пометкой «устарел» (CF-0746: старше 14 дней от даты новости, у вечнозелёных
// — от принятия; только пометка), готова ли карточка (почему нет — словами фабрики) и холд.
// Пачкой: отметить ролики, выставить порядок (↑/↓, по умолчанию — по дате принятия) → «Разложить
// по слотам…» → план фабрики (какой ролик в какой день, отказы по ролику, пометки) → одно «да».
// Принятые, но не легшие в копилку (`not_queued`) — со словами фабрики и «Доложить в копилку…».
// Коды отказов и строки фабрики — под «подробнее».
// CC-0180 (политика ленты 04.11, фабрика CF-0918/CF-0919): новостные и бессрочные — отдельно,
// запас (снятые из ленты), горизонт; у новости — `news_why` как есть и когда устареет. «Разложить
// автоматически» — план фабрики: порядок, что ждёт и почему, одно «да»; `force` — под «подробнее».
// CC-0183 (CF-0920): в копилке бывает два ролика одного имени из разных батчей. Строка — батч плюс
// имя (`stashKeyOf`: ключи, отметки, порядок, правки); рядом с именем батч — только у тёзок.
// CC-0187 (фабрика CC-0186, CF-0921): «Не положены: похоже на другую версию» (`other_version`) —
// только чтение: название, батч, причина словами, ссылка на уже размещённую версию. Решает драйвер
// фабрики (пользователь: имена и версии — не его уровень); команда `repair` — под «Подробнее».
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { BatchError } from '@/api/batchProblem';
import { isAhead, useQueue, type ChannelQueue } from '@/api/publish';
import {
  planStashAuto,
  planStashPlace,
  planStashRepair,
  stashPlace,
  stashProblemText,
  stashRepair,
  useStash,
  type PublishStash,
  type StashHorizon,
  type StashPlacePlan,
  type StashPlaceResult,
  type StashRepairPlan,
  type StashOtherVersion,
  type StashRepairResult,
  type StashVideo,
} from '@/api/stash';
import { readableSlug, useVideos } from '@/api/videos';
import { Card, CardHead, Keep } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { plural, videosWord } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { ScoreBadge } from '@/pages/videos/Score';

import { mskDay, slotDay } from './format';
import {
  acceptedAgo,
  ageOf,
  entryParts,
  otherVersionSlot,
  otherVersionWhy,
  inReserve,
  kindMarkLabel,
  mergeOrder,
  move,
  namesakeMark,
  namesakesOf,
  newsStale,
  placeable,
  skipReasonText,
  slotWhen,
  batchFrom,
  stashBatch,
  withoutPath,
  stashKeyOf,
  stashTitle,
  stashTitles,
  videoHref,
  withMark,
  withoutBatchTail,
  type NameOf,
} from './stashWords';
import { CardActions, CardStateBadge } from './CardState';
import { reasonsText } from './cardWords';
import { MoveDone, ReturnFromReserve, StudioHand, type MoveDoneState } from './MoveWrites';
import { daysAhead, placedOf } from './moveWords';
import { headWhy, lineWords, ownRefusals } from './serverLines';
import { isStudioLine } from '@/api/publishMove';
import { Done, PlanHead, WriteAction } from './Writes';
import { SkeletonRows } from '@/components/common/Skeletons';

/** Превью 9:16; картинки нет или не загрузилась — тихая плашка. */
function Thumb({ url }: { url: string | null | undefined }) {
  const [broken, setBroken] = useState(false);
  return (
    <span
      aria-hidden
      className="relative block h-[78px] w-[44px] shrink-0 overflow-hidden rounded-sm border bg-[linear-gradient(160deg,var(--muted),var(--card))]"
    >
      {url && !broken ? (
        <img
          src={url}
          alt=""
          loading="lazy"
          data-testid="stash-thumb"
          onError={() => setBroken(true)}
          className="absolute inset-0 size-full object-cover object-left-top"
        />
      ) : null}
    </span>
  );
}

/**
 * CC-0125: оценка ролика копилки — из списка роликов его батча (один запрос на батч, общий кэш с
 * «Роликами»). Батча нет или у ролика нет оценки — значка нет.
 */
function StashScore({ v }: { v: StashVideo }) {
  const batch = stashBatch(v);
  const list = useVideos(batch);
  const video = list.data?.videos.find((x) => x.slug === v.slug);
  if (!batch || !list.data || !video?.score) return null;
  return (
    <ScoreBadge
      score={video.score}
      tiers={list.data.score_model.tiers}
      below={list.data.score_model.below}
      batch={batch}
      slug={v.slug}
      href={videoHref(v) ?? undefined}
    />
  );
}

function Meta({
  v,
  threshold,
  batchNamed = false,
}: {
  v: StashVideo;
  threshold: number;
  /** CC-0183: батч уже назван рядом с именем (тёзка) — второй раз не пишем. */
  batchNamed?: boolean;
}) {
  const age = ageOf(v.age, threshold);
  // CC-0127: состояние карточки — по `state`/`placeable`; почему не готова — словами фабрики.
  const why = v.card.state === 'not_ready' ? (v.card.why_not ?? reasonsText(v.card)) : null;
  const mark = kindMarkLabel(v);
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <StashScore v={v} />
      {batchNamed ? null : <span data-testid="stash-batch">{batchFrom(v.batch_id)}</span>}
      {/* Возраст от принятия (вечнозелёная тема) — уже в значке возраста, второй раз не пишем. */}
      {v.age.basis === 'accepted' ? null : (
        <span data-testid="stash-accepted">{acceptedAgo(v.age.accepted_days)}</span>
      )}
      <StatusBadge tone={age.stale ? 'warn' : 'idle'} tip={age.tip}>
        <span data-testid="stash-age" data-stale={age.stale ? '1' : undefined}>
          {age.stale ? `устарел · ${age.text}` : age.text}
        </span>
      </StatusBadge>
      <CardStateBadge
        card={v.card.present ? v.card : { ...v.card, state: 'none' }}
        channel={v.channel}
        prefix="карточка"
        testId="stash-card"
      />
      {why ? <span data-testid="stash-card-why">{why}</span> : null}
      {mark ? (
        <StatusBadge tone="idle" tip={mark.tip}>
          <span data-testid="stash-kind-mark">{mark.text}</span>
        </StatusBadge>
      ) : null}
      {inReserve(v) ? (
        <StatusBadge
          tone="warn"
          tip="Снят из ленты: ролик уже в Studio и должен стоять на «Ограниченный доступ». Вернуть — на день, новой загрузки нет"
        >
          <span data-testid="stash-reserve">в запасе</span>
        </StatusBadge>
      ) : null}
      {v.held ? (
        <StatusBadge
          tone="danger"
          tip="На ролике неподписанный холд публикации — разложить нельзя, пока он не подписан (блок «Холды» ниже)"
        >
          <span data-testid="stash-held">холд</span>
        </StatusBadge>
      ) : null}
      {v.held ? (
        <a
          href="#holds"
          data-testid="stash-held-link"
          className="text-primary-text underline-offset-4 hover:underline"
        >
          к холдам
        </a>
      ) : null}
    </span>
  );
}

/** CC-0180: почему новость — словами фабрики как есть — и когда она устареет. */
function NewsLine({ v, today }: { v: StashVideo; today: string }) {
  if (v.feed_kind !== 'news') return null;
  const stale = newsStale(v, today);
  return (
    <span
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"
      data-testid="stash-news"
      data-stale={stale ? '1' : undefined}
    >
      {/* Значок возраста уже в строке выше: второй — только если фабрика его не пометила. */}
      {stale && !v.age.stale ? <StatusBadge tone="warn">устарела</StatusBadge> : null}
      {v.news_why ? (
        <span data-testid="stash-news-why" className="[overflow-wrap:anywhere]">
          Почему новость: {v.news_why}
        </span>
      ) : null}
      {v.stale_at ? (
        <span
          className={stale ? 'text-warning' : 'text-muted-foreground'}
          data-testid="stash-stale-at"
        >
          {stale ? 'Срок вышел' : 'Устареет'}: {slotDay(v.stale_at, today)}
        </span>
      ) : null}
    </span>
  );
}

/** CC-0180: сколько чего в копилке, до какого дня идёт лента и что за горизонтом. */
function PolicyLine({
  s,
  queue,
  today,
}: {
  s: PublishStash;
  queue: ChannelQueue | undefined;
  today: string;
}) {
  const horizon: StashHorizon | null = s.horizon ?? null;
  const beyond =
    horizon && queue
      ? queue.slots.filter((x) => x.taken_by && isAhead(queue, x) && x.day > horizon.last_day)
      : [];
  if (!horizon && !s.news && !s.reserve) return null;
  return (
    <div className="mb-3 grid gap-1 text-[13px] text-muted-foreground" data-testid="stash-policy">
      <span data-testid="stash-summary">
        Новостных: {s.news} · бессрочных: {s.count - s.news} · в запасе: {s.reserve}
      </span>
      {horizon ? (
        <span data-testid="stash-horizon">
          Лента вперёд на {horizon.days} {plural(horizon.days, 'день', 'дня', 'дней')}: до{' '}
          {slotDay(horizon.last_day, today)}. Остальное ждёт здесь.
        </span>
      ) : null}
      {beyond.length ? (
        <span className="text-warning" data-testid="stash-beyond">
          Дальше горизонта в ленте уже стоит: {videosWord(beyond.length)} (
          {beyond.map((x) => slotDay(x.day, today)).join(', ')}).
        </span>
      ) : null}
    </div>
  );
}

function Title({ v }: { v: StashVideo }) {
  const href = videoHref(v);
  const title = stashTitle(v);
  return href ? (
    <Link
      to={href}
      data-testid="stash-title"
      className="font-semibold [overflow-wrap:anywhere] hover:text-primary-text hover:underline"
    >
      {title}
    </Link>
  ) : (
    <span data-testid="stash-title" className="font-semibold [overflow-wrap:anywhere]">
      {title}
    </span>
  );
}

const NOTHING_TO_PLACE =
  'Ставить нечего: подходящих роликов нет или в горизонте ленты нет свободных слотов.';

function PlacePlan({
  plan,
  titleOf,
  today,
}: {
  plan: StashPlacePlan;
  titleOf: NameOf;
  today: string;
}) {
  const own = ownRefusals(plan);
  const skipped = plan.skipped ?? [];
  const staleSkipped = skipped.filter((x) => x.reason === 'stale_news');
  const raw = [...new Set([...plan.lines, ...plan.items.flatMap((x) => x.warnings)])];
  return (
    <>
      <PlanHead
        plan={{ ...plan, why: headWhy(plan) }}
        yes="можно разложить"
        no={plan.auto ? 'ставить нечего' : 'разложить нельзя'}
        partial={
          !plan.ok && plan.placed > 0 && !own.length
            ? `разложить можно ${plan.placed} из ${plan.items.length}`
            : null
        }
      />
      {own.length ? (
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="stash-plan-refusals">
          {own.map((r, i) => (
            <li key={i} className="text-danger" data-code={r.code}>
              {r.code === 'empty_order' ? NOTHING_TO_PLACE : r.message}
            </li>
          ))}
        </ul>
      ) : null}
      <StudioHand items={plan.items.filter((x) => x.ok)} titleOf={titleOf} today={today} />
      <ol className="m-0 grid list-none gap-1.5 p-0" data-testid="stash-plan-items">
        {plan.items.map((it, i) => (
          <li
            key={`${stashKeyOf(it)}-${i}`}
            data-testid="stash-plan-item"
            data-slug={it.slug}
            data-batch={it.batch_id ?? undefined}
            data-ok={it.ok ? '1' : '0'}
            className="grid gap-0.5 rounded-sm border p-2"
          >
            <span className="flex flex-wrap items-center gap-2">
              <b className="font-semibold">
                {i + 1}. {titleOf(it.slug, it.batch_id)}
              </b>
              {it.ok ? (
                <span data-testid="stash-plan-slot">
                  → {slotWhen(it.day, it.label, (d) => slotDay(d, today))}
                </span>
              ) : (
                <StatusBadge tone="danger">не встанет</StatusBadge>
              )}
              {it.stale ? (
                <StatusBadge
                  tone="warn"
                  tip="Устаревший ролик только помечается — разместить его можно"
                >
                  <span data-testid="stash-plan-stale">
                    устарел{it.age_days != null ? `: ${it.age_days} дн.` : ''}
                  </span>
                </StatusBadge>
              ) : null}
              {it.feed_kind === 'news' ? (
                <StatusBadge
                  tone="idle"
                  tip={it.stale_at ? `Устареет: ${slotDay(it.stale_at, today)}` : undefined}
                >
                  <span data-testid="stash-plan-kind">новость</span>
                </StatusBadge>
              ) : null}
              {it.reserve ? (
                <StatusBadge tone="warn" tip="Ролик уже в Studio: новой загрузки нет">
                  <span data-testid="stash-plan-reserve">из запаса</span>
                </StatusBadge>
              ) : null}
              {it.beyond_horizon ? (
                <StatusBadge tone="warn" tip="Ближайший свободный слот дальше горизонта ленты">
                  <span data-testid="stash-plan-beyond">за горизонтом</span>
                </StatusBadge>
              ) : null}
            </span>
            {it.refusals.map((r, j) => (
              <span
                key={j}
                className="text-danger"
                data-testid="stash-plan-refusal"
                data-code={r.code}
              >
                {r.message}
              </span>
            ))}
            {it.warnings
              .filter((w) => !isStudioLine(w))
              .map((w, j) => (
                <span
                  key={j}
                  className="text-warning"
                  data-testid="stash-plan-warning"
                  data-kind={lineWords(w).kind}
                >
                  {lineWords(w).text}
                </span>
              ))}
          </li>
        ))}
      </ol>
      {skipped.length ? (
        <div className="grid gap-1" data-testid="stash-plan-skipped">
          <b className="font-semibold">Ждут в копилке: {videosWord(skipped.length)}</b>
          <ul className="m-0 grid list-none gap-1 p-0">
            {skipped.map((x) => (
              <li
                key={stashKeyOf(x)}
                data-testid="stash-plan-skip"
                data-slug={x.slug}
                data-batch={x.batch_id ?? undefined}
                data-reason={x.reason}
              >
                <b className="font-semibold">{titleOf(x.slug, x.batch_id)}</b>:{' '}
                {skipReasonText(x.reason, x.message)}
              </li>
            ))}
          </ul>
          {staleSkipped.length ? (
            <div data-testid="stash-plan-stale-more">
              <More className="mt-0" label="Подробнее: устаревшие новости">
                <span className="font-sans">
                  Обычно автоматика пропускает устаревшие новости: зритель увидит то, что уже
                  прошло. Поставить такую новость можно вручную или отметкой «Брать и устаревшие
                  новости» под списком копилки.
                </span>
                {staleSkipped.map((x) => (
                  <span key={stashKeyOf(x)}>
                    {x.slug}: {withoutBatchTail(x.message)}
                  </span>
                ))}
              </More>
            </div>
          ) : null}
        </div>
      ) : null}
      {plan.auto && !plan.ok ? (
        <p className="m-0 text-muted-foreground" data-testid="stash-auto-manual">
          Можно разложить вручную: отметьте ролики и нажмите «Разложить по слотам…».
        </p>
      ) : null}
      <More className="mt-0">
        {raw.map((l, i) => (
          <span key={i}>{withoutBatchTail(l)}</span>
        ))}
        {skipped.map((x) => (
          <span key={`s${stashKeyOf(x)}`}>
            {x.slug}: {x.reason} — {withoutBatchTail(x.line ?? '')}
          </span>
        ))}
        {[...plan.refusals, ...plan.items.flatMap((x) => x.refusals)].map((r, i) => (
          <span key={`r${i}`}>
            {r.slug ? `${r.slug}: ` : ''}код {r.code}
            {r.line ? ` — ${withoutBatchTail(r.line)}` : ''}
          </span>
        ))}
        {own
          .filter((r) => r.code === 'empty_order')
          .map((r) => (
            <span key="empty">{r.message}</span>
          ))}
        <span>заказ: {plan.order.join(', ')}</span>
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function PlaceDone({
  r,
  titleOf,
  today,
  onClose,
}: {
  r: StashPlaceResult;
  titleOf: NameOf;
  today: string;
  onClose: () => void;
}) {
  const placed = r.items.filter((x) => x.ok);
  return (
    <Done
      tone={r.commit ? 'ok' : 'warn'}
      title={`${r.auto ? 'Разложено автоматически' : 'Разложено'}: ${videosWord(r.placed)}`}
      testId="stash-done"
      onClose={onClose}
    >
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {placed.map((it) => (
          <li
            key={stashKeyOf(it)}
            data-testid="stash-done-item"
            data-slug={it.slug}
            data-batch={it.batch_id ?? undefined}
          >
            {titleOf(it.slug, it.batch_id)} → {slotWhen(it.day, it.label, (d) => slotDay(d, today))}
          </li>
        ))}
      </ul>
      {r.skipped?.length ? (
        <ul className="m-0 grid list-none gap-0.5 p-0" data-testid="stash-done-skipped">
          {r.skipped.map((x) => (
            <li key={stashKeyOf(x)} data-reason={x.reason}>
              Ждёт в копилке: {titleOf(x.slug, x.batch_id)} — {skipReasonText(x.reason, x.message)}
            </li>
          ))}
        </ul>
      ) : null}
      <StudioHand items={placed} titleOf={titleOf} today={today} done />
      <span data-testid="stash-done-commit">
        {r.commit
          ? `Сохранено: ${r.committed.length} ${plural(r.committed.length, 'файл', 'файла', 'файлов')} публикации.`
          : 'Коммитить было нечего.'}
      </span>
      <More className="mt-0">
        {r.commit ? <span>коммит {r.commit}</span> : null}
        {r.committed.map((f) => (
          <span key={f}>{withoutBatchTail(f)}</span>
        ))}
        {r.lines.map((l, i) => (
          <span key={`l${i}`}>{withoutBatchTail(l)}</span>
        ))}
      </More>
    </Done>
  );
}

function RepairPlan({ plan, titleOf }: { plan: StashRepairPlan; titleOf: NameOf }) {
  return (
    <>
      <PlanHead plan={plan} yes="можно доложить" no="доложить нельзя" />
      <ul className="m-0 grid list-none gap-1 p-0" data-testid="stash-repair-items">
        {plan.items.map((it, i) => (
          <li key={i} data-code={it.code}>
            <b className="font-semibold">{titleOf(it.slug, it.batch_id)}</b>:{' '}
            {it.text_ru ? withoutPath(it.text_ru) : 'фабрика положит ролик в копилку'}
          </li>
        ))}
      </ul>
      <More className="mt-0">
        {plan.items.map((it, i) => (
          <span key={i}>
            {it.entry_id}: {it.code}
            {it.publish_path ? ` → ${it.publish_path}` : ''}
            {it.text_ru ? ` · ${it.text_ru}` : ''}
          </span>
        ))}
        {plan.lines.map((l, i) => (
          <span key={`l${i}`}>{l}</span>
        ))}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function NotQueued({
  channel,
  rows,
  titleOf,
  onRepaired,
}: {
  channel: string;
  rows: StashVideo[];
  titleOf: NameOf;
  onRepaired: (r: StashRepairResult) => void;
}) {
  return (
    <div className="mt-4 grid gap-2" data-testid="stash-not-queued">
      <h3 className="eyebrow">Приняты, но не в копилке</h3>
      <ul className="m-0 grid list-none gap-2 p-0">
        {rows.map((v) => (
          <li
            key={v.entry_id ?? stashKeyOf(v)}
            data-testid="stash-not-queued-row"
            data-slug={v.slug}
            className="grid gap-2 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] p-2.5 text-[13px] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
          >
            <span className="grid min-w-0 gap-0.5">
              <Title v={v} />
              <span className="text-xs text-muted-foreground">
                {/* «не в копилке» уже в заголовке раздела — здесь только когда принят. */}
                {batchFrom(v.batch_id)} · {acceptedAgo(v.age.accepted_days)}
              </span>
              <span data-testid="stash-not-queued-text">
                {v.queue_text_ru
                  ? withoutPath(v.queue_text_ru)
                  : 'Фабрика не положила ролик в копилку.'}
              </span>
            </span>
            {v.entry_id ? (
              <WriteAction<string[] | null, StashRepairPlan, StashRepairResult>
                id="stash-repair"
                label="Доложить в копилку…"
                title="Доложить ролик в копилку?"
                description="Фабрика проверила, что сделает с записью приёмки. Это только план — ничего не изменится, пока вы не подтвердите."
                body={[v.entry_id]}
                tip="Фабрика положит принятый ролик в копилку канала; запись — после вашего «да»"
                confirmLabel="Доложить"
                plan={(b) => planStashRepair(channel, b)}
                act={(c) => stashRepair(channel, c)}
                view={(p) => <RepairPlan plan={p} titleOf={titleOf} />}
                onDone={onRepaired}
                problemText={stashProblemText}
                triggerVariant="outline"
              />
            ) : null}
          </li>
        ))}
      </ul>
      <More className="mt-0" label="Подробнее: не в копилке">
        {rows.map((v) => (
          <span key={stashKeyOf(v)}>
            {v.queue_text_ru ? `${withoutBatchTail(v.queue_text_ru)} · ` : ''}
            {v.entry_id}: {v.queue_code ?? '—'}
            {v.repair ? ` · ${v.repair}` : ''}
          </span>
        ))}
      </More>
    </div>
  );
}

/** Уже размещённая версия: ссылка на её слот, если центр туда ведёт, иначе имя и батч. */
function PlacedVersion({ channel, v }: { channel: string; v: StashOtherVersion }) {
  const [params] = useSearchParams();
  const to = otherVersionSlot(v.other_path, channel);
  const entry = entryParts(v.other_entry);
  const slug = entry?.slug ?? v.slug;
  const name = readableSlug(slug);
  if (to) {
    const p = new URLSearchParams(params);
    p.set('channel', channel);
    p.set('slot', to.slot);
    // Батч в адресе — только у файла `<имя>~<батч>` (тёзки, CC-0183), как у ссылок ленты.
    if (to.batch) p.set('batch', to.batch);
    else p.delete('batch');
    return (
      <span data-testid="stash-other-placed">
        Уже размещена:{' '}
        <Link
          to={{ search: `?${p.toString()}` }}
          data-testid="stash-other-link"
          className="text-primary-text underline underline-offset-2 hover:no-underline"
        >
          {name}, {to.where}
        </Link>
      </span>
    );
  }
  return (
    <span data-testid="stash-other-placed">
      Уже размещена: {name}
      {entry ? `, ${batchFrom(entry.batch)}` : ''}
    </span>
  );
}

function OtherVersion({ channel, rows }: { channel: string; rows: StashOtherVersion[] }) {
  return (
    <div className="mt-4 grid gap-2" data-testid="stash-other-version">
      <h3 className="eyebrow">Не положены: похоже на другую версию</h3>
      <p className="m-0 text-[13px] text-muted-foreground" data-testid="stash-other-note">
        Решает драйвер фабрики, вам ничего делать не нужно.
      </p>
      <ul className="m-0 grid list-none gap-2 p-0">
        {rows.map((v) => {
          const href = videoHref(v as StashVideo);
          const title = stashTitle(v);
          return (
            <li
              key={v.entry_id ?? stashKeyOf(v)}
              data-testid="stash-other-row"
              data-slug={v.slug}
              data-batch={v.batch_id ?? undefined}
              className="grid min-w-0 gap-0.5 rounded-sm border border-border p-2.5 text-[13px]"
            >
              {href ? (
                <Link
                  to={href}
                  data-testid="stash-other-title"
                  className="font-semibold [overflow-wrap:anywhere] hover:text-primary-text hover:underline"
                >
                  {title}
                </Link>
              ) : (
                <span
                  data-testid="stash-other-title"
                  className="font-semibold [overflow-wrap:anywhere]"
                >
                  {title}
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {batchFrom(v.batch_id)} · {acceptedAgo(v.age.accepted_days)}
              </span>
              <span data-testid="stash-other-why">{otherVersionWhy(v)}</span>
              <PlacedVersion channel={channel} v={v} />
            </li>
          );
        })}
      </ul>
      <More className="mt-0" label="Подробнее: для драйвера фабрики">
        {rows.map((v) => (
          <span key={stashKeyOf(v)} className="[overflow-wrap:anywhere]">
            {v.entry_id ?? v.slug}: {v.queue_code ?? '—'}
            {v.other_entry ? ` · версия ${v.other_entry}` : ''}
            {v.other_path ? ` · ${v.other_path}` : ''}
            {v.repair ? ` · ${v.repair}` : ''}
          </span>
        ))}
      </More>
    </div>
  );
}

function Pile({ channel, s }: { channel: string; s: PublishStash }) {
  const name = useChannelNames();
  const today = mskDay(s.now ?? new Date().toISOString());
  const threshold = s.staleness.threshold_days ?? 14;
  const [order, setOrder] = useState<string[]>(() => mergeOrder([], s.videos));
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  // CC-0164: отметка живёт, пока ролик в копилке. Перечитанная копилка без ролика снимает его
  // отметку сразу (а не только прячет): вернётся ролик — вернётся без галочки.
  const inPile = s.videos.map(stashKeyOf).join('\n');
  const [seen, setSeen] = useState(inPile);
  if (seen !== inPile) {
    setSeen(inPile);
    const keys = new Set(s.videos.map(stashKeyOf));
    setPicked((prev) => {
      const kept = [...prev].filter((k) => keys.has(k));
      return kept.length === prev.size ? prev : new Set(kept);
    });
  }
  const [said, setSaid] = useState('');
  // Итог держит названия на момент записи: разложенные и доложенные уходят из ответа копилки.
  const [done, setDone] = useState<{ r: StashPlaceResult; titleOf: NameOf } | null>(null);
  const [repaired, setRepaired] = useState<{ r: StashRepairResult; titleOf: NameOf } | null>(null);
  const titleOf = stashTitles(s.videos, s.not_queued);
  // CC-0187: ответ прежней фабрики — поля нет.
  const otherVersion = s.other_version ?? [];
  const names = namesakesOf(s.videos);
  // CC-0180: запас возвращается переносом на день; автоматика — план фабрики, `force` — по отметке.
  const [force, setForce] = useState(false);
  const [moved, setMoved] = useState<MoveDoneState | null>(null);
  const queue = useQueue(channel).data;
  const placedFeed = queue ? placedOf(queue, (x) => titleOf(x)) : [];
  // CC-0183: адрес с батчем — только когда есть тёзка (в копилке или уже в ленте), иначе как раньше.
  const batchToSend = (v: StashVideo) =>
    names.has(v.slug) || placedFeed.some((p) => p.slug === v.slug) ? (v.batch_id ?? null) : null;
  const ahead = queue ? daysAhead(queue) : [];
  const lastDay = s.horizon?.last_day ?? null;
  const staleNews = s.videos.filter((v) => newsStale(v, today));

  const byKey = new Map(s.videos.map((v) => [stashKeyOf(v), v]));
  // Перечитанная копилка: порядок — прежний для оставшихся, новые — в конец по дате принятия.
  const merged = mergeOrder(order, s.videos).map((k) => byKey.get(k)!);
  // CC-0180: сначала новостные, потом бессрочные; ↑/↓ — внутри своей группы.
  const news = merged.filter((v) => v.feed_kind === 'news');
  const evergreen = merged.filter((v) => v.feed_kind !== 'news');
  const rows = [...news, ...evergreen];
  const chosen = rows.map(stashKeyOf).filter((k) => picked.has(k));
  const ready = rows.filter(placeable).map(stashKeyOf);

  const toggle = (k: string, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(k);
      else next.delete(k);
      return next;
    });
  const shift = (i: number, by: -1 | 1) => {
    const v = rows[i]!;
    setOrder(move(rows.map(stashKeyOf), i, by));
    const title = withMark(stashTitle(v), namesakeMark(names, v.slug, v.batch_id));
    setSaid(`${title} — теперь ${i + by + 1}-й из ${rows.length}`);
  };

  const group = (kind: 'news' | 'evergreen', list: StashVideo[], from: number, head: string) =>
    list.length ? (
      <section key={kind} className="grid gap-2" data-testid="stash-group" data-kind={kind}>
        {news.length ? (
          <h3 className="eyebrow" data-testid="stash-group-head">
            {head}: {list.length}
          </h3>
        ) : null}
        <ol
          className="m-0 grid list-none gap-2 p-0"
          aria-label={`${head}: ролики копилки по порядку размещения`}
        >
          {list.map((v, j) => {
            const i = from + j;
            const k = stashKeyOf(v);
            const mark = namesakeMark(names, v.slug, v.batch_id);
            const title = withMark(stashTitle(v), mark);
            return (
              <li
                key={k}
                data-testid="stash-row"
                data-slug={v.slug}
                data-batch={v.batch_id ?? undefined}
                data-picked={picked.has(k) ? '1' : undefined}
                className={cn(
                  'grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-3 rounded-sm border p-2.5 text-[13px] sm:grid-cols-[auto_auto_minmax(0,1fr)_auto]',
                  picked.has(k) &&
                    'border-primary bg-[color-mix(in_srgb,var(--primary)_6%,transparent)]',
                )}
              >
                {/* CC-0164: щёлкать можно по всей полосе у галочки, а не только в квадрат 16px. */}
                <label
                  data-testid="stash-pick-area"
                  className="-my-2.5 -ml-2.5 flex cursor-pointer items-center self-stretch py-2.5 pr-1 pl-2.5"
                >
                  <input
                    type="checkbox"
                    data-testid="stash-pick"
                    aria-label={`Разложить: ${title}`}
                    checked={picked.has(k)}
                    onChange={(e) => toggle(k, e.target.checked)}
                    className="size-4 cursor-pointer"
                  />
                </label>
                <Thumb url={v.preview_url} />
                <span className="grid min-w-0 gap-1">
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span
                      className="font-mono text-xs text-muted-foreground"
                      data-testid="stash-pos"
                    >
                      {i + 1}.
                    </span>
                    <Title v={v} />
                    {mark ? (
                      <StatusBadge
                        tone="idle"
                        tip="В копилке два ролика с этим именем: их различает батч"
                      >
                        <span data-testid="stash-namesake">{mark}</span>
                      </StatusBadge>
                    ) : null}
                  </span>
                  <Meta v={v} threshold={threshold} batchNamed={!!mark} />
                  <NewsLine v={v} today={today} />
                  {/* CC-0127: в копилке — только у не готовой и без карточки (итог держится). */}
                  <CardActions
                    channel={channel}
                    slug={v.slug}
                    batchId={v.batch_id ?? null}
                    card={v.card}
                    title={title}
                    compact
                    rebuild={v.card.state === 'not_ready' || !v.card.present}
                  />
                  {inReserve(v) && queue?.slot ? (
                    <ReturnFromReserve
                      channel={channel}
                      slug={v.slug}
                      batchId={batchToSend(v)}
                      title={title}
                      days={ahead}
                      placed={placedFeed}
                      titleOf={titleOf}
                      today={today}
                      lastDay={lastDay}
                      onDone={setMoved}
                    />
                  ) : null}
                </span>
                <span className="col-span-3 flex gap-1 justify-self-end sm:col-span-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid="stash-up"
                    aria-label={`Выше: ${title}`}
                    disabled={j === 0}
                    onClick={() => shift(i, -1)}
                  >
                    <span aria-hidden>↑</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    data-testid="stash-down"
                    aria-label={`Ниже: ${title}`}
                    disabled={j === list.length - 1}
                    onClick={() => shift(i, 1)}
                  >
                    <span aria-hidden>↓</span>
                  </Button>
                </span>
              </li>
            );
          })}
        </ol>
      </section>
    ) : null;

  return (
    <>
      <PolicyLine s={s} queue={queue} today={today} />
      {s.videos.length ? (
        <>
          <div className="grid gap-3" data-testid="stash-list">
            {group('news', news, 0, 'Новостные')}
            {group('evergreen', evergreen, news.length, 'Бессрочные')}
          </div>
          <p role="status" aria-live="polite" className="sr-only" data-testid="stash-said">
            {said}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="stash-bar">
            {/* CC-0164: ширина подписи и состав кнопок не меняются от отметки — «Разложить по
                слотам…» не уезжает из-под щелчка (раньше на его место вставала «Снять отметки»). */}
            <span
              className="min-w-[11rem] text-[13px] text-muted-foreground"
              data-testid="stash-picked"
            >
              {chosen.length ? `Отмечено: ${videosWord(chosen.length)}` : 'Ничего не отмечено'}
            </span>
            <Button
              size="sm"
              variant="outline"
              data-testid="stash-pick-ready"
              disabled={!ready.length}
              onClick={() => setPicked(new Set(ready))}
            >
              Отметить готовые
            </Button>
            <Button
              size="sm"
              variant="ghost"
              data-testid="stash-pick-none"
              disabled={!chosen.length}
              onClick={() => setPicked(new Set())}
            >
              Снять отметки
            </Button>
            <WriteAction<string[], StashPlacePlan, StashPlaceResult>
              id="stash-place"
              label="Разложить по слотам…"
              title={`Разложить ролики ${name(channel)} по ближайшим слотам?`}
              description={`Фабрика показала, какой ролик ${name(channel)} в какой день встанет. Это только план — ничего не изменится, пока вы не подтвердите. Порядок — как в списке.`}
              body={chosen.length ? chosen : null}
              why={chosen.length ? null : 'Отметьте ролики, которые разложить'}
              tip="Фабрика поставит отмеченные ролики по порядку на ближайшие свободные слоты; запись и коммит — после вашего «да»"
              confirmLabel="Разложить"
              countdownWord="план ещё"
              plan={(b) => planStashPlace(channel, b)}
              act={(c) => stashPlace(channel, c)}
              view={(p) => <PlacePlan plan={p} titleOf={titleOf} today={today} />}
              onDone={(r) => {
                setDone({ r, titleOf });
                setPicked(new Set());
              }}
              problemText={stashProblemText}
            />
            <WriteAction<{ force: boolean }, StashPlacePlan, StashPlaceResult>
              id="stash-auto"
              label="Разложить автоматически"
              title={`Разложить копилку ${name(channel)} автоматически?`}
              description="Порядок выбирает фабрика: сначала свежие новости, потом бессрочные, столько, сколько берут свободные слоты в горизонте ленты. Что не встало — ниже с причиной. Это только план — ничего не изменится, пока вы не подтвердите."
              body={{ force }}
              tip="Фабрика сама выберет порядок и слоты; что не встало — покажет с причиной. Запись и коммит — после вашего «да»"
              confirmLabel="Разложить"
              countdownWord="план ещё"
              plan={(b) => planStashAuto(channel, b.force)}
              act={(c) => stashPlace(channel, c)}
              view={(p) => <PlacePlan plan={p} titleOf={titleOf} today={today} />}
              onDone={(r) => {
                setDone({ r, titleOf });
                setPicked(new Set());
                setForce(false);
              }}
              problemText={stashProblemText}
              triggerVariant="outline"
            />
          </div>
          {staleNews.length ? (
            <div data-testid="stash-auto-more">
              <More label="Подробнее: устаревшие новости" className="mt-2">
                <label className="flex items-start gap-2 font-sans text-[13px] text-foreground">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    data-testid="stash-auto-force"
                    checked={force}
                    onChange={(e) => setForce(e.target.checked)}
                  />
                  <span>
                    Брать и устаревшие новости ({staleNews.length}). Обычно автоматика их
                    пропускает: зритель увидит новость, которая уже прошла. С этой отметкой они
                    встанут в ленту вместе со свежими — план покажет какие.
                  </span>
                </label>
              </More>
            </div>
          ) : null}
        </>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="stash-empty">
          Копилка пуста.
          {s.not_queued.length || otherVersion.length ? '' : ' Все принятые ролики стоят в слотах.'}
        </p>
      )}
      {done ? (
        <div className="mt-3">
          <PlaceDone
            r={done.r}
            titleOf={done.titleOf}
            today={today}
            onClose={() => setDone(null)}
          />
        </div>
      ) : null}
      {moved ? (
        <div className="mt-3">
          <MoveDone done={moved} today={today} onClose={() => setMoved(null)} />
        </div>
      ) : null}
      {s.not_queued.length ? (
        <NotQueued
          channel={channel}
          rows={s.not_queued}
          titleOf={titleOf}
          onRepaired={(r) => setRepaired({ r, titleOf })}
        />
      ) : null}
      {otherVersion.length ? <OtherVersion channel={channel} rows={otherVersion} /> : null}
      {repaired ? (
        <div className="mt-3">
          <Done
            tone="ok"
            title="Доложено в копилку"
            testId="stash-repaired"
            onClose={() => setRepaired(null)}
          >
            {repaired.r.items.map((it, i) => (
              <span key={i} data-testid="stash-repaired-item">
                {repaired.titleOf(it.slug, it.batch_id)}:{' '}
                {it.text_ru ? withoutPath(it.text_ru) : it.code}
              </span>
            ))}
            <More className="mt-0">
              {repaired.r.commit ? <span>коммит {repaired.r.commit}</span> : null}
              {repaired.r.items.map((it, i) =>
                it.text_ru ? <span key={`t${i}`}>{it.text_ru}</span> : null,
              )}
              {repaired.r.lines.map((l, i) => (
                <span key={i}>{l}</span>
              ))}
            </More>
          </Done>
        </div>
      ) : null}
      <More label="Подробнее: копилка и правило свежести">
        <span>
          правило свежести {s.staleness.rule ?? '—'}:{' '}
          {s.staleness.stale_when ?? `days > ${threshold}`}
          {s.staleness.basis ? ` · ${s.staleness.basis}` : ''}
        </span>
        {s.videos.map((v) => (
          <span key={stashKeyOf(v)}>
            {v.entry_id ?? v.slug} · {withoutBatchTail(v.mp4 ?? 'нет mp4')} ·{' '}
            {withoutBatchTail(v.card.path ?? 'нет карточки')}
            {v.hold_id ? ` · холд ${v.hold_id}` : ''}
          </span>
        ))}
      </More>
    </>
  );
}

const problem = (e: unknown) =>
  e instanceof BatchError && e.problem ? e.problem.message : 'Проверьте, что API фабрики запущен.';

/** Блок «Копилка» выбранного канала. */
export function Stash({ channel }: { channel: string }) {
  const q = useStash(channel);
  const name = useChannelNames();
  const s = q.data;
  const title = !s
    ? 'Копилка'
    : s.count
      ? `В копилке: ${videosWord(s.count)}${s.stale ? ` · устарели: ${s.stale}` : ''}`
      : 'Копилка пуста';
  return (
    <Card
      id="stash"
      className="scroll-mt-36"
      aria-labelledby="stash-title"
      data-testid="stash"
      data-channel={channel}
      data-count={s?.count}
    >
      <CardHead
        eyebrow={
          <>
            Копилка · <Keep data-testid="stash-channel">{name(channel)}</Keep>
          </>
        }
        title={title}
        titleId="stash-title"
      />
      {q.isPending ? (
        <SkeletonRows rows={3} height={64} label="Читаю копилку…" />
      ) : !s ? (
        <ErrorState title="Копилку не прочитать" error={q.error} onRetry={() => void q.refetch()}>
          {problem(q.error)}
        </ErrorState>
      ) : (
        <>
          {/* CC-0164: упал только опрос — прежний список с отметками остаётся на экране. */}
          {q.isError ? (
            <p
              role="status"
              className="m-0 mb-2 flex flex-wrap items-center gap-2 text-[13px] text-warning"
              data-testid="stash-stale-read"
            >
              Копилку не перечитать — показана прежняя. {problem(q.error)}
              <Button size="sm" variant="ghost" onClick={() => void q.refetch()}>
                Перечитать
              </Button>
            </p>
          ) : null}
          <Pile channel={channel} s={s} />
        </>
      )}
    </Card>
  );
}
