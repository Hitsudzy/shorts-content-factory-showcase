// Кинолента батча (макет «Кинозал»): кадры стадий в порядке плана прогона (CC-0090), сколько
// их в плане — столько колонок. Плёнка всегда тёмная; до 64rem (телефон, планшет) —
// вертикальная, у ждущих кадров подпись прячется (как в макете). Условный кадр «Добор» —
// пунктиром. Кадр, до которого упавший батч не дошёл, — серым, без ✓ (CC-0095).
// CC-0126: состояние кадра видно и без цвета — значок у номера (✓ ▶ ○ ✕ ❚❚ –) и рамка
// (готово — сплошная «ок», пропущено — пунктир); у готового — «готово · 1 ч 05 мин» по пролётам
// стадий (`…/stages`); плёнка между кадрами — пройденный участок толще и цвета «ок». Вид — в
// src/index.css (`.film-frame[data-state]`), значок «идёт» не мигает при «меньше движения».
import type { CSSProperties } from 'react';

import type { StageSpan } from '@/api/batches';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import { clockSpan, frameSpent, spareText, type Frame, type FrameState } from './going';
import type { FrameKind } from './stages';

const SMALL: Record<FrameState, string> = {
  done: 'готово',
  now: 'идёт',
  wait: 'ждёт',
  part: '',
  skip: 'не в этом прогоне',
  bad: 'ошибка',
  stopped: 'остановлено',
  opt: 'только если нужно',
  unneeded: 'не понадобился',
  unreached: 'не дошёл',
};

/** Подпись этих состояний видна и на телефоне. */
const NOTE = new Set<FrameState>(['done', 'part', 'opt', 'unneeded', 'unreached']);

/** Кадры, которые батч прошёл насквозь: плёнка от них — пройденная, если следующий достигнут. */
const THROUGH = new Set<FrameState>(['done', 'part', 'unneeded', 'skip']);
/** Куда плёнка ведёт пройденной: в пройденный кадр или в идущий/остановленный. В упавший и в
 * недостигнутый — нет (CC-0126, ревью экранов). */
const INTO = new Set<FrameState>([...THROUGH, 'now', 'stopped']);
/** Стадии этих кадров не запускались — итогов у них нет. */
const NO_RESULT = new Set<FrameState>(['wait', 'skip', 'opt', 'unreached']);

/**
 * `frames` — из `framesOf`; `nowText` — подпись идущего кадра (сколько идёт стадия), только у
 * состояния «идёт»: у упавшего и остановленного — их слово («ошибка», «остановлено», CC-0095);
 * `note` — строка под подписью текущего кадра (почему стоит, CC-0094); `progress` — доля
 * потолка стадии (0…1) для полоски идущего кадра; `summaries` — итог законченного этапа по
 * виду кадра (CC-0092: «нашёл 3 темы, 3 отсеял»), он виден и на телефоне; `onSummary` — клик по
 * итогу (к темам батча); `spans` — пролёты стадий (`…/stages`): длительность готовых кадров.
 */
