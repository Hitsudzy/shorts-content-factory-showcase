// «Журнал уведомлений»: что фабрика вам отправила — сверху новые (API отдаёт новые в конце), с
// фильтром по виду и каналу и «показать все» (по умолчанию — последние 20, как `notify.py list`).
// У строки — когда, вид, канал, текст, ссылка и что ответил каждый канал доставки (строка
// бэкенда — в тултипе). Ключ события, ссылка-путь и строки бэкендов — под «подробнее»; многострочный
// текст для Telegram (`body`, CC-0188) — простым текстом под своим свёрнутым «Подробнее».
import { useId, useState } from 'react';

import { useChannels } from '@/api/channels';
import { JOURNAL_LIMIT, notifyCode, useJournal, type NotifyEvent } from '@/api/notify';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';
import { inputBase } from '@/pages/channels/styles';
import { Loaded } from '@/components/common/Loaded';

import { backendLabel, backendResult, eventBody, KIND, kindLabel, whenText } from './format';

const isUrl = (s: string | null | undefined): s is string => !!s && /^https?:\/\//.test(s);

function EventRow({ e }: { e: NotifyEvent }) {
  const name = useChannelNames();
  const kind = e.kind ? KIND[e.kind] : undefined;
  const backends = Object.entries(e.backends ?? {});
  const body = eventBody(e);
  return (
    <li
      data-testid="notify-event"
      data-kind={e.kind ?? ''}
      className="grid gap-1.5 border-b py-2.5 last:border-b-0"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          {whenText(e.at) ?? '—'}
        </span>
        <StatusBadge
          tone={e.kind === 'run_halted' ? 'warn' : 'idle'}
          tip={kind?.tip}
        >
          {kindLabel(e.kind)}
        </StatusBadge>
        <span className="text-xs text-muted-foreground">
          {e.channel ? name(e.channel) : 'вся фабрика'}
        </span>
      </div>
      <p className="m-0 [overflow-wrap:anywhere]">{e.text ?? '—'}</p>
      {body ? (
        <More className="mt-0" label="Подробнее: текст для Telegram">
          <span
            data-testid="notify-event-body"
            className="font-sans text-[13px] whitespace-pre-wrap text-foreground"
          >
            {body}
          </span>
        </More>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {backends.map(([b, v]) => {
          const r = backendResult(v);
          return (
            <span
              key={b}
              className="inline-flex items-center gap-1 text-xs"
              data-testid="notify-backend"
              data-backend={b}
            >
              <span className="text-muted-foreground">{backendLabel(b)}:</span>
              <StatusBadge tone={r.tone} tip={String(v)}>
                {r.label}
              </StatusBadge>
            </span>
          );
        })}
        {isUrl(e.link) ? (
          <a
            href={e.link}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary-text underline-offset-4 hover:underline"
          >
            Открыть пульт
          </a>
        ) : null}
      </div>
      <More className="mt-0">
        <span>ключ: {e.key ?? '—'}</span>
        {e.link ? <span>ссылка: {e.link}</span> : null}
        <span>at: {e.at ?? '—'}</span>
        {backends.map(([b, v]) => (
          <span key={b}>
            {b}: {String(v)}
          </span>
        ))}
      </More>
    </li>
  );
}

function Picker({
  label,
  value,
  onChange,
  options,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testId: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="grid min-w-0 flex-1 basis-40 gap-1 text-[13px]">
      <span className="text-xs text-muted-foreground">{label}</span>
      <select
        id={id}
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputBase}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Journal() {
  const [kind, setKind] = useState('');
  const [channel, setChannel] = useState('');
  const [all, setAll] = useState(false);
  const q = useJournal({
    kind: kind || null,
    channel: channel || null,
    limit: all ? 0 : JOURNAL_LIMIT,
  });
  const channels = useChannels();
  const kinds = q.data?.kinds ?? Object.keys(KIND);
  const filtered = !!(kind || channel);
  return (
    <Card aria-labelledby="notify-journal-title" data-testid="notify-journal">
      <CardHead
        eyebrow="Что фабрика вам отправила · сверху — новые"
        title="Журнал уведомлений"
        titleId="notify-journal-title"
        actions={
          <Tip content={`Без этого — последние ${JOURNAL_LIMIT}`}>
            <Button
              size="sm"
              variant={all ? 'default' : 'ghost'}
              aria-pressed={all}
              data-testid="notify-journal-all"
              onClick={() => setAll(!all)}
            >
              Показать все
            </Button>
          </Tip>
        }
      />
      <div className="mb-3 flex flex-wrap gap-2" data-testid="notify-journal-filters">
        <Picker
          label="Вид"
          value={kind}
          onChange={setKind}
          testId="notify-journal-kind"
          options={[
            { value: '', label: 'Все виды' },
            ...kinds.map((k) => ({ value: k, label: kindLabel(k) })),
          ]}
        />
        <Picker
          label="Канал"
          value={channel}
          onChange={setChannel}
          testId="notify-journal-channel"
          options={[
            { value: '', label: 'Все каналы и вся фабрика' },
            ...(channels.data ?? []).map((c) => ({
              value: c.id,
              label: c.display_name ?? c.id,
            })),
          ]}
        />
      </div>
      <Loaded
        q={q}
        reading="Читаю журнал уведомлений…"
        failed={
          notifyCode(q.error) === 'bad_kind'
            ? 'Такого вида уведомлений у фабрики нет'
            : 'Журнал уведомлений не прочитать'
        }
      >
        {(d) =>
          d.events.length ? (
            <>
              <ul
                className={cn('m-0 list-none p-0', q.isPlaceholderData && 'opacity-60')}
                data-testid="notify-events"
              >
                {[...d.events].reverse().map((e, i) => (
                  <EventRow key={`${e.key ?? ''}-${e.at ?? ''}-${i}`} e={e} />
                ))}
              </ul>
              <p
                className="m-0 mt-2 text-xs text-muted-foreground"
                data-testid="notify-journal-count"
              >
                {d.events.length < d.total
                  ? `Показаны последние ${d.events.length} из ${d.total}.`
                  : `Всего ${d.total}.`}
              </p>
              <More>
                <span>{d.path}</span>
              </More>
            </>
          ) : (
            <EmptyState
              title={filtered ? 'Таких уведомлений нет' : 'Фабрика ещё ничего не отправляла'}
            >
              {filtered
                ? 'Выберите другой вид или канал выше. Уведомления про всю фабрику (токен, напоминания) — без канала.'
                : 'Здесь появится каждое уведомление: ролик ждёт «да», батч остановился, срок токена, напоминание.'}
            </EmptyState>
          )
        }
      </Loaded>
    </Card>
  );
}
