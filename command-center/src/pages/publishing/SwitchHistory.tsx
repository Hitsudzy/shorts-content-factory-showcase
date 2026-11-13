// История переключателя API-загрузки (CC-0141): последние строки `history` из
// `GET /api/publish/{c}/api-upload` (`ApiSwitchRow`: когда, кто, что, заметка, предупреждения) —
// свёрнуто под «История переключений», новые сверху. В пульте 2.2 это было, в центре — с 1.0.1.
import { dateTimeMsk } from '@/pages/batches/format';

import {
  latestSwitches,
  switchAction,
  switchWho,
  type SwitchHistoryRow,
} from './switchHistoryWords';

export function SwitchHistory({ rows }: { rows: readonly SwitchHistoryRow[] }) {
  const shown = latestSwitches(rows);
  return (
    <details data-testid="switch-history" className="mt-1 text-xs text-muted-foreground">
      <summary className="w-max cursor-pointer text-primary-text">История переключений</summary>
      {shown.length ? (
        <ol className="m-0 mt-1.5 grid list-none gap-2 p-0">
          {shown.map((r, i) => {
            const warn = r.warnings?.length ?? 0;
            return (
              <li
                key={`${r.at ?? ''}-${i}`}
                data-testid="switch-history-row"
                className="grid gap-0.5 border-t pt-2 [overflow-wrap:anywhere] first:border-t-0 first:pt-0"
              >
                <span>
                  <span className="text-foreground">{dateTimeMsk(r.at) ?? 'дата не записана'}</span>
                  {' · '}
                  {switchWho(r.by)}
                  {' · '}
                  <span className="font-medium text-foreground">{switchAction(r.action)}</span>
                  {warn > 0 ? (
                    <span className="text-warning"> · предупреждений: {warn}</span>
                  ) : null}
                </span>
                {r.note?.trim() ? <span>«{r.note.trim()}»</span> : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="m-0 mt-1.5" data-testid="switch-history-empty">
          переключений не было
        </p>
      )}
      {rows.length > shown.length ? (
        <p className="m-0 mt-1.5">
          показаны последние {shown.length} из {rows.length}
        </p>
      ) : null}
    </details>
  );
}