export function FilmStrip({
  frames,
  nowText,
  note,
  progress,
  className,
  label = 'Стадии батча',
  summaries,
  onSummary,
  spans,
}: {
  frames: Frame[];
  nowText?: string | null;
  note?: string | null;
  progress?: number | null;
  className?: string;
  label?: string;
  summaries?: Partial<Record<FrameKind, string[]>>;
  onSummary?: () => void;
  spans?: readonly StageSpan[] | null;
}) {
  /**
   * Итог вида — у последнего запускавшегося кадра этого вида. Кадр «не понадобился» итог у
   * прежнего кадра вида не забирает: так «темы на замену» не уходят в пропущенный раунд добора
   * после отказа судьи кадра (CC-0150).
   */
  const lastOf = new Map<FrameKind, number>();
  for (const f of frames) {
    if (NO_RESULT.has(f.state)) continue;
    if (f.state === 'unneeded' && lastOf.has(f.kind)) continue;
    lastOf.set(f.kind, f.n);
  }
  /** Плёнка от кадра `i` пройдена: он пройден насквозь, а следующий батч достиг. */
  const passed = (i: number) => {
    const next = frames[i + 1];
    return THROUGH.has(frames[i]!.state) && !!next && INTO.has(next.state);
  };
  return (
    <ol
      aria-label={label}
      data-testid="film-strip"
      data-tour="stages"
      style={{ '--film-cols': `repeat(${frames.length}, minmax(0, 1fr))` } as CSSProperties}
      className={cn(
        'film-strip m-0 grid list-none grid-cols-1 gap-2 rounded-sm px-4 py-2.5 lg:grid-cols-(--film-cols) lg:px-2.5 lg:py-[18px]',
        className,
      )}
    >
      {frames.map((f, i) => {
        const live = f.state === 'now' || f.state === 'stopped' || f.state === 'bad';
        const spent = clockSpan(frameSpent(f, spans));
        const small =
          f.state === 'part'
            ? `${f.done} из ${f.total} шагов`
            : f.state === 'done'
              ? `${f.empty ? 'нечего проверять' : f.more ? 'готово, возможен добор' : 'готово'}${spent ? ` · ${spent}` : ''}`
              : f.state === 'now'
                ? `${f.returned ? 'добор · ' : ''}${nowText ?? 'идёт'}`
                : SMALL[f.state];
        const why = f.current && note ? note : null;
        const sum = lastOf.get(f.kind) === f.n ? summaries?.[f.kind] : undefined;
        const sumLines = sum?.length
          ? sum.map((line) => (
              <span key={line} className="block">
                {line}
              </span>
            ))
          : null;
        const first = f.returned && f.done > 0 && !f.judge;
        return (
          <li
            key={f.n}
            data-state={f.state}
            data-kind={f.kind}
            data-link={i < frames.length - 1 ? (passed(i) ? 'passed' : 'ahead') : undefined}
            data-returned={f.returned || undefined}
            data-empty={f.empty || undefined}
            aria-current={f.state === 'now' ? 'step' : undefined}
            className={cn(
              'film-frame relative grid grid-cols-[40px_1fr] gap-x-2 rounded-[3px] px-2.5 py-2 lg:flex lg:min-h-[86px] lg:flex-col lg:gap-[3px] lg:p-2.5',
              f.kind === 'extra' && f.state !== 'done' && 'border-dashed! border-film-extra-line!',
            )}
          >
            <span className="film-num row-span-2 font-mono text-[10.5px] whitespace-nowrap">
              {String(f.n).padStart(2, '0')}
            </span>
            <b className="film-title min-w-0 text-[13px] font-semibold hyphens-auto">{f.title}</b>
            {f.returned ? (
              <Tip
                content={
                  first
                    ? `Батч вернулся в этот этап за добором: фабрика запускает его, только когда основного не хватило. Первый проход${spent ? ` шёл ${spent}` : ' закончен'} — готовое сохранено.`
                    : f.judge
                      ? 'Добор после отказа судьи кадра: фабрика запускает эти шаги, только когда судья кадра отказал роликам'
                      : 'Добор: фабрика запускает эти шаги, только когда основного не хватило'
                }
              >
                <small
                  tabIndex={0}
                  data-testid="frame-small"
                  className="film-small w-max max-w-full text-[11.5px] leading-[1.35] underline decoration-dotted underline-offset-2"
                >
                  {small}
                </small>
              </Tip>
            ) : (
              <small
                data-testid="frame-small"
                className={cn(
                  'film-small text-[11.5px] leading-[1.35]',
                  !live && !NOTE.has(f.state) && 'hidden lg:block',
                )}
              >
                {small}
              </small>
            )}
            {first ? (
              <span
                data-testid="frame-first"
                className="film-aside col-start-2 text-[11px] leading-[1.35]"
              >
                первый проход готов
              </span>
            ) : null}
            {f.state === 'done' && f.spare ? (
              <span
                data-testid="frame-spare"
                className="film-aside col-start-2 text-[11px] leading-[1.35]"
              >
                {spareText(f.spare)}
              </span>
            ) : null}
            {why ? (
              <small
                data-testid="frame-note"
                className="col-start-2 text-[11.5px] leading-[1.35] text-[#c8c8d4]"
              >
                {why}
              </small>
            ) : null}
            {sumLines ? (
              onSummary ? (
                <Tip content="Показать темы батча: что нашёл и решил этот этап">
                  <button
                    type="button"
                    data-testid="frame-summary"
                    onClick={onSummary}
                    className="col-start-2 grid cursor-pointer gap-0.5 text-left text-[11.5px] leading-[1.35] text-[#c8c8d4] underline decoration-[#6a6a7e] decoration-dotted underline-offset-2 hover:text-[#ffe23d] focus-visible:text-[#ffe23d]"
                  >
                    {sumLines}
                  </button>
                </Tip>
              ) : (
                <small
                  data-testid="frame-summary"
                  className="col-start-2 grid gap-0.5 text-[11.5px] leading-[1.35] text-[#c8c8d4]"
                >
                  {sumLines}
                </small>
              )
            ) : null}
            {f.state === 'now' && progress != null ? (
              <span
                aria-hidden
                className="col-start-2 mt-1 block h-[3px] overflow-hidden rounded-[2px] bg-[#2a2a38] lg:mt-auto"
              >
                <i
                  className="block h-full bg-[#ffe23d]"
                  style={{ width: `${Math.round(Math.min(1, Math.max(0, progress)) * 100)}%` }}
                />
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
