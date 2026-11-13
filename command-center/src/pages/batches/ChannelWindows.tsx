// Окна каналов (`GET`/`PUT /api/schedule/channels/{ch}`): участвует ли канал в расписании,
// начало и длительность окна, горизонт ленты и порог батча (CF-0922: горизонт — на сколько дней
// вперёд ставится лента, порог — батч, когда лента короче; порог не меньше горизонта, иначе
// фабрика отвечает 409 `refused` — форма предупреждает до сохранения). Это настройки пульта поверх конфига канала (не git):
// идущий батч их не блокирует. Проверяет фабрика: 422 `invalid` — её сообщение как есть;
// `changed: {}` — ничего не поменялось. Откуда значения (`source`/`overlay`) — под «подробнее».
import { useId, useState, type ReactNode } from 'react';

import { nbShort } from '@/api/humanText';
import {
  useChannelSchedule,
  useSaveChannelSchedule,
  type ChannelSchedule,
  type PlanChannel,
} from '@/api/schedule';
import { useWrites } from '@/api/writes';
import { Card } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { Avatar } from '@/pages/channels/identity';
import { cn } from '@/lib/utils';
import { inputBase } from '@/pages/channels/styles';

import { breakerText } from './breaker';
import { BREAKER_TIP, breakerBadge, changesText } from './format';
import {
  BATCH_FEED_DEFAULT,
  draftOf,
  editOf,
  thresholdBelow,
  thresholdOrigin,
  windowsList,
  type Draft,
  type ThresholdOrigin,
} from './windowDraft';
import { useChannelNames } from './names';
import { Refusal } from './parts';
import { SkeletonText } from '@/components/common/Skeletons';

const tzText = (tz: string | null | undefined) => (!tz || tz === 'Europe/Moscow' ? 'МСК' : tz);

function Field({
  label,
  tip,
  htmlFor,
  children,
  className,
}: {
  label: string;
  tip: string;
  htmlFor: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`grid min-w-0 content-start gap-1 ${className ?? ''}`}>
      <Tip content={tip} wide>
        <label
          htmlFor={htmlFor}
          tabIndex={0}
          className="w-max max-w-full text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
        >
          {label}
        </label>
      </Tip>
      {children}
    </div>
  );
}

function planBadge(p: PlanChannel | undefined) {
  if (!p) return null;
  if (p.plannable)
    return (
      <StatusBadge
        tone="ok"
        tip="Канал в плане: расписание планирует его батчи по окну и порогу батча"
      >
        в плане
      </StatusBadge>
    );
  if (p.no_pipeline)
    return (
      <StatusBadge tone="idle" tip="У канала нет конвейера — батча не будет, окно ждёт его">
        конвейера нет
      </StatusBadge>
    );
  return (
    <StatusBadge tone="warn" tip={p.why_not ?? 'План не берёт этот канал'}>
      вне плана
    </StatusBadge>
  );
}

/** Плашка размыкателя повторов у канала (CF-0822): метка и что держит, словами. */
function BreakerNote({ b }: { b: NonNullable<PlanChannel['breaker']> }) {
  const name = useChannelNames();
  const pill = breakerBadge(b);
  return (
    <div
      data-testid="win-breaker"
      data-held={b.held}
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-2.5 text-[13px]"
    >
      <StatusBadge
        tone={pill.tone}
        tip={BREAKER_TIP}
        className="w-max cursor-help underline decoration-current/80 decoration-dotted decoration-[length:1.5px] underline-offset-2"
      >
        {pill.label}
      </StatusBadge>
      <span className="text-muted-foreground" data-testid="win-breaker-text">
        {nbShort(breakerText(b, name))}
      </span>
    </div>
  );
}

/** Откуда порог батча — словами под полем (CC-0185). */
function originText(origin: ThresholdOrigin, raised: boolean): string {
  if (origin === 'center') return 'Задан в\u00a0центре';
  if (origin === 'channel') return 'Задан в\u00a0настройках канала';
  return raised ? 'По умолчанию фабрики\u00a0— поднят до горизонта ленты' : 'По умолчанию фабрики';
}

