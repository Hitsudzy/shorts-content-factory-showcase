// «Вопросы» (CC-0017): вопросы фабрики к вам из журнала CF-0652 (`GET /api/questions`).
// Сверху — ждущие ответа (новые первыми), под ними — с отправленным ответом, ниже — история
// решённых (`?status=resolved`, новые первыми, по 10). Ответ — прямо в карточке, «решено» —
// одно подтверждение. Фильтры по источнику и каналу — в адресе (`?source=…&channel=…`).
// Номера, ключи событий и имена скриптов — только под «подробнее». Переключатель «Просьбы»
// (`?view=requests`, CC-0019) показывает здесь же ваши просьбы оператору и его ответы.
import { useState } from 'react';
import { useSearchParams } from 'react-router';

import { useOpenCount, useQuestions, type Question } from '@/api/questions';
import { useAnsweredCount } from '@/api/requests';
import { Card, CardHead } from '@/components/common/Card';
import { CountBadge } from '@/components/common/CountBadge';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { useLiveSearchParams } from '@/lib/useLiveSearchParams';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';
import { inputBase } from '@/pages/channels/styles';

import { historyOrder, liveOrder, matches, NO_CHANNEL, sourceName } from './format';
import { HistoryItem, QuestionCard } from './QuestionCard';
import { Requests } from './Requests';
import { SkeletonRows } from '@/components/common/Skeletons';

/** Сколько решённых показывать за раз. */
const HISTORY_PAGE = 10;

function Filters({
  all,
  source,
  channel,
  onChange,
  channelName,
}: {
  all: Question[];
  source: string;
  channel: string;
  onChange: (next: { source?: string; channel?: string }) => void;
  channelName: (id: string) => string;
}) {
  const sources = [...new Set(all.map((q) => q.source))].sort((a, b) =>
    sourceName(a).localeCompare(sourceName(b), 'ru'),
  );
  const channels = [...new Set(all.map((q) => q.channel ?? NO_CHANNEL))].sort((a, b) =>
    a === NO_CHANNEL ? 1 : b === NO_CHANNEL ? -1 : channelName(a).localeCompare(channelName(b)),
  );
  const pick = (
    key: 'source' | 'channel',
    label: string,
    value: string,
    options: { value: string; label: string }[],
    tip: string,
  ) => (
    <label className="grid min-w-0 gap-1 text-[13px] sm:w-[16rem]">
      <span className="text-muted-foreground">{label}</span>
      <Tip content={tip}>
        <select
          data-testid={`filter-${key}`}
          value={value}
          onChange={(e) => onChange({ [key]: e.target.value })}
          className={inputBase}
        >
          <option value="">{key === 'source' ? 'Все источники' : 'Все каналы'}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Tip>
    </label>
  );
  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="filters">
      {pick(
        'source',
        'Кто спросил',
        source,
        sources.map((s) => ({ value: s, label: sourceName(s) })),
        'Показать вопросы одного источника: публикатора, аналитика, охотника за трендами…',
      )}
      {pick(
        'channel',
        'Канал',
        channel,
        channels.map((c) => ({
          value: c,
          label: c === NO_CHANNEL ? 'Без канала (общие)' : channelName(c),
        })),
        'Показать вопросы одного канала или общие, без канала',
      )}
      {source || channel ? (
        <Button
          variant="ghost"
          data-testid="filters-reset"
          onClick={() => onChange({ source: '', channel: '' })}
        >
          Сбросить фильтры
        </Button>
      ) : null}
    </div>
  );
}

/** Пока список читается — скелетон карточек вопросов (CC-0121); `children` — для читалки. */
function Loading({ children, height = 88 }: { children: string; height?: number }) {
  return <SkeletonRows rows={3} height={height} gap={10} label={children} />;
}

