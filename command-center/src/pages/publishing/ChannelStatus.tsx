// Состояние публикации канала: пауза (`…/pause`) — с записями «поставить/заменить/снять»
// (./PauseWrites, CC-0068), переключатель API-загрузки (`…/api-upload`, с тем, о чём предупредит
// включение; включить/выключить — ./SwitchWrites, CC-0069; история переключений —
// ./SwitchHistory, CC-0141), ротация паттернов (`…/rotation`) — с записями «назначить/
// отклонить/отказаться» (./RotationWrites, CC-0068) и серия роликов Studio без ручных правок
// (`…/studio`) — с отметкой «правил в Studio» и её отменой (./StudioEdited, CC-0115).
import type { ReactNode } from 'react';

import { BatchError } from '@/api/batchProblem';
import { useApiUpload, usePause, useRotation, useStudio } from '@/api/publish';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge, type Tone } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';

import { apiWarningText, pauseState, switchState } from './format';
import { PauseWrites } from './PauseWrites';
import { RotationWrites } from './RotationWrites';
import { StudioEdited } from './StudioEdited';
import { SwitchHistory } from './SwitchHistory';
import { SwitchWrites } from './SwitchWrites';
import { SkeletonText } from '@/components/common/Skeletons';

function Block({
  id,
  tour,
  title,
  badge,
  children,
}: {
  id: string;
  /** Метка тура «Обучение» (`data-tour`). */
  tour?: string;
  title: string;
  badge?: { label: string; tone: Tone; tip: string } | null;
  children: ReactNode;
}) {
  return (
    <section
      data-testid={`state-${id}`}
      data-tour={tour}
      aria-label={title}
      className="grid gap-1.5 border-t py-3 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {badge ? (
          <StatusBadge tone={badge.tone} tip={badge.tip}>
            {badge.label}
          </StatusBadge>
        ) : null}
      </div>
      <div className="grid gap-1 text-[13px] text-muted-foreground">{children}</div>
    </section>
  );
}

/** Отказ блока: словами — здесь, строка фабрики (она бывает и по-английски) — под «подробнее». */
function Failed({ error, what }: { error: unknown; what: string }) {
  const problem = error instanceof BatchError ? error.problem : null;
  return (
    <div role="alert" data-testid="state-failed">
      <p className="m-0 text-danger">
        {problem
          ? `Фабрика не может прочитать ${what}.`
          : 'Не прочитать — проверьте, что API фабрики запущен.'}
      </p>
      {problem ? (
        <More className="mt-1">
          <span>{problem.message}</span>
          {problem.details.map((d) => (
            <span key={d}>{d}</span>
          ))}
        </More>
      ) : null}
    </div>
  );
}

const loading = <SkeletonText lines={2} lineHeight={19.5} label="Читаю…" />;

function Pause({ channel }: { channel: string }) {
  const q = usePause(channel);
  const view = q.data ? pauseState(q.data) : null;
  return (
    <Block
      id="pause"
      tour="pause"
      title="Пауза публикаций"
      badge={
        view
          ? {
              ...view,
              tip: 'Пока стоит пауза, фабрика не ставит ролики в слоты, а завтрашний слот остаётся пустым',
            }
          : null
      }
    >
      {q.isPending ? (
        loading
      ) : q.isError ? (
        <Failed error={q.error} what="паузу канала" />
      ) : (
        <>
          <p className="m-0">{view!.text}</p>
          {q.data.row && q.data.state !== 'free' ? (
            <p className="m-0">
              с {dateTimeMsk(q.data.row.set_at) ?? q.data.row.set_at}
              {q.data.row.until
                ? ` до ${dateTimeMsk(q.data.row.until) ?? q.data.row.until}`
                : ' · без срока'}
            </p>
          ) : null}
          <More className="mt-1">
            <span>{q.data.line}</span>
            <span>реестр: {q.data.registry}</span>
            {q.data.row ? <span>пауза: {q.data.row.pause_id}</span> : null}
          </More>
          <PauseWrites channel={channel} pause={q.data} />
        </>
      )}
    </Block>
  );
}

