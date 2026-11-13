// Перенос размещённых роликов в ленте слотов (CC-0166; фабрика CC-0165, договор 0.73.0): у
// размещённого ролика — «Перенести…» (выбор дня) и «Вернуть в копилку» (только не в Studio), над
// лентой — «Сдвинуть очередь…» (все с дня N на день раньше или позже, ролик дня N−1 — в копилку)
// одним планом. Окно — как «Разложить по слотам…» (`WriteAction`: план фабрики с токеном и
// отсчётом, одно «да»); «да» шлёт токен и `base_sha256` плана. Строки фабрики `STUDIO …` — на
// виду: ролик уже в Studio, дату там человек ставит вручную. После «да» перечитывается вся
// публикация (лента, копилка, обзор — `publishKeys.all`); карточки дней только помечаются
// устаревшими: ролики уже на новых днях, прежние «день/ролик» не перечитываются (их нет — 404).
// CC-0180 (фабрика CF-0918): «Снять из ленты в запас…» у ролика из Studio — до «да» окно говорит:
// сначала «Ограниченный доступ» в Studio, центр Studio не проверяет; возврат из запаса — перенос на
// день, новой загрузки нет, дату в Studio человек ставит сам. Строки `STUDIO …`, `HORIZON …` —
// русским текстом, сами строки — под «подробнее». Опубликовать сразу центр не предлагает нигде.
// CC-0183 (фабрика CC-0182, CF-0920): тёзку называет батч: `moves[].batch_id`, `<батч>/<имя>` в
// `unplace` и `withdraw`. Батч шлётся, только когда есть тёзка, — без тёзки запрос прежний.
import { useQueryClient } from '@tanstack/react-query';
import { useId, useRef, useState, type ReactNode } from 'react';

import { publishKeys } from '@/api/publish';

import {
  confirmMove,
  isStudioLine,
  MOVE_MAX_EDITS,
  moveProblemText,
  planMove,
  type MoveBody,
  type MoveItem,
  type MovePlan,
  type MoveResult,
} from '@/api/publishMove';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { WriteButton } from '@/components/common/WriteButton';
import { plural, videosWord } from '@/pages/batches/format';
import { inputBase } from '@/pages/channels/styles';

import { slotDay } from './format';
import {
  addDay,
  dayChoice,
  moveEdit,
  moveName,
  moveRefusalText,
  shiftBody,
  type Placed,
} from './moveWords';
import { headWhy, lineWords, ownRefusals, whyIsOnItem } from './serverLines';
import { slotWhen, stashKeyOf, withoutBatchTail } from './stashWords';
import { Done, PlanHead, WriteAction } from './Writes';

type NameOf = (slug: string, batchId?: string | null) => string;

/** Итог переноса держит названия на момент записи: ушедший в копилку пропадает из ленты. */
export type MoveDoneState = { r: MoveResult; titleOf: NameOf };

/**
 * Запись переноса: `WriteAction` с планом фабрики; `base_sha256` последнего плана уходит с «да»
 * (план взят заново — и отпечаток новый).
 */
function MoveAction({
  channel,
  id,
  label,
  title,
  description,
  body,
  why,
  tip,
  confirmLabel,
  pendingLabel = 'Переношу…',
  view,
  onDone,
  triggerVariant,
}: {
  channel: string;
  id: string;
  label: string;
  title: string;
  description: ReactNode;
  body: MoveBody | null;
  why?: string | null;
  tip: string;
  confirmLabel: string;
  pendingLabel?: string;
  view: (p: MovePlan) => ReactNode;
  onDone: (r: MoveResult) => void;
  triggerVariant?: 'outline' | 'ghost';
}) {
  const base = useRef<string | null>(null);
  const qc = useQueryClient();
  const note = [...publishKeys.all, 'note'];
  const isNote = (k: readonly unknown[]) => k[2] === note[2];
  // Карточки дней — только пометить устаревшими: перенесённые ролики читаются по новым дням,
  // а прежние «день/ролик» перечитывать незачем (их уже нет — 404).
  const settled = () => {
    void qc.invalidateQueries({ queryKey: publishKeys.all, predicate: (q) => !isNote(q.queryKey) });
    void qc.invalidateQueries({ queryKey: note, refetchType: 'none' });
  };
  return (
    <WriteAction<MoveBody, MovePlan, MoveResult>
      id={id}
      label={label}
      title={title}
      description={description}
      body={body}
      why={why}
      tip={tip}
      confirmLabel={confirmLabel}
      pendingLabel={pendingLabel}
      plan={async (b) => {
        const p = await planMove(channel, b);
        base.current = p.base_sha256 ?? null;
        return p;
      }}
      act={(c) => confirmMove(channel, c, base.current)}
      view={view}
      onDone={onDone}
      problemText={moveProblemText}
      onSettled={settled}
      triggerVariant={triggerVariant}
    />
  );
}

