// «Снятые за 14 дней (N)» в «Холдах публикации» (CC-0170, API CC-0169, фабрика 2.29 CF-0846):
// холды, снятые за окно (`GET /api/publish/holds/released?channel&days=14`), новые первыми.
// Фабрика сама снимает удержание, если флаг чувствительности стоит на сцене, которой нет в
// ролике, — строку («Удержание снято: флаг на s2, в ролике s1, подпись не нужна») пишет она же
// (`release.line_ru`), центр показывает её как есть. Снова поставленное правилом сцен
// (`state: reopened`) — с отметкой «снова стоит, нужна подпись»: оно же есть в открытых.
// Список свёрнут; реестр не читается (`problem`) — строка фабрики как есть.
import { useReleasedHolds, type ReleasedHold } from '@/api/publish';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';
import { plural } from '@/pages/batches/format';

import { HoldScenes } from './HoldScenes';

const REOPENED_TIP =
  'Правило сцен сняло удержание, а потом поставило обратно: сценарий взял сцену с флагом. Холд снова в открытых — его надо подписать';

const daysText = (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`;

function Released({ hold: h }: { hold: ReleasedHold }) {
  const r = h.release;
  const reopened = r.state === 'reopened';
  const where = [
    h.topic_id ? `тема ${h.topic_id}` : null,
    h.script_id ? `ролик ${h.script_id}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <li
      className="grid min-w-0 gap-0.5 border-t pt-2 first:border-t-0 first:pt-0"
      data-testid="hold-released"
      data-state={r.state}
    >
      <div className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
        <span
          className="min-w-0 font-medium [overflow-wrap:anywhere]"
          data-testid="hold-released-line"
        >
          {r.line_ru}
        </span>
        {reopened ? (
          <StatusBadge tone="warn" tip={REOPENED_TIP}>
            <span data-testid="hold-reopened">снова стоит, нужна подпись</span>
          </StatusBadge>
        ) : null}
      </div>
      <span
        className="text-xs text-muted-foreground [overflow-wrap:anywhere]"
        data-testid="hold-released-when"
      >
        {reopened ? 'снова поставлен' : 'снят'} {dateTimeMsk(r.at) ?? '—'}
        {where ? ` · ${where}` : ''}
      </span>
      <HoldScenes hold={h} />
      <More className="mt-0">
        {h.hold_id ? <span>холд: {h.hold_id}</span> : null}
        {h.batch_id ? <span>батч: {h.batch_id}</span> : null}
        {r.code ? <span>код: {r.code}</span> : null}
        {r.reason ? <span>фабрика: {r.reason}</span> : null}
        {r.scripts.length ? <span>сценарии: {r.scripts.join(', ')}</span> : null}
        {r.by ? <span>снял: {r.by}</span> : null}
        {r.task ? <span>задача: {r.task}</span> : null}
      </More>
    </li>
  );
}

export function ReleasedHolds({ channel }: { channel: string }) {
  const q = useReleasedHolds(channel);
  if (q.isPending) return null;
  if (q.isError)
    return (
      <p
        role="note"
        data-testid="holds-released-error"
        className="m-0 mt-3 text-[13px] text-muted-foreground"
      >
        Снятые холды не прочитать — проверьте, что API фабрики запущен.
      </p>
    );
  const d = q.data;
  if (d.problem)
    return (
      <p
        role="alert"
        data-testid="holds-released-problem"
        className="m-0 mt-3 text-[13px] text-muted-foreground [overflow-wrap:anywhere]"
      >
        Снятые за {daysText(d.days)} не прочитать: {d.problem}
      </p>
    );
  return (
    <details className="mt-3 min-w-0 text-[13px]" data-testid="holds-released" data-total={d.total}>
      <summary
        className="w-max max-w-full cursor-pointer text-primary-text"
        data-testid="holds-released-summary"
      >
        Снятые за {daysText(d.days)} ({d.total})
      </summary>
      {d.holds.length ? (
        <ul className="m-0 mt-2 grid min-w-0 list-none gap-2 p-0">
          {d.holds.map((h, i) => (
            <Released key={`${h.hold_id ?? i}-${h.release.state}`} hold={h} />
          ))}
        </ul>
      ) : (
        <p className="m-0 mt-2 text-muted-foreground" data-testid="holds-released-empty">
          За {daysText(d.days)} ни один холд не снят.
        </p>
      )}
      {d.total > d.holds.length ? (
        <p className="m-0 mt-2 text-xs text-muted-foreground">
          Показаны последние {d.holds.length} из {d.total}.
        </p>
      ) : null}
    </details>
  );
}
