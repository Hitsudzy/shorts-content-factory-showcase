// План батчей на неделю (`GET /api/schedule?days=7`): по дню — канал, окно, оценка конца
// и роликов, почему так; каналы вне расписания — почему (CC-0140). Оценки — оценки: с пометкой, на скольких
// прогонах они стоят (`est_*_n`; 0 — значения по умолчанию).
import { useChannels } from '@/api/channels';
import { nbShort } from '@/api/humanText';
import { usePublishOverview } from '@/api/publish';
import type { PlanDay, SchedulePlan } from '@/api/schedule';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';

import { ADMISSION_REASON, admissionText, type BudgetAdmission } from './budget';
import { dayWhy, perDayText } from './dayWhy';
import {
  dayLabel,
  dayPill,
  daysWord,
  durationText,
  estimateBasis,
  timeMsk,
  videosWord,
  dateTimeMsk,
} from './format';
import { useChannelNames, useChannelText } from './names';
import { OFF_REASON_TEXT, offSchedule } from './offSchedule';

/**
 * Оценка с пометкой, на чём она стоит, — тултипом. Пунктир серый, текст обычный: подсказка не
 * должна выглядеть ссылкой — сплошное жёлтое подчёркивание только у ссылок (CC-0146).
 */
function Estimate({
  children,
  n,
  testId,
}: {
  children: string;
  n: number | null | undefined;
  testId?: string;
}) {
  const basis = estimateBasis(n);
  if (!basis) return <span data-testid={testId}>{children}</span>;
  return (
    <Tip content={basis} side="top">
      <span
        tabIndex={0}
        data-testid={testId}
        data-basis={n && n > 0 ? 'runs' : 'default'}
        className="cursor-help underline decoration-muted-foreground decoration-dotted underline-offset-4"
      >
        {children}
        {n === 0 ? <span className="text-muted-foreground"> · по умолчанию</span> : null}
      </span>
    </Tip>
  );
}

/** Причина допуска второго батча (CF-0830): метка словами, расчёт и строка фабрики — рядом. */
function Admission({ a, testId }: { a: BudgetAdmission; testId: string }) {
  const r = ADMISSION_REASON[a.reason];
  return (
    <span data-testid={testId} data-reason={a.reason} className="text-muted-foreground">
      <span className={a.admitted ? 'text-success' : 'text-warning'}>
        {r ? r.label : nbShort(admissionText(a))}
      </span>
      {r ? nbShort(admissionText(a).slice(r.label.length)) : null}
    </span>
  );
}

/** Окно записи допуска «05:30» по МСК; конец, если известен — из окна дня. */
const admissionWindow = (a: BudgetAdmission) => timeMsk(a.window_start);

/**
 * Записи допуска дня, которые батча не дали (`budget`, `admitted: false`) и не показаны у батчей
 * дня. `quiet` — тот же канал в день, где батч уже был или сутки заняты: строка дня это уже
 * говорит, «ещё батча не будет» — под «Подробнее».
 */
function heldOf(d: PlanDay): { loud: BudgetAdmission[]; quiet: BudgetAdmission[] } {
  const shown = new Set(
    [d.budget_admission, ...(d.more ?? []).map((m) => m.budget_admission)]
      .filter(Boolean)
      .map((a) => `${a!.channel} ${a!.window_start}`),
  );
  const held = (d.budget ?? []).filter(
    (a) => !a.admitted && !shown.has(`${a.channel} ${a.window_start}`),
  );
  const quiet = (a: BudgetAdmission) => d.status !== 'planned' && a.channel === d.channel;
  return { loud: held.filter((a) => !quiet(a)), quiet: held.filter(quiet) };
}

/**
 * Следующие батчи дня (`more`, CF-0830): канал, окно, конец, ролики и причина допуска; записи
 * допуска, которые батча не дали и что-то добавляют к строке дня, — строкой «не будет».
 */