function WindowForm({
  id,
  data,
  save,
}: {
  id: string;
  data: ChannelSchedule;
  save: ReturnType<typeof useSaveChannelSchedule>;
}) {
  const s = data.settings;
  const [draft, setDraft] = useState<Draft>(() => draftOf(s));
  const uid = useId();
  const field = (k: keyof Draft) => `${uid}-${k}`;
  const initial = draftOf(s);
  const dirty =
    draft.enabled !== initial.enabled ||
    draft.window !== initial.window ||
    draft.window_hours !== initial.window_hours ||
    draft.min_feed_days !== initial.min_feed_days ||
    draft.batch_feed_days !== initial.batch_feed_days ||
    draft.windows !== initial.windows;
  // CF-0922: порог батча — в силе; откуда он и не ниже ли горизонта в черновике.
  const origin = thresholdOrigin(s);
  // Фабрика без порога (ключа нет, ошибки нет) — поля нет: она его не примет.
  const hasThreshold = origin != null || !!s.error;
  const below = hasThreshold ? thresholdBelow(draft, initial, origin) : null;
  // CF-0830: окна у канала уже есть — пустое поле их снимет; есть в черновике — перекрывают начало.
  const had = !!s.windows?.length;
  const many = windowsList(draft.windows).length > 0;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
    if (!save.isPending) save.reset();
  };
  const tz = tzText(s.tz);
  const writes = useWrites();

  return (
    <form
      noValidate
      aria-label={`Окно канала ${id}`}
      className="@container grid gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (writes.allowed) save.mutate(editOf(draft, had, initial));
      }}
    >
      {s.error ? (
        <ErrorState title="Настройки расписания канала не читаются">{s.error}</ErrorState>
      ) : null}
      <label className="flex items-center gap-2 text-[13px]">
        <input
          type="checkbox"
          data-testid="win-enabled"
          checked={draft.enabled}
          onChange={(e) => set('enabled', e.target.checked)}
          className="size-4 accent-[var(--primary)]"
        />
        <Tip content="Снимите — расписание не будет планировать батчи канала; запуск вручную останется">
          <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
            Участвует в расписании
          </span>
        </Tip>
      </label>
      <div className="grid grid-cols-1 gap-x-6 gap-y-3 @[20rem]:grid-cols-2">
        <Field
          label={`Начало окна, ${tz}`}
          tip={`С какого времени фабрика может начать батч канала. Время ЧЧ:ММ, от 00:00 до 23:59, часовой пояс канала (${s.tz ?? 'Europe/Moscow'})`}
          htmlFor={field('window')}
        >
          <input
            id={field('window')}
            data-testid="win-window"
            inputMode="numeric"
            placeholder="ЧЧ:ММ"
            value={draft.window}
            onChange={(e) => set('window', e.target.value)}
            className={cn(inputBase, many && 'opacity-60')}
          />
        </Field>
        <Field
          label="Длительность, ч"
          tip="Сколько часов после начала окна батч ещё можно начать: от 0.5 до 24, шаг 0.25"
          htmlFor={field('window_hours')}
        >
          <input
            id={field('window_hours')}
            data-testid="win-hours"
            type="number"
            inputMode="decimal"
            min={0.5}
            max={24}
            step={0.25}
            value={draft.window_hours}
            onChange={(e) => set('window_hours', e.target.value)}
            className={inputBase}
          />
        </Field>
        <Field
          label="Горизонт ленты, дн."
          tip="На сколько дней вперёд ставится лента: ролики встают в слоты публикации на столько дней от сегодня. Целое число от 1 до 30"
          htmlFor={field('min_feed_days')}
        >
          <input
            id={field('min_feed_days')}
            data-testid="win-feed"
            type="number"
            inputMode="numeric"
            min={1}
            max={30}
            step={1}
            value={draft.min_feed_days}
            onChange={(e) => set('min_feed_days', e.target.value)}
            className={inputBase}
          />
        </Field>
        {hasThreshold ? (
          <Field
            label="Порог батча, дн."
            tip="Батч запускается, когда лента короче: опубликованных вперёд роликов хватает меньше чем на столько дней. Целое число от 1 до 30, не меньше горизонта ленты"
            htmlFor={field('batch_feed_days')}
          >
            <input
              id={field('batch_feed_days')}
              data-testid="win-batch-feed"
              type="number"
              inputMode="numeric"
              min={1}
              max={30}
              step={1}
              value={draft.batch_feed_days}
              onChange={(e) => set('batch_feed_days', e.target.value)}
              aria-invalid={below ? true : undefined}
              aria-describedby={below ? `${uid}-below` : undefined}
              className={inputBase}
            />
            {origin ? (
              <span className="text-xs text-muted-foreground" data-testid="win-batch-origin">
                {originText(origin, (s.min_feed_days ?? 0) > BATCH_FEED_DEFAULT)}
              </span>
            ) : null}
          </Field>
        ) : null}
      </div>
      {below ? (
        <p
          id={`${uid}-below`}
          role="alert"
          data-testid="win-threshold-below"
          className="m-0 -mt-1.5 text-[13px] text-warning"
        >
          {`Порог батча ${below.threshold}\u00a0дн. меньше горизонта ленты ${below.horizon}\u00a0дн.\u00a0— фабрика такое не примет. Порог батча\u00a0— не меньше горизонта.`}
        </p>
      ) : null}
      {many ? (
        <p
          className="m-0 -mt-1.5 text-xs text-muted-foreground"
          data-testid="win-window-overridden"
        >
          Не действует: заданы окна
        </p>
      ) : null}
      <Field
        label={`Несколько окон, ${tz} — по желанию`}
        tip={`До 4 окон в сутки, время ЧЧ:ММ через запятую, например 05:30, 17:00. Если окна заданы, они заменяют «Начало окна»: батч может стартовать в любом из них, каждое длится «Длительность». Второй батч в те же сутки квоты будет, только если хватит бюджета поиска. Пустое поле — одно окно, как раньше`}
        htmlFor={field('windows')}
      >
        <input
          id={field('windows')}
          data-testid="win-windows"
          placeholder="ЧЧ:ММ, ЧЧ:ММ"
          value={draft.windows}
          onChange={(e) => set('windows', e.target.value)}
          className={inputBase}
        />
        <span className="text-xs text-muted-foreground" data-testid="win-windows-note">
          {many
            ? 'Окна заменяют «Начало окна»: батч может стартовать в любом из них'
            : had
              ? 'Окна снимутся\u00a0— снова одно окно с «Начала окна»'
              : 'Пусто\u00a0— одно окно с «Начала окна»'}
        </span>
      </Field>
      <Field
        label="Заметка — по желанию"
        tip="Почему меняете: останется в журнале настроек расписания"
        htmlFor={field('note')}
      >
        <input
          id={field('note')}
          data-testid="win-note"
          value={draft.note}
          onChange={(e) => set('note', e.target.value)}
          className={inputBase}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <WriteButton
          type="submit"
          variant="default"
          data-testid="win-save"
          disabled={save.isPending}
          aria-busy={save.isPending || undefined}
        >
          {save.isPending ? 'Сохраняю…' : 'Сохранить'}
        </WriteButton>
        {dirty ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft(draftOf(s));
              save.reset();
            }}
          >
            Вернуть как было
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function ChannelWindow({ id, planned }: { id: string; planned: PlanChannel | undefined }) {
  const name = useChannelNames()(id);
  const q = useChannelSchedule(id);
  const save = useSaveChannelSchedule(id);
  const result = save.data;
  const data = q.data;
  const s = data?.settings;
  return (
    <Card
      // Сюда ведёт «окно канала» из строки «вне расписания» плана недели (CC-0140).
      id={`window-${id}`}
      tabIndex={-1}
      aria-labelledby={`win-${id}`}
      data-testid={`window-${id}`}
      className="grid scroll-mt-4 content-start gap-3 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-center gap-3">
        <Avatar id={id} name={name} />
        <h3 id={`win-${id}`} className="min-w-0 flex-1 text-[15px] font-semibold">
          {name}
        </h3>
        {planBadge(planned)}
      </div>
      {planned?.breaker ? <BreakerNote b={planned.breaker} /> : null}
      {planned && !planned.plannable && planned.why_not ? (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="win-why-not">
          {planned.why_not}
        </p>
      ) : null}
      {q.isPending ? (
        <SkeletonText lines={3} lineHeight={32} label="Читаю настройки…" />
      ) : q.isError ? (
        <Refusal error={q.error} title="Настройки канала не прочитаны" />
      ) : (
        <WindowForm
          // Ответ фабрики с новыми значениями — форма с ними заново (черновик сохранён).
          key={JSON.stringify([
            s?.enabled,
            s?.window,
            s?.window_hours,
            s?.min_feed_days,
            s?.batch_feed_days,
            s?.windows,
          ])}
          id={id}
          data={q.data}
          save={save}
        />
      )}
      {save.isError ? <Refusal error={save.error} title="Не сохранено" /> : null}
      {result ? (
        Object.keys(result.changed).length ? (
          <div role="status" data-testid="win-saved" className="grid gap-0.5 text-[13px]">
            <span className="font-semibold text-success">Сохранено</span>
            {changesText(result.changed).map((c) => (
              <span key={c} className="text-muted-foreground">
                {c}
              </span>
            ))}
          </div>
        ) : (
          <p role="status" data-testid="win-unchanged" className="m-0 text-[13px]">
            Ничего не поменялось: значения те же, запись не сделана.
          </p>
        )
      ) : null}
      <More className="mt-0">
        <span>канал: {id}</span>
        {s?.source ? <span data-testid="win-source">откуда значения: {s.source}</span> : null}
        <span data-testid="win-overlay">
          пульт задал:{' '}
          {s?.overlay && Object.keys(s.overlay).length ? JSON.stringify(s.overlay) : 'ничего'}
        </span>
        {s?.tz ? <span>часовой пояс: {s.tz}</span> : null}
        {planned?.window ? <span>окно в плане: {planned.window}</span> : null}
        {planned?.min_feed_days != null || planned?.batch_feed_days != null ? (
          <span data-testid="win-plan-feed">
            в плане:{' '}
            {[
              planned.min_feed_days != null ? `горизонт ленты ${planned.min_feed_days} дн.` : null,
              planned.batch_feed_days != null ? `порог батча ${planned.batch_feed_days} дн.` : null,
            ]
              .filter(Boolean)
              .join(', ')}
          </span>
        ) : null}
        {planned?.breaker?.line ? <span>защита от повтора: {planned.breaker.line}</span> : null}
        {planned?.slot_rule ? <span>слоты публикации: {planned.slot_rule}</span> : null}
        {planned?.queue != null ? (
          <span>
            очередь: {planned.queue}, ждут: {planned.pending ?? 0}
          </span>
        ) : null}
        {data?.history.slice(0, 5).map((h, i) => (
          <span key={i}>
            {h.at} · {h.by}: {changesText(h.changes ?? {}).join('; ')}
            {h.note ? ` · ${h.note}` : ''}
          </span>
        ))}
      </More>
    </Card>
  );
}

export function ChannelWindows({ channels }: { channels: Record<string, PlanChannel> }) {
  const ids = Object.keys(channels);
  return (
    <section aria-labelledby="windows-title" data-testid="channel-windows" className="grid gap-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="eyebrow">Расписание каналов</div>
          <h2 id="windows-title" className="mt-0.5 text-[17px] font-semibold">
            Окна каналов
          </h2>
        </div>
        <p className="m-0 max-w-[60ch] text-[13px] text-muted-foreground sm:text-right">
          Когда фабрика может начать батч канала. Это настройки поверх конфига канала: идущий батч
          их не блокирует, план пересчитается сразу.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-gap md:grid-cols-3">
        {ids.map((id) => (
          <ChannelWindow key={id} id={id} planned={channels[id]} />
        ))}
      </div>
    </section>
  );
}
