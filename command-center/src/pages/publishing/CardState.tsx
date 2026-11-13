// Карточка публикации без оператора (CC-0127): значок состояния карточки (нет / собирается… —
// с опросом сборки / готова / готова вашим решением / не готова: почему) и действия «Собрать
// заново…» (план — что будет и что пропадёт → «да» → опрос итога раз в `poll_s` → строка итога) и
// «Принять своим решением…» (только у не готовой: план — что не прошло и что решение покрывает,
// ваши слова обязательны → «да» → итог с коммитом). Путь «принял → разложил → загрузил» — целиком
// в центре. Коды отказов и строки фабрики — под «подробнее».
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  cardBuild,
  cardProblemText,
  cardRuling,
  planCardBuild,
  planCardRuling,
  RULING_MAX,
  useCardBuildRun,
  type CardBuildLaunchPlan,
  type CardBuildStarted,
  type CardCenterRefusal,
  type CardRulingPlan,
  type CardRulingResult,
  type CardStateLike,
} from '@/api/cards';
import { publishKeys } from '@/api/publish';
import { videoKeys } from '@/api/videos';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { plural } from '@/pages/batches/format';

import { buildRefusalsText, buildWhyText, parseBuildWhy } from './buildWhy';
import { cardStateView, whereText } from './cardWords';
import { withoutBatchTail } from './stashWords';
import { Disclosure, Done, Elapsed, Field, PlanHead, WriteAction } from './Writes';

/** Крутилка «идёт» (без движения, если человек его не любит). */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      data-testid="spinner"
      className={cn(
        'inline-block size-2.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent motion-reduce:animate-none',
        className,
      )}
    />
  );
}

/**
 * Значок состояния карточки. Собирается и известен номер сборки — опрашивает итог раз в
 * `poll_s`; сборка кончилась — перечитывается всё про публикацию и ролики (значок сменится сам).
 */
export function CardStateBadge({
  card,
  channel,
  testId = 'card-state',
  prefix,
  withWhy = false,
}: {
  card: CardStateLike | null | undefined;
  channel: string | null;
  testId?: string;
  /** Слово перед состоянием: «карточка готова». */
  prefix?: string;
  /** «не готова: почему» прямо в значке (иначе причину показывает тот, кто его держит). */
  withWhy?: boolean;
}) {
  const runId = card?.state === 'building' ? (card.build?.run_id ?? null) : null;
  useCardBuildRun(channel, runId);
  const view = cardStateView(card);
  const label = view.why && !withWhy ? 'не готова' : view.label;
  return (
    <StatusBadge tone={view.tone} tip={view.tip}>
      <span
        data-testid={testId}
        data-state={card?.state ?? 'none'}
        data-placeable={card?.placeable ? '1' : '0'}
        // Строгий смысл `ready` — для тестов прежних экранов (CC-0122).
        data-ready={card?.state === 'ready' ? '1' : '0'}
        className="inline-flex items-center gap-1.5"
      >
        {card?.state === 'building' ? <Spinner /> : null}
        {prefix && card?.state !== 'none' ? `${prefix} ${label}` : label}
      </span>
    </StatusBadge>
  );
}

const SKIPPED_TEXT: Record<string, string> = {
  running: 'карточка уже собирается',
  ready: 'карточка уже готова',
  ruled: 'карточка уже принята вашим решением',
  off: 'автосборка карточек выключена на фабрике',
};