function MoreBatches({ d }: { d: PlanDay }) {
  const name = useChannelNames();
  const human = useChannelText();
  const more = d.more ?? [];
  const held = heldOf(d).loud;
  if (!more.length && !held.length) return null;
  return (
    <ul className="m-0 mt-1 grid list-none gap-1.5 p-0 text-[13px]" data-testid="day-more">
      {more.map((m, i) => {
        const start = timeMsk(m.window_start);
        const end = timeMsk(m.window_end);
        const finish = timeMsk(m.est_end);
        return (
          <li
            key={`${m.channel}-${m.window_start}-${i}`}
            data-testid="day-more-batch"
            data-channel={m.channel}
            className="grid gap-0.5 border-l-2 border-[color-mix(in_srgb,var(--success)_50%,var(--border))] pl-2.5"
          >
            <span>
              <span className="text-muted-foreground">Ещё батч: </span>
              <b className="font-semibold">{name(m.channel)}</b>
              {start && end ? <span>{` · окно ${start}–${end} МСК`}</span> : null}
              {finish ? (
                <Estimate n={m.est_wall_n} testId="day-more-end">
                  {` · конец ≈ ${finish}`}
                </Estimate>
              ) : null}
              {m.est_videos != null ? (
                <Estimate n={m.est_videos_n} testId="day-more-videos">
                  {` · ≈ ${videosWord(m.est_videos)}`}
                </Estimate>
              ) : null}
            </span>
            {m.budget_admission ? (
              <Admission a={m.budget_admission} testId="day-more-admission" />
            ) : null}
            {m.why || m.budget_admission?.why ? (
              <More className="mt-0">
                {m.why ? <span>фабрика: {human(m.why)}</span> : null}
                {m.budget_admission?.why ? (
                  <span>бюджет: {human(m.budget_admission.why)}</span>
                ) : null}
              </More>
            ) : null}
          </li>
        );
      })}
      {held.map((a, i) => {
        const at = admissionWindow(a);
        return (
          <li
            key={`held-${a.channel}-${a.window_start}-${i}`}
            data-testid="day-more-held"
            data-channel={a.channel}
            className="grid gap-0.5 border-l-2 border-[color-mix(in_srgb,var(--warning)_50%,var(--border))] pl-2.5"
          >
            <span>
              <span className="text-muted-foreground">Ещё батча не будет: </span>
              <b className="font-semibold">{name(a.channel)}</b>
              {at ? <span>{` · окно ${at} МСК`}</span> : null}
            </span>
            <Admission a={a} testId="day-more-admission" />
            {a.why ? (
              <More className="mt-0">
                <span>бюджет: {human(a.why)}</span>
              </More>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function DayRow({ d, plan }: { d: PlanDay; plan: SchedulePlan }) {
  const name = useChannelNames();
  const human = useChannelText();
  const label = dayLabel(d.day, plan.today);
  const st = dayPill(d);
  const start = timeMsk(d.window_start);
  const end = timeMsk(d.window_end);
  const finish = timeMsk(d.est_end);
  const wall = durationText(d.est_wall_s);
  // Причина — словами из `kind` и полей плана; строка фабрики и её заметки — под «Подробнее»
  // (CC-0146, CC-0147). У «некого планировать в этот день» заметки уже в причине словами, а
  // строка фабрики их перечисляет — отдельным списком второй раз не повторяем.
  const why = dayWhy(d, plan, name);
  const factory = d.why ? human(d.why) : null;
  const quietHeld = heldOf(d).quiet;
  // День под размыкателем (CF-0822) пересказывает запись `breaker`, а не заметки, — они под «Подробнее».
  const notes = (d.kind === 'nobody_available' && !d.breaker ? [] : (d.notes ?? [])).map(human);
  return (
    <li
      data-testid={`day-${d.day}`}
      data-status={d.status}
      data-kind={d.kind}
      className="grid grid-cols-[52px_minmax(0,1fr)] gap-3 border-t py-3 first:border-t-0 first:pt-0 sm:grid-cols-[64px_minmax(0,1fr)]"
    >
      <div className="grid content-start">
        <span className="font-display text-[20px] leading-none font-semibold uppercase">
          {label.weekday}
        </span>
        <span className="mt-1 font-mono text-xs text-muted-foreground">{label.date}</span>
        {label.rel ? <span className="text-xs text-primary-text">{label.rel}</span> : null}
      </div>
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap items-center gap-2">
          {/* У метки дня есть подсказка — пунктир, как у остальных подсказок (CC-0146). */}
          <StatusBadge
            tone={st.tone}
            tip={st.tip}
            className="cursor-help underline decoration-current/80 decoration-dotted decoration-[length:1.5px] underline-offset-2"
          >
            {st.label}
          </StatusBadge>
          {d.channel ? <span className="font-semibold">{name(d.channel)}</span> : null}
        </div>
        {d.status === 'planned' ? (
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px]">
            {start && end ? (
              <Tip content="Окно канала: расписание может начать батч только в эти часы (время московское)">
                <span tabIndex={0} data-testid="day-window">
                  окно {start}–{end} МСК
                </span>
              </Tip>
            ) : null}
            {finish && wall ? (
              <Estimate n={d.est_wall_n} testId="day-est-end">
                {`конец ≈ ${finish} (${wall.replace('≈ ', '')})`}
              </Estimate>
            ) : null}
            {d.est_videos != null ? (
              <Estimate n={d.est_videos_n} testId="day-est-videos">
                {`≈ ${videosWord(d.est_videos)}`}
              </Estimate>
            ) : null}
          </div>
        ) : null}
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="day-why">
          {nbShort(why.text)}
          {why.slot ? <span data-testid="day-slot">{`. ${nbShort(why.slot)}`}</span> : null}
          {why.covers ? <span data-testid="day-covers">{`. ${nbShort(why.covers)}`}</span> : null}
          {why.next ? <span data-testid="day-next">{`. ${nbShort(why.next)}`}</span> : null}
        </p>
        {d.status === 'planned' && d.budget_admission ? (
          <p className="m-0 text-[13px]">
            <span className="text-muted-foreground">Второй батч в сутки квоты: </span>
            <Admission a={d.budget_admission} testId="day-admission" />
          </p>
        ) : null}
        <MoreBatches d={d} />
        {d.fills?.length || factory || notes.length || d.breaker || quietHeld.length ? (
          <More className="mt-0.5">
            {factory ? <span data-testid="day-factory">фабрика: {factory}</span> : null}
            {d.breaker?.line ? (
              <span data-testid="day-breaker-line">защита от повтора: {human(d.breaker.line)}</span>
            ) : null}
            {quietHeld.map((a, i) => (
              <span key={`q-${a.channel}-${i}`} data-testid="day-held-quiet">
                {`ещё батча не будет: ${name(a.channel)}`}
                {admissionWindow(a) ? ` · окно ${admissionWindow(a)} МСК` : ''}
                {` · ${admissionText(a)}`}
                {a.why ? ` · бюджет: ${human(a.why)}` : ''}
              </span>
            ))}
            {d.budget_admission?.why ? <span>бюджет: {human(d.budget_admission.why)}</span> : null}
            {notes.length ? (
              <ul className="m-0 grid list-none gap-0.5 p-0" data-testid="day-notes">
                {notes.map((n, i) => (
                  <li key={i} className="before:mr-1.5 before:content-['·']">
                    {n}
                  </li>
                ))}
              </ul>
            ) : null}
            {d.fills?.length ? (
              <span>
                заполнит слоты: {d.fills.map((f) => dateTimeMsk(f) ?? f).join('; ')} (МСК)
              </span>
            ) : null}
            {d.fills?.length && d.window_start ? <span>окно с {d.window_start}</span> : null}
            {d.fills?.length && d.est_end ? <span>конец ≈ {d.est_end}</span> : null}
          </More>
        ) : null}
      </div>
    </li>
  );
}

/** К окну канала на этой же странице («Окна каналов»): прокрутить и поставить фокус. */
function toWindow(id: string) {
  const el = document.getElementById(`window-${id}`);
  if (!el) return;
  el.scrollIntoView({ block: 'start' });
  el.focus({ preventScroll: true });
}

/**
 * Каналы вне расписания батчей (CC-0140): план их не называет ни в одном дне — строка на
 * канал с причиной словами; строка фабрики как есть — под «подробнее».
 */
function OffPlan({ plan }: { plan: SchedulePlan }) {
  const name = useChannelNames();
  const human = useChannelText();
  const channels = useChannels();
  const publish = usePublishOverview();
  const off = offSchedule(plan, channels.data, publish.data);
  if (!off.length) return null;
  return (
    <div className="grid gap-1.5 border-t pt-3" data-testid="off-plan">
      <Tip content="Эти каналы план не берёт: для них батча по расписанию не будет, только вручную">
        <span tabIndex={0} className="eyebrow w-max">
          Вне расписания
        </span>
      </Tip>
      <ul className="m-0 grid list-none gap-1.5 p-0 text-[13px]">
        {off.map((c) => (
          <li key={c.id} data-testid={`why-not-${c.id}`} data-reason={c.reason}>
            <span className="font-semibold">{name(c.id)}</span>
            <span className="text-muted-foreground">
              {' '}
              — {c.reason === 'unknown' ? '' : 'вне расписания: '}
              <span data-testid="why-not-reason">{OFF_REASON_TEXT[c.reason]}</span>
            </span>
            {c.hasWindow ? (
              <>
                {' · '}
                <a
                  href={`#window-${c.id}`}
                  data-testid="why-not-window"
                  className="text-primary-text underline underline-offset-4"
                  onClick={(e) => {
                    e.preventDefault();
                    toWindow(c.id);
                  }}
                >
                  окно канала
                </a>
              </>
            ) : null}
            {c.factory ? (
              <More className="mt-0.5">
                <span>фабрика: {human(c.factory)}</span>
              </More>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function WeekPlan({ plan }: { plan: SchedulePlan }) {
  return (
    <Card aria-labelledby="plan-title" data-testid="week-plan" className="grid content-start gap-3">
      <CardHead
        eyebrow={`План на ${daysWord(plan.days.length)} · ${perDayText(plan.per_day)}`}
        title="План недели"
        titleId="plan-title"
        actions={
          <Tip content="Фабрика пересчитывает план каждый раз: лента публикаций, окна каналов, идущие батчи. Время — московское">
            <span tabIndex={0} className="font-mono text-xs text-muted-foreground">
              на {dateTimeMsk(plan.now) ?? plan.now}
            </span>
          </Tip>
        }
      />
      {plan.stale_open.length ? (
        <div
          role="status"
          data-testid="stale-open"
          className="rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-3 text-[13px]"
        >
          <div className="font-semibold text-warning">
            {plan.stale_open.length === 1
              ? 'Один открытый батч давно молчит'
              : `Открытых батчей давно молчат: ${plan.stale_open.length}`}
          </div>
          <p className="m-0 text-muted-foreground">
            Батч открыт, но старше потолка свежести: план его не считает идущим. Посмотрите, жив ли
            он, и закройте или продолжите.
          </p>
          <More className="mt-1">
            {plan.stale_open.map((b) => (
              <span key={b}>{b}</span>
            ))}
          </More>
        </div>
      ) : null}
      <ol className="m-0 grid list-none p-0">
        {plan.days.map((d) => (
          <DayRow key={d.day} d={d} plan={plan} />
        ))}
      </ol>
      <OffPlan plan={plan} />
    </Card>
  );
}
