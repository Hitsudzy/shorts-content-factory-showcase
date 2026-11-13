// Данные API по каналам — словами: у каждого канала, что из него хранится (или удалится). Пути,
// строки `describe` фабрики и id роликов — под «подробнее» у того, кто показывает план.
import { byChannel, type ApiDataPlan } from '@/api/oauth';
import { More } from '@/components/common/More';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';

import { shareLines } from './format';

export function Shares({
  plan,
  testId,
  className,
}: {
  plan: ApiDataPlan;
  testId: string;
  className?: string;
}) {
  const shares = byChannel(plan);
  const name = useChannelNames();
  return (
    <ul className={cn('m-0 grid list-none gap-2 p-0', className)} data-testid={testId}>
      {shares.map((s) => (
        <li
          key={s.channel ?? '—'}
          data-testid="oauth-share"
          data-channel={s.channel ?? ''}
          className="grid gap-1 rounded-sm border px-3 py-2"
        >
          <b className="font-semibold">{s.channel ? name(s.channel) : 'Общее для фабрики'}</b>
          <ul className="m-0 grid list-disc gap-0.5 pl-4 text-[13px]">
            {shareLines(s, plan).map((l) => (
              <li key={l} className="[overflow-wrap:anywhere]">
                {l}
              </li>
            ))}
          </ul>
          {s.rows.length || s.texts.length || s.files.length || s.dirs.length ? (
            <More className="mt-0">
              {s.rows.map((r, i) => (
                <span key={`r${i}`}>
                  {r.slug ?? '—'}
                  {r.video_id ? ` · ${r.video_id}` : ''}
                  {r.entry_id ? ` · ${r.entry_id}` : ''}
                </span>
              ))}
              {s.texts.map((t, i) => (
                <span key={`t${i}`}>
                  {t.file} · {t.video_id}
                </span>
              ))}
              {[...s.files, ...s.dirs].map((f) => (
                <span key={f}>{f}</span>
              ))}
            </More>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
