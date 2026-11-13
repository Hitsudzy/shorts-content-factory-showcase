// Ролики канала с окном YouTube «первые 7 дней» (`GET …/metrics`): числа окна, окончательные
// они или ещё нет, «досмотрели» из Studio. Клик по ролику — его график по дням (`?video=`).
import type { MouseEvent } from 'react';
import { Link } from 'react-router';

import type { ChannelMetrics } from '@/api/analytics';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { useLiveSearchParams } from '@/lib/useLiveSearchParams';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';

import { METRIC, pct, publishedDay, shortDay, videoName, windowState } from './format';

const COLS = ['views', 'engagedViews', 'averageViewPercentage'] as const;

/** Щелчок, который `Link` обработал бы сам: левой кнопкой, без клавиш-модификаторов. */
const plainClick = (e: MouseEvent<HTMLAnchorElement>) =>
  e.button === 0 && !e.metaKey && !e.altKey && !e.ctrlKey && !e.shiftKey;

export function VideosTable({ m, selected }: { m: ChannelMetrics; selected: string | null }) {
  // CC-0163: ролик пишется в текущий адрес роутера, а не в отрисованный: иначе день, выбранный
  // перед этим до перерисовки, теряется. `to` — только для `href` ссылки (новая вкладка).
  const [params, setParams] = useLiveSearchParams();
  const to = (id: string) => {
    const p = new URLSearchParams(params);
    p.set('video', id);
    return { search: `?${p.toString()}` };
  };
  /** Как раньше: строка — новый шаг истории, ссылка — как `Link` (тот же адрес — замена). */
  const open = (id: string, replace = false) =>
    setParams(
      (p) => {
        p.set('video', id);
        return p;
      },
      { replace },
    );
  const rows = [...m.videos].sort((a, b) =>
    (publishedDay(b) ?? '').localeCompare(publishedDay(a) ?? ''),
  );
  return (
    <Card aria-labelledby="stats-videos-title" data-testid="stats-videos">
      <CardHead
        eyebrow={`Ролики · первые ${m.first_days} дней`}
        title="Числа роликов"
        titleId="stats-videos-title"
      />
      {!m.collected ? (
        <p
          data-testid="not-collected"
          className="m-0 mb-3 rounded-sm border border-dashed p-3 text-muted-foreground"
        >
          Окно первых {m.first_days} дней фабрика у YouTube для этого канала не спрашивает — чисел
          окна нет. Дневные строки есть: откройте ролик, чтобы увидеть просмотры по дням.
        </p>
      ) : null}
      {!rows.length ? (
        <EmptyState title="Роликов со статистикой пока нет">
          {m.last_run
            ? 'Сбор был, но ни по одному ролику YouTube ещё не дал чисел.'
            : 'Сбор статистики для канала ещё не запускался.'}
        </EmptyState>
      ) : (
        <div className="-mx-card overflow-x-auto px-card sm:mx-0 sm:px-0">
          <table className="w-full min-w-[560px] border-collapse text-left">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Ролик</th>
                {COLS.map((c) => (
                  <th key={c} className="py-2 pr-3 text-right font-medium">
                    <Tip content={METRIC[c]!.tip}>
                      <span tabIndex={0} className="cursor-help">
                        {METRIC[c]!.label}
                      </span>
                    </Tip>
                  </th>
                ))}
                <th className="py-2 pr-3 text-right font-medium">
                  <Tip content={METRIC.viewed_pct!.tip}>
                    <span tabIndex={0} className="cursor-help">
                      Досмотрели
                    </span>
                  </Tip>
                </th>
                <th className="py-2 font-medium">Числа</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => {
                const st = windowState(v, m.collected, m.first_days);
                const on = v.video_id === selected;
                const studio = v.studio;
                return (
                  <tr
                    key={v.video_id}
                    data-testid="stats-video"
                    data-video={v.video_id}
                    aria-current={on ? 'true' : undefined}
                    onClick={() => open(v.video_id)}
                    className={cn(
                      'cursor-pointer border-b last:border-b-0 hover:bg-muted',
                      on && 'bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]',
                    )}
                  >
                    <td className="py-2 pr-3">
                      <Link
                        to={to(v.video_id)}
                        className={cn('font-semibold', on && 'text-primary-text')}
                        onClick={(e) => {
                          e.stopPropagation();
                          // Обычный щелчок — сами, от текущего адреса; с Ctrl/⌘/Shift, средней
                          // кнопкой — браузеру (новая вкладка/окно) по `href`.
                          if (!plainClick(e)) return;
                          e.preventDefault();
                          open(v.video_id, on);
                        }}
                      >
                        {videoName(v.window ?? v.last_daily ?? v)}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        вышел {shortDay(publishedDay(v))}
                      </div>
                    </td>
                    {COLS.map((c) => (
                      <td key={c} className="py-2 pr-3 text-right font-mono tabular-nums">
                        {v.window ? METRIC[c]!.show(v.window[c]) : '—'}
                      </td>
                    ))}
                    <td className="py-2 pr-3 text-right font-mono tabular-nums">
                      {studio?.note ? (
                        <span className="font-sans text-xs text-muted-foreground">мало данных</span>
                      ) : (
                        pct(studio?.viewed_pct)
                      )}
                    </td>
                    <td className="py-2">
                      <StatusBadge tone={st.tone} tip={st.tip}>
                        {st.label}
                      </StatusBadge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <More>
        <span>
          GET /api/analytics/{m.channel}/metrics?first_days={m.first_days} · окна: first
          {m.window_days.join('d, first')}d · collected: {String(m.collected)}
        </span>
        {m.last_run ? (
          <span>
            сбор: {dateTimeMsk(String(m.last_run.collected_at ?? '')) ?? '—'} МСК · end_day{' '}
            {String(m.last_run.end_day ?? '—')} · outcome {String(m.last_run.outcome ?? '—')}
          </span>
        ) : null}
        {rows.map((v) => (
          <span key={v.video_id}>
            {v.video_id}: {v.window?.entry_id ?? v.last_daily?.entry_id ?? '—'} · дневных строк{' '}
            {v.daily_rows}
          </span>
        ))}
      </More>
    </Card>
  );
}