/** Сборка идёт: «собирается… уже 0:42»; кончилась — строка итога (`text_ru`). */
export function BuildProgress({
  channel,
  runId,
  pollS,
  onClose,
  testId = 'card-build',
}: {
  channel: string;
  runId: string;
  pollS?: number | null;
  onClose?: () => void;
  testId?: string;
}) {
  const [since] = useState(() => Date.now());
  const run = useCardBuildRun(channel, runId, pollS);
  const r = run.data;
  if (!r?.done)
    return (
      <p
        role="status"
        data-testid={testId}
        data-done="0"
        className="m-0 flex flex-wrap items-center gap-2 text-[13px]"
      >
        <Spinner className="text-primary-text" />
        <span data-testid={`${testId}-text`}>{r?.text_ru ?? 'Карточка собирается…'}</span>
        <span className="text-xs text-muted-foreground">
          уже <Elapsed since={since} />
        </span>
        {run.isError ? (
          <span className="text-xs text-warning">итог пока не читается — спрошу ещё раз</span>
        ) : null}
      </p>
    );
  const good = r.code === 'ready';
  const body = (
    <>
      <span data-testid={`${testId}-text`}>{r.text_ru}</span>
      <More className="mt-0">
        <span>итог: {r.code}</span>
        <span>{r.line}</span>
        {r.detail ? <span>{r.detail}</span> : null}
        {r.log ? <span>журнал: {r.log}</span> : null}
        {r.run_id ? <span>сборка: {r.run_id}</span> : null}
      </More>
    </>
  );
  if (!onClose)
    return (
      <div
        role="status"
        data-testid={testId}
        data-done="1"
        data-code={r.code}
        className={cn('grid gap-0.5 text-[13px]', !good && 'text-warning')}
      >
        {body}
      </div>
    );
  return (
    <div data-testid={testId} data-done="1" data-code={r.code}>
      <Done
        tone={good ? 'ok' : 'warn'}
        title={good ? 'Карточка собрана' : 'Сборка закончилась'}
        testId={`${testId}-done`}
        onClose={onClose}
      >
        {body}
      </Done>
    </div>
  );
}

function Refusals({ list }: { list: CardCenterRefusal[] }) {
  if (!list.length) return null;
  return (
    <ul className="m-0 grid list-none gap-1 p-0" data-testid="card-plan-refusals">
      {list.map((x, i) => (
        <li key={i} className="text-danger" data-testid="card-plan-refusal" data-code={x.code}>
          {x.message}
        </li>
      ))}
    </ul>
  );
}

