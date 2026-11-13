// «Данные API»: что фабрика хранит из YouTube API (метрики Analytics, API-поля журнала публикаций,
// id роликов в текстах) — по каналам и словами; строка состояния фабрики (`api_data.py status`):
// отзыва нет / Google отказал токену — когда всё удалится и предел политики / уже удалены; правила
// политики (сроки); что удалил бы авто-прогон сейчас и «Удалить по сроку» (CC-0087, API CC-0082) —
// план фабрики и «да», в журнал удалений — «вы, из центра». «Удалить данные API» по просьбе
// владельца — план фабрики и «да» (`WriteAction`, как записи публикации): окно перечисляет по
// каналам, что удалится, и что остаётся — токен YouTube и цифры из Studio. Переключатель загрузки
// через API — на экране «Публикация» (ссылка), здесь не дублируется.
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';

import {
  oauthProblemText,
  planAuto,
  planPurge,
  planSize,
  purgeApiData,
  runAuto,
  useAfterPurge,
  useApiData,
  type ApiDataAutoPlan,
  type ApiDataAutoResult,
  type ApiDataPurgeIn,
  type ApiDataPurgePlan,
  type ApiDataPurgeResult,
  type ApiDataState,
} from '@/api/oauth';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge, type Tone } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { whoText } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { usePlanFailed } from '@/pages/publishing/planFailed';
import { Check, Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';
import { Loaded } from '@/components/common/Loaded';

import { channelsWord, dayText, dueReason, itemsWord } from './format';
import { Shares } from './Shares';

const KIND: Record<ApiDataState['kind'], { label: string; tone: Tone; tip: string }> = {
  ok: { label: 'в порядке', tone: 'ok', tip: 'Отзыва нет, записи журнала обновляются вовремя' },
  warn: {
    label: 'есть что обновить',
    tone: 'warn',
    tip: 'Часть записей давно не обновлялась — или данные уже удалены после отзыва доступа',
  },
  bad: {
    label: 'к удалению',
    tone: 'danger',
    tip: 'Google отказал токену: по политике YouTube API данные API надо удалить в срок',
  },
};

/** Главная строка блока — словами, по отметке отзыва. */
function Headline({ d }: { d: ApiDataState }) {
  const rev = d.revocation;
  if (rev?.deleted)
    return (
      <>
        Данные API удалены {dayText(String(rev.deleted.at ?? ''), d.now) ?? ''} после отзыва доступа
        — сбор метрик стоит до нового входа в Google
      </>
    );
  if (rev)
    return (
      <>
        Google отказал токену {dayText(rev.revoked_at, d.now)} — данные API удалятся{' '}
        {dayText(rev.due_at, d.now)}, предел политики — {dayText(rev.deadline, d.now)}. Новый вход
        снимет отметку
      </>
    );
  return <>Отзыва доступа нет</>;
}

function Rules({ d }: { d: ApiDataState }) {
  const r = d.rules;
  return (
    <p className="m-0 text-xs text-muted-foreground" data-testid="oauth-rules">
      <Tip
        wide
        content="Политика разработчиков YouTube API: данные, полученные через API, нельзя хранить дольше срока и после отзыва доступа"
      >
        <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
          Правила политики
        </span>
      </Tip>
      : после отзыва доступа фабрика удаляет данные API через {r.purge_after_days} дней (предел —{' '}
      {r.retention_days}); записи журнала обновляются раз в {r.refresh_days} дней, не обновлённые{' '}
      {r.stale_days} дней — удаляются.
    </p>
  );
}

function AutoPlanView({ plan, staleDays }: { plan: ApiDataAutoPlan; staleDays: number }) {
  const failed = usePlanFailed();
  return (
    <>
      <PlanHead plan={plan} yes="можно удалить" no="удалять нечего" />
      {plan.due.map((p, i) => (
        <div key={i} className="grid gap-1.5" data-testid="oauth-auto-plan-part">
          <span>
            {failed ? 'Ничего не удалено. По сроку удалилось бы' : 'Удалится'} —{' '}
            {dueReason(p.reason, staleDays).toLowerCase()}: {itemsWord(planSize(p))}
          </span>
          <Shares plan={p} testId="oauth-auto-shares" />
        </div>
      ))}
      <p className="m-0 text-xs text-muted-foreground">
        То же удалила бы сама фабрика при следующем сборе метрик — сейчас удалит по вашему «да».
        Удаляет: {whoText(plan.by) ?? plan.by}, из центра — так и запишется в журнал удалений.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · by {plan.by} · via {plan.via}
        </span>
        {plan.due.map((p, i) => (
          <span key={i}>reason: {p.reason}</span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function AutoDone({ result, onClose }: { result: ApiDataAutoResult; onClose: () => void }) {
  const n = result.done.reduce((a, x) => a + planSize(x.plan), 0);
  return (
    <Done tone="ok" testId="oauth-auto-done" title="Удалено по сроку" onClose={onClose}>
      <span>
        Удалено {itemsWord(n)}. В журнале удалений — {result.done.length}{' '}
        {result.done.length === 1 ? 'запись' : 'записи'}: вы, из центра.
      </span>
      <More className="mt-0">
        <span>журнал удалений: {result.log}</span>
        {result.done.map((x, i) => (
          <span key={i}>{JSON.stringify(x.record)}</span>
        ))}
      </More>
    </Done>
  );
}

function AutoRun({ d }: { d: ApiDataState }) {
  const [done, setDone] = useState<ApiDataAutoResult | null>(null);
  const after = useAfterPurge();
  return (
    <div className="grid gap-2" data-testid="oauth-auto">
      <div>
        <WriteAction
          id="oauth-auto"
          label="Удалить по сроку…"
          title="Удалить данные API по сроку?"
          description="Фабрика составила план — вот что подлежит удалению по правилам политики сейчас."
          body={d.due.length ? true : null}
          why={d.due.length ? null : 'По сроку удалять нечего'}
          tip="Фабрика покажет, что подлежит удалению по сроку; удалит — после вашего «да»"
          confirmLabel="Удалить"
          pendingLabel="Удаляю…"
          danger
          plan={() => planAuto()}
          act={runAuto}
          view={(p) => <AutoPlanView plan={p} staleDays={d.rules.stale_days} />}
          problemText={oauthProblemText}
          onSettled={after}
          onDone={setDone}
        />
      </div>
      {done ? <AutoDone result={done} onClose={() => setDone(null)} /> : null}
    </div>
  );
}

function Due({ d }: { d: ApiDataState }) {
  return (
    <div className="grid gap-2" data-testid="oauth-due">
      <b className="text-sm font-semibold">Что удалит авто-прогон сейчас</b>
      {d.due.length ? (
        <>
          {d.due.map((p, i) => (
            <div key={i} className="grid gap-1.5" data-testid="oauth-due-plan">
              <span className="text-[13px]">{dueReason(p.reason, d.rules.stale_days)}:</span>
              <Shares plan={p} testId="oauth-due-shares" />
              <More className="mt-0">
                <span>reason: {p.reason}</span>
                {p.lines.map((l, j) => (
                  <span key={j}>{l}</span>
                ))}
              </More>
            </div>
          ))}
          <p className="m-0 text-xs text-muted-foreground">
            Удалит сама фабрика при следующем сборе метрик — или сейчас, по кнопке.
          </p>
        </>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="oauth-due-none">
          Авто-прогону сейчас удалять нечего.
        </p>
      )}
      <AutoRun d={d} />
    </div>
  );
}

function PurgePlanView({ plan }: { plan: ApiDataPurgePlan }) {
  const p = plan.plan;
  const failed = usePlanFailed();
  return (
    <>
      <PlanHead plan={plan} yes="можно удалить" no="удалять нечего" />
      {plan.ok ? (
        <>
          <p className="m-0" data-testid="oauth-purge-size">
            {failed ? 'Ничего не удалено. По плану удалилось бы' : 'Удалится'}{' '}
            <b className="font-semibold">{itemsWord(planSize(p))}</b> —{' '}
            {channelsWord(p.channels.length)}:
          </p>
          <Shares plan={p} testId="oauth-purge-shares" />
        </>
      ) : null}
      <div className="grid gap-0.5 text-[13px]" data-testid="oauth-purge-kept">
        <b className="font-semibold">Останется</b>
        <span>Токен YouTube — доступ не отзывается, загрузка и сбор метрик идут дальше.</span>
        <span>Цифры из Studio, которые вы вносили руками, — их правила API не касаются.</span>
        <span>Остальное в записях журнала публикаций: день, слот, название.</span>
      </div>
      <p className="m-0 text-xs text-muted-foreground">
        Удаляет: {whoText(plan.by) ?? plan.by}, из центра — так и запишется в журнал удалений.
        Вернуть удалённое нельзя; метрики снова соберутся при следующем сборе.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · scope {plan.scope}
          {plan.asked ? ` · ${plan.asked.join(', ')}` : ''} · by {plan.by} · via {plan.via}
        </span>
        <span>reason: {p.reason}</span>
        <span>журнал: {p.journal}</span>
        {p.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function PurgeDone({ result, onClose }: { result: ApiDataPurgeResult; onClose: () => void }) {
  const p = result.plan;
  const name = useChannelNames();
  const ref = useRef<HTMLDivElement>(null);
  // Итог — посреди длинной карточки: подвести его в поле зрения (отступ под липкой шапкой).
  useEffect(() => ref.current?.scrollIntoView?.({ block: 'nearest' }), []);
  return (
    <div ref={ref} className="scroll-mt-36">
      <Done tone="ok" testId="oauth-purge-done" title="Данные API удалены" onClose={onClose}>
        <span>
          Удалено {itemsWord(planSize(p))}: {p.channels.map(name).join(', ')}. Токен YouTube на
          месте — сбор метрик идёт дальше.
        </span>
        <More className="mt-0">
          <span>журнал удалений: {result.log}</span>
          {Object.entries(result.record).map(([k, v]) => (
            <span key={k}>
              {k}: {typeof v === 'string' ? v : JSON.stringify(v)}
            </span>
          ))}
        </More>
      </Done>
    </div>
  );
}

function Purge({ d }: { d: ApiDataState }) {
  const held = d.held.channels;
  const name = useChannelNames();
  const [all, setAll] = useState(true);
  const [picked, setPicked] = useState<string[]>([]);
  const [done, setDone] = useState<ApiDataPurgeResult | null>(null);
  const after = useAfterPurge();
  const chosen = picked.filter((c) => held.includes(c));
  const why = d.held.empty
    ? 'Удалять нечего — фабрика не хранит данных API'
    : !all && !chosen.length
      ? 'Отметьте каналы, данные API которых удалить'
      : null;
  const body: ApiDataPurgeIn = all
    ? { scope: 'all', channels: [] }
    : { scope: 'channels', channels: chosen };
  return (
    <div className="grid gap-2.5 rounded-sm border p-3" data-testid="oauth-purge">
      <b className="text-sm font-semibold">Удалить данные API</b>
      <p className="m-0 text-[13px]">
        По вашей просьбе фабрика удалит то, что получила из YouTube API. Токен и цифры из Studio
        останутся.
      </p>
      {held.length ? (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-2"
          data-testid="oauth-purge-scope"
        >
          <Check
            label="Все каналы"
            checked={all}
            onChange={setAll}
            testId="oauth-purge-all"
            tip="Снимите, чтобы выбрать каналы"
          />
          {!all
            ? held.map((c) => (
                <Check
                  key={c}
                  label={name(c)}
                  checked={chosen.includes(c)}
                  onChange={(v) =>
                    setPicked((p) =>
                      v ? [...p.filter((x) => x !== c), c] : p.filter((x) => x !== c),
                    )
                  }
                  testId={`oauth-purge-ch-${c}`}
                />
              ))
            : null}
        </div>
      ) : null}
      <div>
        <WriteAction
          id="oauth-purge"
          label="Удалить…"
          title="Удалить данные API?"
          description="Фабрика составила план — вот что удалится и что останется."
          body={why ? null : body}
          why={why}
          tip="Фабрика покажет по каналам, что удалится; удалит — после вашего «да»"
          confirmLabel="Удалить"
          pendingLabel="Удаляю…"
          danger
          plan={planPurge}
          act={purgeApiData}
          view={(p) => <PurgePlanView plan={p} />}
          problemText={oauthProblemText}
          onSettled={after}
          onDone={(r) => {
            setDone(r);
            setPicked([]);
            setAll(true);
          }}
        />
      </div>
      {done ? <PurgeDone result={done} onClose={() => setDone(null)} /> : null}
    </div>
  );
}

function ApiDataView({ d }: { d: ApiDataState }) {
  const k = KIND[d.kind];
  const staleTail = /; (\d+) не обновлялись/.exec(d.line)?.[1];
  return (
    <div className="grid gap-3.5" data-testid="oauth-api-data-view" data-kind={d.kind}>
      <div className="grid gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={k.tone} tip={k.tip}>
            <span data-testid="oauth-api-data-kind">{k.label}</span>
          </StatusBadge>
          <b className="font-semibold [overflow-wrap:anywhere]" data-testid="oauth-api-data-head">
            <Headline d={d} />
          </b>
        </div>
        {staleTail && !d.revocation ? (
          <span className="text-[13px] text-warning" data-testid="oauth-api-data-stale">
            Не обновлялись {d.rules.refresh_days}+ дней: {staleTail} — фабрика обновит их при сборе
            метрик, не обновлённые {d.rules.stale_days} дней удалит.
          </span>
        ) : null}
        {d.config_error ? (
          <span className="text-[13px] text-warning" data-testid="oauth-config-error">
            Настройки публикатора не читаются — отметка отзыва неизвестна. Данные API показаны всё
            равно.
          </span>
        ) : null}
        <Rules d={d} />
      </div>
      <div className="grid gap-2" data-testid="oauth-held">
        <b className="text-sm font-semibold">Что хранится</b>
        {d.held.empty ? (
          <EmptyState title="Данных API нет">
            Фабрика не хранит ничего из YouTube API — удалять нечего.
          </EmptyState>
        ) : (
          <>
            <Shares plan={d.held} testId="oauth-held-shares" />
            <p className="m-0 text-xs text-muted-foreground">
              Цифры из Studio, которые вы вносили руками, сюда не входят и не удаляются.
            </p>
          </>
        )}
        <More className="mt-0">
          <span>журнал публикаций: {d.held.journal}</span>
          <span>журнал удалений: {d.log}</span>
          {d.held.lines.map((l, i) => (
            <span key={i}>{l}</span>
          ))}
        </More>
      </div>
      <Due d={d} />
      <Purge d={d} />
      <p className="m-0 text-[13px]" data-testid="oauth-switch-link">
        Загрузку роликов через API включают и выключают на экране{' '}
        <Link className="text-primary-text underline underline-offset-4" to="/publishing">
          «Публикация»
        </Link>{' '}
        — в карточке канала, блок «Загрузка через API YouTube».
      </p>
      <More className="mt-0">
        <span>{d.line}</span>
        <span>часы фабрики {d.now}</span>
        {d.config_error ? <span>{d.config_error}</span> : null}
        {d.revocation ? (
          <span>
            revoked_at {d.revocation.revoked_at} · due_at {d.revocation.due_at} · deadline{' '}
            {d.revocation.deadline}
          </span>
        ) : null}
      </More>
    </div>
  );
}

export function ApiData() {
  const q = useApiData();
  return (
    <Card
      aria-labelledby="oauth-api-data-title"
      data-testid="oauth-api-data"
      className="scroll-mt-36"
    >
      <CardHead
        eyebrow="Что фабрика хранит из YouTube API · по каналам"
        title="Данные API"
        titleId="oauth-api-data-title"
        actions={
          <Button
            size="sm"
            variant="ghost"
            data-testid="oauth-api-data-again"
            disabled={q.isFetching}
            onClick={() => void q.refetch()}
          >
            {q.isFetching && !q.isPending ? 'Читаю…' : 'Перечитать'}
          </Button>
        }
      />
      <Loaded q={q} reading="Читаю данные API…" failed="Данные API не прочитать">
        {(d) => <ApiDataView d={d} />}
      </Loaded>
    </Card>
  );
}