function ApiSwitch({ channel }: { channel: string }) {
  const q = useApiUpload(channel);
  const st = q.data?.channels.find((c) => c.channel === channel) ?? q.data?.channels[0];
  const view = st ? switchState(st) : null;
  return (
    <Block
      id="api-upload"
      tour="api-switch"
      title="Загрузка через API YouTube"
      badge={
        view
          ? {
              ...view,
              tip: 'Переключатель загрузки программой; выключен — ролики грузите вы через Studio',
            }
          : null
      }
    >
      {q.isPending ? (
        loading
      ) : q.isError ? (
        <Failed error={q.error} what="переключатель загрузки" />
      ) : (
        <>
          <p className="m-0">{view?.text ?? 'Состояния переключателя нет.'}</p>
          {q.data.warnings?.length ? (
            <div data-testid="api-warnings" className="grid gap-1">
              <span>Если включить, фабрика предупредит:</span>
              <ul className="m-0 grid list-disc gap-1 pl-5">
                {q.data.warnings.map((w) => (
                  <li key={w} className="text-warning [overflow-wrap:anywhere]">
                    {apiWarningText(w)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {st ? <SwitchHistory rows={st.history ?? []} /> : null}
          <More className="mt-1">
            {st ? <span>{st.line}</span> : null}
            {st?.error ? <span>{st.error}</span> : null}
            {q.data.warnings_error ? <span>{q.data.warnings_error}</span> : null}
            {q.data.warnings?.map((w) => (
              <span key={`raw-${w}`}>{w}</span>
            ))}
            <span>файл: {q.data.path}</span>
          </More>
          {st ? <SwitchWrites channel={channel} state={st} /> : null}
        </>
      )}
    </Block>
  );
}

function Rotation({ channel }: { channel: string }) {
  const q = useRotation(channel);
  const r = q.data?.report;
  return (
    <Block
      id="rotation"
      tour="rotation"
      title="Ротация паттернов"
      badge={
        r
          ? r.constrained
            ? {
                label: 'урезана',
                tone: 'warn',
                tip: 'Части пар паттернов не хватает материала: ротация идёт по меньшему кругу',
              }
            : { label: 'полная', tone: 'ok', tip: 'Ротация идёт по всем разрешённым парам' }
          : null
      }
    >
      {q.isPending ? (
        loading
      ) : q.isError ? (
        <Failed error={q.error} what="ротацию канала (у канала может не быть её настроек)" />
      ) : (
        <>
          <p className="m-0">
            В круге {r!.k_effective} из {r!.k_configured} пар паттернов · доступно{' '}
            {r!.eligible_pairs.length}, заблокировано {r!.blocked_by.length}
          </p>
          <p className="m-0">
            Разброс за последние {r!.window}: {r!.spread}
            {r!.awaiting_material.length
              ? ` · тем ждут материала: ${r!.awaiting_material.length}`
              : ''}
          </p>
          <More className="mt-1">
            <span>доступны: {r!.eligible_pairs.join(', ') || '—'}</span>
            {Object.entries(r!.blocked_pairs).map(([k, why]) => (
              <span key={k}>
                {k}: {why ?? 'заблокирована'}
              </span>
            ))}
            {Object.entries(r!.counts_in_window).map(([k, n]) => (
              <span key={k}>
                {k}: {n}
              </span>
            ))}
            {r!.awaiting_material.map((a) => (
              <span key={`${a.batch_id}/${a.script_id}`}>
                ждёт: {a.script_id} ({a.state}){a.retry_when ? ` — ${a.retry_when}` : ''}
              </span>
            ))}
            <span>журнал: {q.data.ledger}</span>
          </More>
          <RotationWrites channel={channel} />
        </>
      )}
    </Block>
  );
}

function Streak({ channel }: { channel: string }) {
  const q = useStudio(channel);
  const s = q.data?.streak;
  return (
    <Block
      id="studio"
      title="Studio без ручных правок"
      badge={
        s
          ? s.done
            ? { label: 'цель взята', tone: 'ok', tip: 'Нужная серия роликов без правок набрана' }
            : {
                label: `${s.streak} из ${s.goal}`,
                tone: 'idle',
                tip: 'Сколько роликов подряд вы загрузили через Studio, не поправив поля руками',
              }
          : null
      }
    >
      {q.isPending ? (
        loading
      ) : q.isError ? (
        <Failed error={q.error} what="журнал загрузок" />
      ) : (
        <>
          <p className="m-0">
            Подряд без правок: {s!.streak} из {s!.goal} · всего через Studio: {s!.studio_videos}
          </p>
          {s!.last_edited ? (
            <p className="m-0">
              Последняя правка: {dateTimeMsk(String(s!.last_edited.at ?? '')) ?? 'дата не записана'}
            </p>
          ) : null}
          <More className="mt-1">
            <span>журнал: {q.data.journal}</span>
            {s!.run.length ? <span>серия: {s!.run.join(', ')}</span> : null}
            {s!.last_edited ? <span>{JSON.stringify(s!.last_edited)}</span> : null}
          </More>
          <StudioEdited channel={channel} streak={s!} />
        </>
      )}
    </Block>
  );
}

export function ChannelStatus({ channel }: { channel: string }) {
  return (
    <Card aria-labelledby="status-title" data-testid="channel-status">
      <CardHead
        eyebrow="Состояние канала"
        title="Пауза, загрузка, ротация"
        titleId="status-title"
      />
      <Pause channel={channel} />
      <ApiSwitch channel={channel} />
      <Rotation channel={channel} />
      <Streak channel={channel} />
    </Card>
  );
}