function History({
  source,
  channel,
  channelName,
}: {
  source: string;
  channel: string;
  channelName: (id: string) => string;
}) {
  const q = useQuestions('resolved');
  const [shown, setShown] = useState(HISTORY_PAGE);
  const list = (q.data?.questions ?? [])
    .filter((x) => matches(x, source, channel))
    .sort(historyOrder);
  return (
    <Card aria-labelledby="history-title" data-testid="history">
      <CardHead
        eyebrow={q.data ? `История · решено: ${list.length}` : 'История'}
        title="Решено раньше"
        titleId="history-title"
      />
      {q.isPending ? (
        <Loading>Читаю историю…</Loading>
      ) : q.isError ? (
        <ErrorState title="Историю не прочитать" error={q.error} onRetry={() => void q.refetch()}>
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : !list.length ? (
        <EmptyState title={source || channel ? 'Под фильтр ничего не попало' : 'Решённых пока нет'}>
          {source || channel
            ? 'Среди решённых нет вопросов этого источника или канала.'
            : 'Здесь соберутся вопросы, которые вы или фабрика отметили решёнными.'}
        </EmptyState>
      ) : (
        <>
          <ul className="m-0 grid list-none p-0">
            {list.slice(0, shown).map((x) => (
              <HistoryItem key={x.id} q={x} channelName={channelName} />
            ))}
          </ul>
          {list.length > shown ? (
            <div className="mt-2">
              <Button
                size="sm"
                data-testid="history-more"
                onClick={() => setShown((n) => n + HISTORY_PAGE)}
              >
                Показать ещё {Math.min(HISTORY_PAGE, list.length - shown)}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

type View = 'questions' | 'requests';

/** Переключатель «Вопросы» / «Просьбы»; выбранное — в адресе (`?view=requests`). */
function ViewSwitch({ view, onPick }: { view: View; onPick: (v: View) => void }) {
  const questions = useOpenCount();
  const answered = useAnsweredCount();
  const item = (v: View, label: string, n: number | null, countLabel: string, tip: string) => (
    <Tip content={tip}>
      <button
        type="button"
        data-testid={`view-${v}`}
        aria-pressed={view === v}
        onClick={() => onPick(v)}
        className={cn(
          'inline-flex h-9 items-center gap-1.5 rounded-sm px-3 text-[13px] text-muted-foreground transition-colors hover:text-foreground',
          view === v &&
            'bg-card font-semibold text-foreground shadow-[inset_0_0_0_1px_var(--border)]',
        )}
      >
        {label}
        <CountBadge n={n} label={countLabel} small />
      </button>
    </Tip>
  );
  return (
    <div
      role="group"
      aria-label="Что показать"
      data-testid="view-switch"
      data-tour="requests-switch"
      className="inline-flex w-max gap-1 rounded-md border bg-[color-mix(in_srgb,var(--muted-foreground)_6%,transparent)] p-1"
    >
      {item(
        'questions',
        'Вопросы',
        questions,
        'ждут ответа',
        'Вопросы фабрики к вам: ответить, отметить решённым',
      )}
      {item(
        'requests',
        'Просьбы',
        answered,
        'пришёл ответ',
        'Ваши просьбы оператору: что с ними и что он ответил',
      )}
    </div>
  );
}

export function Questions() {
  const [params, setParams] = useSearchParams();
  const view: View = params.get('view') === 'requests' ? 'requests' : 'questions';
  const pick = (v: View) => setParams(v === 'requests' ? { view: v } : {}, { replace: true });
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">
            {view === 'requests'
              ? 'Вы просите — оператор делает'
              : 'Фабрика спрашивает — вы решаете'}
          </div>
          <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
            Вопросы
          </h1>
        </div>
        <ViewSwitch view={view} onPick={pick} />
      </div>
      {view === 'requests' ? <Requests /> : <QuestionsView />}
    </>
  );
}

function QuestionsView() {
  const live = useQuestions('live');
  const resolved = useQuestions('resolved');
  const channelName = useChannelNames();
  // CC-0162: запись — от текущего адреса роутера. Функция в `setSearchParams` получает
  // параметры последней отрисовки: второй выбор до перерисовки стирал первый.
  const [params, setParams] = useLiveSearchParams();
  const source = params.get('source') ?? '';
  const channel = params.get('channel') ?? '';
  const onChange = (change: { source?: string; channel?: string }) =>
    setParams((next) => {
      for (const [key, value] of Object.entries(change)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      return next;
    });

  const all = [...(live.data?.questions ?? []), ...(resolved.data?.questions ?? [])];
  const shown = (live.data?.questions ?? [])
    .filter((q) => matches(q, source, channel))
    .sort(liveOrder);
  const open = shown.filter((q) => q.status === 'open');
  const answered = shown.filter((q) => q.status === 'answered');
  const totalOpen = live.data?.questions.filter((q) => q.status === 'open').length ?? 0;

  return (
    <>
      <Card aria-labelledby="questions-summary-title" data-testid="questions-summary">
        <CardHead
          eyebrow="Журнал вопросов"
          titleId="questions-summary-title"
          title={
            live.data
              ? totalOpen
                ? `Ждут вашего ответа: ${totalOpen}`
                : 'Ответов от вас фабрика не ждёт'
              : 'Читаю журнал…'
          }
        />
        <p className="m-0 mb-3 text-muted-foreground">
          Ответ записывается в журнал фабрики, и его читает тот, кто спросил. Новые вопросы фабрика
          сама присылает в Telegram.
        </p>
        <Filters
          all={all}
          source={source}
          channel={channel}
          onChange={onChange}
          channelName={channelName}
        />
      </Card>

      {live.isPending ? (
        <Loading height={180}>Читаю вопросы…</Loading>
      ) : live.isError ? (
        <ErrorState
          title="Вопросы не прочитать"
          error={live.error}
          onRetry={() => void live.refetch()}
        >
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : !shown.length ? (
        <EmptyState
          title={source || channel ? 'Под фильтр ничего не попало' : 'Вопросов к вам нет'}
        >
          {source || channel
            ? 'Открытых вопросов этого источника или канала нет — сбросьте фильтры.'
            : 'Когда фабрике понадобится ваше решение, вопрос появится здесь и придёт в Telegram.'}
        </EmptyState>
      ) : (
        <>
          {open.length ? (
            <div className="grid gap-2.5" data-testid="open-questions">
              <h2 className="eyebrow">Ждут ответа · {open.length}</h2>
              <div className="grid gap-gap md:grid-cols-2">
                {open.map((q) => (
                  <QuestionCard key={q.id} q={q} channelName={channelName} />
                ))}
              </div>
            </div>
          ) : null}
          {answered.length ? (
            <div className="grid gap-2.5" data-testid="answered-questions">
              <h2 className="eyebrow">Ответ отправлен · {answered.length}</h2>
              <div className="grid gap-gap md:grid-cols-2">
                {answered.map((q) => (
                  <QuestionCard key={q.id} q={q} channelName={channelName} />
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}

      <History source={source} channel={channel} channelName={channelName} />
    </>
  );
}