function BuildPlan({ plan }: { plan: CardBuildLaunchPlan }) {
  const now = cardStateView(plan.card);
  return (
    <>
      <PlanHead plan={plan} yes="можно собрать" no="собрать нельзя" />
      <p className="m-0" data-testid="card-build-what">
        {plan.what}
      </p>
      {plan.replaces ? (
        <p className="m-0 font-medium text-warning" data-testid="card-build-replaces">
          {plan.replaces}
        </p>
      ) : (
        <p className="m-0 text-muted-foreground" data-testid="card-build-now">
          Сейчас карточка: {now.label}.
        </p>
      )}
      {plan.problems.length ? (
        <ul
          className="m-0 grid list-none gap-0.5 p-0 text-warning"
          data-testid="card-build-problems"
        >
          {plan.problems.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      ) : null}
      <Refusals list={plan.refusals} />
      <More className="mt-0">
        {plan.refusals.map((x, i) => (
          <span key={i}>
            {x.code}: {x.line ?? ''}
          </span>
        ))}
        {plan.card.path ? <span>карточка: {withoutBatchTail(plan.card.path)}</span> : null}
        <span>батч: {plan.batch_id}</span>
      </More>
    </>
  );
}

function RulingPlan({ plan }: { plan: CardRulingPlan }) {
  const own = plan.failing.filter((f) => f.video === true);
  return (
    <>
      <PlanHead plan={plan} yes="можно принять" no="принять нельзя" />
      {plan.failing.length ? (
        <div className="grid gap-1" data-testid="card-ruling-failing">
          <span className="text-xs font-semibold">
            Не прошло:{own.length ? ` слова ролика — ${own.length}` : ''}
          </span>
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {plan.failing.map((f, i) => (
              <li
                key={i}
                data-testid="card-ruling-fail"
                data-own={f.video === true ? '1' : '0'}
                className="grid gap-0.5 rounded-sm border p-2"
              >
                <span className="text-xs text-muted-foreground">{whereText(f.where)}</span>
                {f.text ? <q className="[overflow-wrap:anywhere]">{f.text}</q> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="m-0" data-testid="card-ruling-scope">
        {plan.scope}
      </p>
      {plan.words ? (
        <p className="m-0 text-muted-foreground" data-testid="card-ruling-words">
          Ваши слова попадут в карточку: «{plan.words}»
        </p>
      ) : null}
      <Refusals list={plan.refusals} />
      <More className="mt-0">
        {plan.failing.map((f, i) => (
          <span key={i}>
            {f.where}: {f.code}
          </span>
        ))}
        {plan.refusals.map((x, i) => (
          <span key={`r${i}`}>
            {x.code}: {x.line ?? ''}
          </span>
        ))}
        {plan.lines.map((l, i) => (
          <span key={`l${i}`}>{l}</span>
        ))}
        {plan.card ? <span>карточка: {plan.card}</span> : null}
        {plan.path ? <span>в публикации: {withoutBatchTail(plan.path)}</span> : null}
      </More>
    </>
  );
}

function RulingDone({ r, onClose }: { r: CardRulingResult; onClose: () => void }) {
  return (
    <Done
      tone={r.commit ? 'ok' : 'warn'}
      title="Карточка принята вашим решением"
      testId="card-ruling-done"
      onClose={onClose}
    >
      <span data-testid="card-ruling-commit">
        {r.commit
          ? `Сохранено: ${r.committed.length} ${plural(r.committed.length, 'файл', 'файла', 'файлов')} публикации.`
          : 'Записано; коммита не было — файлы вне git.'}
      </span>
      <More className="mt-0">
        {r.commit ? <span>коммит {r.commit}</span> : null}
        {r.touched.map((f) => (
          <span key={f}>{f}</span>
        ))}
      </More>
    </Done>
  );
}

/** После записи карточки — перечитать всё про публикацию и ролики (копилка, лента, ролик). */
function useAfterCardWrite() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: publishKeys.all });
    void qc.invalidateQueries({ queryKey: videoKeys.all });
  };
}

/**
 * Действия с карточкой ролика: «Собрать заново…» (кроме идущей сборки) и «Принять своим
 * решением…» (только у не готовой). `compact` — тихие кнопки (строка копилки).
 */
export function CardActions({
  channel,
  slug,
  batchId,
  card,
  title,
  compact = false,
  rebuild = true,
}: {
  channel: string;
  slug: string;
  batchId: string | null;
  card: CardStateLike | null | undefined;
  /** Ролик словами — для окон. */
  title: string;
  compact?: boolean;
  /** Показывать ли «Собрать заново…» (в копилке — только у не готовой и без карточки). */
  rebuild?: boolean;
}) {
  const [started, setStarted] = useState<CardBuildStarted | null>(null);
  const [ruled, setRuled] = useState<CardRulingResult | null>(null);
  const [words, setWords] = useState('');
  // CC-0128: форма решения и окно решения не открыты разом — окно сворачивает форму, «Отмена»
  // возвращает её с набранными словами, «да» оставляет свёрнутой.
  const [form, setForm] = useState(false);
  const settled = useAfterCardWrite();
  const state = card?.state ?? 'none';
  const trimmed = words.trim();
  const wordsWhy = !trimmed
    ? 'Напишите ваше решение — своими словами, почему карточку можно публиковать'
    : trimmed.length > RULING_MAX
      ? `Не длиннее ${RULING_MAX} знаков`
      : null;
  const variant = compact ? 'ghost' : 'outline';
  // Действий нет и итога нет — ничего; итог записи держится, даже когда состояние сменилось.
  if (!rebuild && state !== 'not_ready' && !started && !ruled) return null;
  return (
    <div className="grid gap-2" data-testid="card-actions" data-slug={slug}>
      <div className="flex flex-wrap items-start gap-2">
        {rebuild ? (
          <WriteAction<{ batch_id: string | null }, CardBuildLaunchPlan, CardBuildStarted>
            id="card-rebuild"
            label="Собрать заново…"
            title="Собрать карточку заново"
            description={`Ролик «${title}». Итог сборки появится здесь.`}
            tip="Собрать карточку ролика заново — после сбоя модели или проверки утверждений"
            body={{ batch_id: batchId }}
            why={state === 'building' ? 'Карточка уже собирается — дождитесь итога' : null}
            confirmLabel="Собрать"
            pendingLabel="Запускаю…"
            plan={(b) => planCardBuild(channel, slug, b)}
            act={(confirm) => cardBuild(channel, slug, confirm)}
            view={(p) => <BuildPlan plan={p} />}
            onDone={(r) => setStarted(r)}
            problemText={cardProblemText}
            onSettled={settled}
            triggerVariant={variant}
          />
        ) : null}
        {state === 'not_ready' ? (
          <Disclosure
            id="card-ruling"
            label="Принять своим решением"
            tip="Не прошли утверждения самого ролика (комментарий, текст на экране): принять карточку под вашу ответственность, вашими словами"
            open={form}
            onOpenChange={setForm}
            keepMounted
          >
            <Field
              label="Ваше решение"
              rows={3}
              value={words}
              onChange={setWords}
              testId="card-ruling-words-input"
              placeholder="Например: цифру проверил сам по пресс-релизу студии — публикуем"
              invalid={trimmed.length > RULING_MAX}
              hint={`${trimmed.length} из ${RULING_MAX} знаков — попадут в карточку как есть`}
            />
            <WriteAction<
              { batch_id: string | null; words: string },
              CardRulingPlan,
              CardRulingResult
            >
              id="card-ruling"
              label="Принять своим решением…"
              title="Принять карточку своим решением"
              description={`Ролик «${title}»: карточка не прошла проверку утверждений. Ваше решение и слова запишутся в карточку.`}
              tip="Фабрика покажет, что не прошло, — подтвердите"
              body={wordsWhy ? null : { batch_id: batchId, words: trimmed }}
              why={wordsWhy}
              confirmLabel="Принять"
              plan={(b) => planCardRuling(channel, slug, b)}
              act={(confirm) => cardRuling(channel, slug, confirm)}
              view={(p) => <RulingPlan plan={p} />}
              onOpenChange={(v) => setForm(!v)}
              onDone={(r) => {
                setRuled(r);
                setWords('');
              }}
              problemText={cardProblemText}
              onSettled={settled}
            />
          </Disclosure>
        ) : null}
      </div>
      {started?.run_id ? (
        <BuildProgress
          channel={channel}
          runId={started.run_id}
          pollS={started.poll_s}
          onClose={() => setStarted(null)}
        />
      ) : started ? (
        <Done
          tone="warn"
          title="Сборка не запущена"
          testId="card-build-skipped"
          onClose={() => setStarted(null)}
        >
          <span>
            {started.skipped
              ? (SKIPPED_TEXT[started.skipped] ?? started.skipped)
              : 'Фабрика сборку не начала.'}
          </span>
          <More className="mt-0">
            {started.lines.map((l, i) => (
              <span key={i}>{l}</span>
            ))}
          </More>
        </Done>
      ) : null}
      {ruled ? <RulingDone r={ruled} onClose={() => setRuled(null)} /> : null}
    </div>
  );
}

/**
 * Ответ приёмки (CC-0127): сборка карточки, которую приёмка запустила сама. Не запустилась —
 * почему (CC-0175, `why`: русские строки фабрики, коды и строка целиком — под «подробнее»).
 */
export function AcceptBuild({
  channel,
  build,
}: {
  channel: string | null;
  build: {
    launched: boolean;
    skipped?: string | null;
    run_id?: string | null;
    refusals?: string[];
    error?: string | null;
    why?: string | null;
  };
}) {
  if (build.launched && build.run_id && channel)
    return <BuildProgress channel={channel} runId={build.run_id} testId="accept-card-build" />;
  const why = build.skipped || build.launched ? null : buildWhyText(build.why);
  const text = build.skipped
    ? `Карточка: ${SKIPPED_TEXT[build.skipped] ?? build.skipped}.`
    : why
      ? build.refusals?.length
        ? `Карточку не собрать: ${why}.`
        : `Сборка карточки не запустилась: ${why}.${build.error ? ' Соберите её заново на странице ролика.' : ''}`
      : build.refusals?.length
        ? `Карточку не собрать: ${buildRefusalsText(build.refusals)}.`
        : build.error
          ? 'Сборка карточки не запустилась — соберите её заново на странице ролика.'
          : null;
  if (!text) return null;
  if (!why)
    return (
      <p
        className={cn('m-0', !build.skipped && 'text-warning')}
        data-testid="accept-card-build"
        data-skipped={build.skipped ?? undefined}
      >
        {text}
      </p>
    );
  const parts = parseBuildWhy(build.why);
  return (
    <div className="m-0 grid min-w-0 gap-0.5" data-testid="accept-card-build" data-why="1">
      <p className="m-0 text-warning [overflow-wrap:anywhere]" data-testid="accept-card-build-why">
        {text}
      </p>
      <More className="mt-0" label="Подробнее о сборке">
        {parts.map((p, i) => (
          <span key={i} data-testid="accept-card-build-why-code" data-code={p.code ?? undefined}>
            {p.code ? `${p.code}: ` : ''}
            {p.line}
          </span>
        ))}
        {build.error ? <span>ошибка: {build.error}</span> : null}
      </More>
    </div>
  );
}