/** Куда правка: «вт 13.10 → в копилку», «вт 13.10 → в запас», «из запаса → ср 14.10, 01:00». */
function whereText(it: MoveItem, today: string): string {
  const from = it.reserve ? 'из запаса' : it.from_day ? slotDay(it.from_day, today) : '—';
  if (it.op === 'unplace') return `${from} → в копилку`;
  if (it.op === 'withdraw') return `${from} → в запас`;
  return `${from} → ${slotWhen(it.day, it.label, (d) => slotDay(d, today))}`;
}

/** Что нужно блоку «руками в Studio» от правки переноса и от строки плана копилки. */
export type HandItem = {
  slug: string;
  batch_id?: string | null;
  op?: string;
  ok?: boolean;
  in_studio?: boolean | null;
  reserve?: boolean | null;
  day?: string | null;
  label?: string | null;
  warnings: string[];
};

const HAND_BOX =
  'grid gap-1.5 rounded-sm border border-[color-mix(in_srgb,var(--warning)_55%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_12%,var(--card))] p-3 text-[13px]';

/** Строки фабрики про Studio — под «подробнее»: на виду русский текст блока. */
function StudioLines({ rows }: { rows: HandItem[] }) {
  const lines = rows.flatMap((r) => r.warnings.filter(isStudioLine));
  if (!lines.length) return null;
  return (
    <More className="mt-0" label="Подробнее: что сказала фабрика">
      {lines.map((w, i) => (
        <span key={i} data-testid="move-studio-line">
          {withoutBatchTail(w)}
        </span>
      ))}
    </More>
  );
}

/**
 * Что человек делает в Studio сам: снять ролик («Ограниченный доступ», окно обязано сказать это до
 * «да») и поставить дату — перенесённому и вернувшемуся из запаса (строки фабрики `STUDIO …`).
 */
export function StudioHand({
  items,
  titleOf,
  today,
  done = false,
}: {
  items: HandItem[];
  titleOf: NameOf;
  today: string;
  done?: boolean;
}) {
  const off = items.filter((i) => i.op === 'withdraw' && i.ok !== false);
  const dated = items.filter(
    (i) =>
      i.op !== 'withdraw' &&
      i.op !== 'unplace' &&
      !(i.reserve && i.ok === false) &&
      (i.reserve || i.in_studio || i.warnings.some(isStudioLine)),
  );
  if (!off.length && !dated.length) return null;
  return (
    <>
      {off.length ? (
        <div role="note" data-testid="move-studio-withdraw" className={HAND_BOX}>
          <b className="font-semibold text-warning" data-testid="withdraw-studio-first">
            {done
              ? 'Проверьте Studio: там должно стоять «Ограниченный доступ»'
              : 'Сначала поставьте в Studio «Ограниченный доступ»'}
          </b>
          <span className="text-muted-foreground">
            Центр Studio не проверяет и не меняет: он правит только журнал и копилку. Если ролик в
            Studio всё ещё запланирован, уберите дату вручную — иначе он выйдет в свой день.
          </span>
          <ul className="m-0 grid list-none gap-1 p-0">
            {off.map((it) => (
              <li
                key={stashKeyOf(it)}
                data-testid="move-studio-withdraw-item"
                data-slug={it.slug}
                data-batch={it.batch_id ?? undefined}
              >
                <b className="font-semibold">{titleOf(it.slug, it.batch_id)}</b>: «Ограниченный
                доступ», без даты публикации
              </li>
            ))}
          </ul>
          <StudioLines rows={off} />
        </div>
      ) : null}
      {dated.length ? (
        <div role="note" data-testid="move-studio" className={HAND_BOX}>
          <b className="font-semibold text-warning" data-testid="move-studio-title">
            {done ? 'Теперь поставьте дату в Studio вручную' : 'Дату в Studio поставить вручную'}
          </b>
          <span className="text-muted-foreground">
            {dated.length === 1 ? 'Этот ролик уже в Studio' : 'Эти ролики уже в Studio'}: фабрика
            поправит журнал загрузок, а дату публикации в Studio меняет человек.
          </span>
          <ul className="m-0 grid list-none gap-1 p-0">
            {dated.map((it) => (
              <li
                key={stashKeyOf(it)}
                data-testid="move-studio-item"
                data-slug={it.slug}
                data-batch={it.batch_id ?? undefined}
                className="grid"
              >
                <span>
                  <b className="font-semibold">{titleOf(it.slug, it.batch_id)}</b>:{' '}
                  {it.reserve ? 'поставить «Отложенная публикация» на ' : 'поставить '}
                  <b className="font-semibold">
                    {slotWhen(it.day, it.label, (d) => slotDay(d, today))}
                  </b>
                  {it.reserve ? (
                    <span data-testid="move-studio-no-upload">
                      {' '}
                      — там сейчас «Ограниченный доступ», новой загрузки нет
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <StudioLines rows={dated} />
        </div>
      ) : null}
    </>
  );
}

/** План фабрики: правки (откуда → куда), отказы её словами, предупреждения; STUDIO — на виду. */
export function MovePlanView({
  plan,
  titleOf,
  today,
  yes = 'можно перенести',
  no = 'перенести нельзя',
}: {
  plan: MovePlan;
  titleOf: NameOf;
  today: string;
  yes?: string;
  no?: string;
}) {
  const own = ownRefusals(plan);
  const bad = plan.items.filter((i) => !i.ok).length;
  // Причина уже написана у правки: над списком — сколько правок не годится, а не тот же отказ.
  const why = whyIsOnItem(plan)
    ? `Не годится правок: ${bad} из ${plan.items.length} — план исполняется только целиком.`
    : headWhy(plan);
  // Строки фабрики на виду только русским текстом, сами они — под «подробнее».
  const raw = [
    ...new Set([...plan.lines, ...plan.warnings, ...plan.items.flatMap((x) => x.warnings)]),
  ];
  return (
    <>
      <PlanHead plan={{ ...plan, why }} yes={yes} no={no} />
      {own.length ? (
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="move-plan-refusals">
          {own.map((r, i) => (
            <li key={i} className="text-danger" data-code={r.code}>
              {moveRefusalText(r)}
            </li>
          ))}
        </ul>
      ) : null}
      {plan.warnings.length ? (
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="move-plan-warnings">
          {plan.warnings.map((w, i) => (
            <li key={i} className="text-warning">
              {lineWords(w).text}
            </li>
          ))}
        </ul>
      ) : null}
      <StudioHand items={plan.items} titleOf={titleOf} today={today} />
      <ol className="m-0 grid list-none gap-1.5 p-0" data-testid="move-plan-items">
        {plan.items.map((it, i) => (
          <li
            key={`${it.op}-${stashKeyOf(it)}-${i}`}
            data-testid="move-plan-item"
            data-slug={it.slug}
            data-batch={it.batch_id ?? undefined}
            data-op={it.op}
            data-ok={it.ok ? '1' : '0'}
            className="grid gap-0.5 rounded-sm border p-2"
          >
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <b className="font-semibold [overflow-wrap:anywhere]">
                {titleOf(it.slug, it.batch_id)}
              </b>
              <span data-testid="move-plan-where">{whereText(it, today)}</span>
              {it.in_studio ? <StatusBadge tone="warn">в Studio</StatusBadge> : null}
              {it.ok ? null : <StatusBadge tone="danger">отказ</StatusBadge>}
            </span>
            {it.refusals.map((r, j) => (
              <span
                key={j}
                className="text-danger"
                data-testid="move-plan-refusal"
                data-code={r.code}
              >
                {moveRefusalText(r)}
              </span>
            ))}
            {it.warnings
              .filter((w) => !isStudioLine(w))
              .map((w, j) => (
                <span
                  key={j}
                  className="text-warning"
                  data-testid="move-plan-warning"
                  data-kind={lineWords(w).kind}
                >
                  {lineWords(w).text}
                </span>
              ))}
          </li>
        ))}
      </ol>
      <More className="mt-0">
        {raw.map((l, i) => (
          <span key={i}>{withoutBatchTail(l)}</span>
        ))}
        {[...plan.refusals, ...plan.items.flatMap((x) => x.refusals)].map((r, i) => (
          <span key={`r${i}`}>
            {r.slug ? `${r.slug}: ` : ''}код {r.code}
            {r.line ? ` — ${withoutBatchTail(r.line)}` : ''}
          </span>
        ))}
        {plan.ledger ? <span>учёт ротации: {plan.ledger}</span> : null}
        <span>отпечаток данных {plan.base_sha256 ?? '—'}</span>
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** Итог «да»: что перенесено и что ушло в копилку; ролики в Studio — дату там руками. */
export function MoveDone({
  done,
  today,
  onClose,
}: {
  done: MoveDoneState;
  today: string;
  onClose: () => void;
}) {
  const { r, titleOf } = done;
  const parts = [
    r.moved ? `перенесено: ${videosWord(r.moved)}` : null,
    r.unplaced ? `в копилку: ${videosWord(r.unplaced)}` : null,
    r.withdrawn ? `снято из ленты: ${videosWord(r.withdrawn)}` : null,
  ].filter(Boolean);
  return (
    <Done
      tone={r.commit ? 'ok' : 'warn'}
      title={parts.length ? parts.join(', ').replace(/^./, (c) => c.toUpperCase()) : 'Перенесено'}
      testId="move-done"
      onClose={onClose}
    >
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {r.items
          .filter((i) => i.ok)
          .map((it) => (
            <li
              key={`${it.op}-${stashKeyOf(it)}`}
              data-testid="move-done-item"
              data-slug={it.slug}
              data-batch={it.batch_id ?? undefined}
            >
              {titleOf(it.slug, it.batch_id)}: {whereText(it, today)}
            </li>
          ))}
      </ul>
      <StudioHand items={r.items.filter((i) => i.ok)} titleOf={titleOf} today={today} done />
      <span data-testid="move-done-commit">
        {r.commit
          ? `Сохранено: ${r.touched.length} ${plural(r.touched.length, 'файл', 'файла', 'файлов')} публикации.`
          : 'Коммитить было нечего.'}
      </span>
      <More className="mt-0">
        {r.commit ? <span>коммит {r.commit}</span> : null}
        {r.items
          .filter((i) => i.journal)
          .map((i) => (
            <span key={`j${stashKeyOf(i)}`}>
              журнал {i.slug}: {i.journal!.from_at ?? '—'} → {i.journal!.to_at ?? '—'}
            </span>
          ))}
        {r.touched.map((f) => (
          <span key={f}>{withoutBatchTail(f)}</span>
        ))}
        {r.lines.map((l, i) => (
          <span key={`l${i}`}>{withoutBatchTail(l)}</span>
        ))}
      </More>
    </Done>
  );
}

const DESCRIPTION =
  'Фабрика проверила правки одним планом: порядок не важен, план исполняется только целиком. Это только план — ничего не изменится, пока вы не подтвердите.';

/** Подпись и поле выбора в одну колонку. */
function Labeled({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * Возврат ролика из запаса (CC-0180): перенос на выбранный день. Новой загрузки нет — ролик уже в
 * Studio; дату там ставит человек (блок «Дату в Studio поставить вручную» в плане и в итоге).
 */
export function ReturnFromReserve({
  channel,
  slug,
  batchId = null,
  title,
  days,
  placed,
  titleOf,
  today,
  lastDay,
  onDone,
}: {
  channel: string;
  slug: string;
  /** CC-0183: батч ролика, когда у него есть тёзка; иначе запрос прежний — только имя. */
  batchId?: string | null;
  title: string;
  /** Дни ленты впереди — куда можно вернуть. */
  days: string[];
  placed: Placed[];
  titleOf: NameOf;
  today: string;
  lastDay?: string | null;
  onDone: (d: MoveDoneState) => void;
}) {
  const [open, setOpen] = useState(false);
  const free = days.filter((d) => !placed.some((p) => p.day === d));
  const [picked, setPicked] = useState<string | null>(null);
  const day = picked ?? free.find((d) => !lastDay || d <= lastDay) ?? free[0] ?? days[0] ?? '';
  return (
    <div
      className="grid gap-2"
      data-testid="reserve-return"
      data-slug={slug}
      data-batch={batchId ?? undefined}
    >
      <WriteButton
        size="sm"
        variant="outline"
        aria-expanded={open}
        data-testid="reserve-return-toggle"
        tip="Выбрать день для ролика из запаса; план фабрики — до записи"
        onClick={() => setOpen(!open)}
        className="w-max"
      >
        Вернуть на день…
        <span aria-hidden>{open ? '▴' : '▾'}</span>
      </WriteButton>
      {open ? (
        <div
          className="grid gap-2.5 rounded-sm border p-3 text-[13px] sm:max-w-md"
          data-testid="reserve-return-form"
        >
          <Labeled label="Вернуть из запаса на день">
            {(id) => (
              <select
                id={id}
                data-testid="reserve-return-day"
                value={day}
                onChange={(e) => setPicked(e.target.value)}
                className={inputBase}
              >
                {days.map((d) => (
                  <option key={d} value={d}>
                    {dayChoice(d, today, placed, lastDay)}
                  </option>
                ))}
              </select>
            )}
          </Labeled>
          <span className="text-xs text-warning" data-testid="reserve-no-upload">
            Новой загрузки нет: ролик уже в Studio. Дату там поставьте вручную — центр её не меняет.
          </span>
          <MoveAction
            channel={channel}
            id="reserve-return"
            label="Проверить возврат…"
            title={`Вернуть «${title}» на ${day ? slotDay(day, today) : '…'}?`}
            description={DESCRIPTION}
            body={day ? { moves: [moveEdit(slug, day, batchId)], unplace: [] } : null}
            why={day ? null : 'В ленте нет дней впереди'}
            tip="Фабрика проверит возврат; запись и коммит — после вашего «да». Новой загрузки нет"
            confirmLabel="Вернуть"
            pendingLabel="Возвращаю…"
            view={(p) => (
              <MovePlanView
                plan={p}
                titleOf={titleOf}
                today={today}
                yes="можно вернуть"
                no="вернуть нельзя"
              />
            )}
            onDone={(r) => {
              setOpen(false);
              onDone({ r, titleOf });
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * У размещённого ролика: «Перенести…» (день — в форме под строкой), «Вернуть в копилку» и, у ролика
 * из Studio, «Снять из ленты в запас…» (CC-0180).
 */
export function RowMoves({
  channel,
  video,
  days,
  placed,
  titleOf,
  today,
  lastDay,
  open,
  onOpen,
  onDone,
}: {
  channel: string;
  video: Placed;
  /** Дни ленты впереди — куда можно перенести. */
  days: string[];
  placed: Placed[];
  titleOf: NameOf;
  today: string;
  /** Последний день горизонта ленты (CC-0180); null — горизонта нет. */
  lastDay?: string | null;
  open: boolean;
  onOpen: (open: boolean) => void;
  onDone: (d: MoveDoneState) => void;
}) {
  const choices = days.filter((d) => d !== video.day);
  const free = choices.find((d) => !placed.some((p) => p.day === d));
  const [day, setDay] = useState(free ?? choices[0] ?? '');
  const taken = placed.filter((p) => p.day === day);
  const when = slotDay(video.day, today);
  return (
    <div className="grid gap-2 pb-2.5 sm:pl-[7.25rem]" data-testid="slot-moves">
      <div className="flex flex-wrap items-center gap-2">
        <WriteButton
          size="sm"
          variant="outline"
          aria-expanded={open}
          data-testid="move-open"
          tip="Выбрать другой день для ролика; план фабрики — до записи"
          onClick={() => onOpen(!open)}
        >
          Перенести…
          <span aria-hidden>{open ? '▴' : '▾'}</span>
        </WriteButton>
        <MoveAction
          channel={channel}
          id="move-unplace"
          label="Вернуть в копилку"
          title={`Вернуть «${video.title}» в копилку?`}
          description={DESCRIPTION}
          body={{ moves: [], unplace: [moveName(video.slug, video.batchId)] }}
          why={
            video.inStudio
              ? 'Ролик уже в Studio — вернуть в копилку нельзя: можно перенести на другой день или снять из ленты в запас'
              : null
          }
          tip={`Ролик уйдёт из дня ${when} обратно в копилку и снова будет ждать слота; запись и коммит — после вашего «да»`}
          confirmLabel="Вернуть"
          view={(p) => <MovePlanView plan={p} titleOf={titleOf} today={today} />}
          onDone={(r) => onDone({ r, titleOf })}
          triggerVariant="ghost"
        />
        <MoveAction
          channel={channel}
          id="move-withdraw"
          label="Снять из ленты в запас…"
          title={`Снять «${video.title}» из ленты в запас?`}
          description={`Ролик уйдёт из дня ${when} в запас копилки. В Studio его снимаете вы: центр Studio не проверяет. ${DESCRIPTION}`}
          body={{ moves: [], unplace: [], withdraw: [moveName(video.slug, video.batchId)] }}
          why={
            video.inStudio
              ? null
              : 'Ролика нет в Studio — снимать из ленты нечего; его можно вернуть в копилку'
          }
          tip={`Ролик уйдёт из дня ${when} в запас копилки; в Studio его снимаете вы. Запись и коммит — после вашего «да»`}
          confirmLabel="Снять в запас"
          pendingLabel="Снимаю…"
          view={(p) => (
            <MovePlanView
              plan={p}
              titleOf={titleOf}
              today={today}
              yes="можно снять"
              no="снять нельзя"
            />
          )}
          onDone={(r) => onDone({ r, titleOf })}
          triggerVariant="ghost"
        />
      </div>
      {open ? (
        <div
          className="grid gap-2.5 rounded-sm border p-3 text-[13px] sm:max-w-md"
          data-testid="move-form"
        >
          <Labeled label={`Перенести с ${when} на день`}>
            {(id) => (
              <select
                id={id}
                data-testid="move-day"
                value={day}
                onChange={(e) => setDay(e.target.value)}
                className={inputBase}
              >
                {choices.map((d) => (
                  <option key={d} value={d}>
                    {dayChoice(d, today, placed, lastDay)}
                  </option>
                ))}
              </select>
            )}
          </Labeled>
          {lastDay && day > lastDay ? (
            <span className="text-xs text-muted-foreground" data-testid="move-day-beyond">
              Этот день дальше горизонта ленты: перенос запишется, как вы назвали — день ваш.
            </span>
          ) : null}
          {taken.length ? (
            <span className="text-xs text-muted-foreground" data-testid="move-day-taken">
              День занят — фабрика откажет, если его не освободить: проще сдвинуть очередь целиком
              («Сдвинуть очередь…» над лентой).
            </span>
          ) : null}
          {video.inStudio ? (
            <span className="text-xs text-warning" data-testid="move-row-studio">
              Ролик уже в Studio: после переноса дату там поставить вручную.
            </span>
          ) : null}
          <MoveAction
            channel={channel}
            id="move-one"
            label="Проверить перенос…"
            title={`Перенести «${video.title}» на ${day ? slotDay(day, today) : '…'}?`}
            description={DESCRIPTION}
            body={day ? { moves: [moveEdit(video.slug, day, video.batchId)], unplace: [] } : null}
            why={day ? null : 'Выберите день'}
            tip="Фабрика проверит перенос; запись и коммит — после вашего «да»"
            confirmLabel="Перенести"
            view={(p) => <MovePlanView plan={p} titleOf={titleOf} today={today} />}
            onDone={(r) => {
              onOpen(false);
              onDone({ r, titleOf });
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

/** «Сдвинуть очередь…»: все ролики с дня N — на день раньше или позже, одним планом. */
export function ShiftQueue({
  channel,
  channelName,
  placed,
  titleOf,
  today,
  onDone,
}: {
  channel: string;
  channelName: string;
  placed: Placed[];
  titleOf: NameOf;
  today: string;
  onDone: (d: MoveDoneState) => void;
}) {
  const [open, setOpen] = useState(false);
  const days = [...new Set(placed.map((p) => p.day))];
  const [fromRaw, setFrom] = useState(days[0] ?? '');
  const from = days.includes(fromRaw) ? fromRaw : (days[0] ?? '');
  const [by, setBy] = useState<-1 | 1>(-1);
  const [freeBefore, setFreeBefore] = useState(true);
  const panel = useId();
  const name = useId();
  if (!days.length) return null;
  const before = placed.filter((p) => p.day === addDay(from, -1));
  const studioBefore = before.some((p) => p.inStudio);
  const unplace = by === -1 && before.length > 0 && freeBefore && !studioBefore;
  const body = shiftBody(placed, from, by, unplace);
  const edits = body.moves.length + body.unplace.length;
  const shifted = placed.filter((p) => p.day >= from);
  const way = by === -1 ? 'на день раньше' : 'на день позже';
  return (
    <div className="mb-3 grid gap-2" data-testid="move-shift">
      <WriteButton
        size="sm"
        variant="outline"
        aria-expanded={open}
        aria-controls={panel}
        data-testid="move-shift-toggle"
        tip="Сдвинуть все ролики с выбранного дня на день раньше или позже — одним планом фабрики"
        onClick={() => setOpen(!open)}
        className="w-max"
      >
        Сдвинуть очередь…
        <span aria-hidden>{open ? '▴' : '▾'}</span>
      </WriteButton>
      {open ? (
        <div
          id={panel}
          data-testid="move-shift-form"
          className="grid gap-2.5 rounded-sm border p-3 text-[13px] sm:max-w-xl"
        >
          <Labeled label="Все ролики с дня">
            {(id) => (
              <select
                id={id}
                data-testid="move-shift-from"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className={inputBase}
              >
                {days.map((d) => (
                  <option key={d} value={d}>
                    {dayChoice(d, today, placed)}
                  </option>
                ))}
              </select>
            )}
          </Labeled>
          <div
            role="radiogroup"
            aria-label="Куда сдвинуть"
            className="flex flex-wrap gap-x-4 gap-y-1"
          >
            {(
              [
                [-1, 'на день раньше'],
                [1, 'на день позже'],
              ] as const
            ).map(([v, text]) => (
              <label key={v} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name={name}
                  data-testid={v === -1 ? 'move-shift-earlier' : 'move-shift-later'}
                  checked={by === v}
                  onChange={() => setBy(v)}
                />
                {text}
              </label>
            ))}
          </div>
          {by === -1 && before.length ? (
            <label className="flex items-start gap-2" data-testid="move-shift-free">
              <input
                type="checkbox"
                className="mt-0.5"
                data-testid="move-shift-unplace"
                checked={freeBefore && !studioBefore}
                disabled={studioBefore}
                onChange={(e) => setFreeBefore(e.target.checked)}
              />
              <span>
                {before.map((p) => `«${p.title}»`).join(', ')} ({slotDay(addDay(from, -1), today)})
                — вернуть в копилку, иначе этот день занят
                {studioBefore ? (
                  <span className="block text-xs text-warning" data-testid="move-shift-studio">
                    Уже в Studio — вернуть в копилку нельзя; фабрика откажет переносу на этот день.
                  </span>
                ) : null}
              </span>
            </label>
          ) : null}
          <div className="grid gap-0.5" data-testid="move-shift-preview">
            <span>
              Сдвинутся {way}: {videosWord(shifted.length)}
              {body.unplace.length ? `, в копилку — ${videosWord(body.unplace.length)}` : ''}
            </span>
            <span className="text-xs text-muted-foreground">
              {shifted
                .slice(0, 4)
                .map((p) => `${slotDay(p.day, today)} → ${slotDay(addDay(p.day, by), today)}`)
                .join(', ')}
              {shifted.length > 4 ? ` и ещё ${shifted.length - 4}` : ''}
            </span>
          </div>
          <MoveAction
            channel={channel}
            id="move-shift"
            label="Проверить сдвиг…"
            title={`Сдвинуть очередь ${channelName} с ${slotDay(from, today)} ${way}?`}
            description={DESCRIPTION}
            body={edits ? body : null}
            why={
              edits > MOVE_MAX_EDITS
                ? `Больше ${MOVE_MAX_EDITS} правок за раз фабрика не принимает — начните с более позднего дня`
                : edits
                  ? null
                  : 'Сдвигать нечего'
            }
            tip="Фабрика проверит все переносы одним планом; запись и коммит — после вашего «да»"
            confirmLabel="Сдвинуть"
            view={(p) => <MovePlanView plan={p} titleOf={titleOf} today={today} />}
            onDone={(r) => {
              setOpen(false);
              onDone({ r, titleOf });
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
