// «Новый канал»: мастер по шагам (CC-0009). Имя и id → тематика и позиция → голос и паттерны →
// ленты и источники → публикация и окно → проверка → создать.
//
// Фабрика создаёт канал из своего шаблона по трём входам (id, название, язык). Мастер сверяет
// входы с ней по ходу (dry-run, ничего не пишет), даёт вписать позицию в одну фразу — поле
// шаблона позиции — и показывает, что из настроек канала появится только с конвейером.
// «Создать» — один коммит трёх файлов; вписанная позиция уходит в нём же (`stance_text`,
// договор 0.5.0) и проверяется фабрикой как правка. Ключей, которых нет в шаблоне, мастер не пишет.
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  ChannelError,
  channelKeys,
  createChannel,
  useChannelTemplate,
  type ChannelTemplate,
  type CreateResult,
  type TemplateInput,
} from '@/api/channels';
import { readOnlyTip, useWrites } from '@/api/writes';
import { Card } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { checkDetail, readDoc } from './fields';
import { todoItems, type WizardLanding } from './firstBatch';
import {
  cleanInputs,
  diffHunks,
  draftStance,
  filesOf,
  hasThesis,
  initialInputs,
  inputErrorsByField,
  lineDiff,
  localError,
  serverErrors,
  stanceErrors,
  STEPS,
  stripTasks,
  thesisNote,
  type Draft,
  type InputName,
  type Inputs,
  type StepId,
} from './wizard';
import { InfoRow } from './parts';
import { problemOf, type Problem } from './problem';
import { Problems } from './Problems';
import { inputBase } from './styles';
import { TodoList } from './TodoList';
import { useFreshness } from './useFreshness';
import { Pending, SkeletonCard } from '@/components/common/Skeletons';

export function NewChannel() {
  const tpl = useChannelTemplate();
  const { refetch } = tpl;
  const refreshLock = useCallback(() => void refetch(), [refetch]);
  return (
    <>
      <div className="grid gap-1">
        <Link to="/channels" className="w-max text-xs text-primary-text">
          ← Все каналы
        </Link>
        <div className="eyebrow">Каналы фабрики</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Новый канал
        </h1>
      </div>
      {tpl.isPending ? (
        <Pending label="Загружаю шаблон канала…" className="gap-3">
          {/* Ждать бывает до минуты — словами, а не только формой. */}
          <p className="m-0 text-muted-foreground" aria-hidden="true">
            Загружаю шаблон канала: фабрика заодно проверяет, не идёт ли батч, — на занятой машине
            это до минуты…
          </p>
          <SkeletonCard bare rows={5} />
        </Pending>
      ) : tpl.isError ? (
        <ErrorState
          title="Не удалось загрузить шаблон нового канала"
          error={tpl.error}
          onRetry={() => void tpl.refetch()}
        >
          {tpl.error instanceof ChannelError && tpl.error.problem
            ? tpl.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <Wizard template={tpl.data} receivedAt={tpl.dataUpdatedAt} onRefreshLock={refreshLock} />
      )}
    </>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  const key = JSON.stringify(value);
  useEffect(() => {
    const t = setTimeout(() => setV(JSON.parse(key) as T), ms);
    return () => clearTimeout(t);
  }, [key, ms]);
  return v;
}

const sameInputs = (a: Inputs, b: Inputs) =>
  a.channel_id === b.channel_id && a.display_name === b.display_name && a.language === b.language;

type Run = 'create' | null;

function Wizard({
  template,
  receivedAt,
  onRefreshLock,
}: {
  template: ChannelTemplate;
  /** Когда пришёл шаблон: его `lock.age_s` — на тот момент. */
  receivedAt: number;
  onRefreshLock: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState<StepId>('name');
  const [inputs, setInputs] = useState<Inputs>(() => initialInputs(template.inputs));
  const [touched, setTouched] = useState<ReadonlySet<InputName>>(new Set());
  const [draft, setDraft] = useState<Draft>({ thesis: '' });
  const [run, setRun] = useState<Run>(null);
  const [failure, setFailure] = useState<Problem | null>(null);
  // На шаге «Создать» — свежая блокировка (идёт ли батч) в фоне; кнопку это не держит.
  const onCreateStep = step === 'create';
  useEffect(() => {
    if (onCreateStep) onRefreshLock();
  }, [onCreateStep, onRefreshLock]);

  const clean = cleanInputs(inputs);
  const local = useMemo(() => {
    const m: Partial<Record<InputName, string>> = {};
    for (const i of template.inputs) {
      const e = localError(i, inputs[i.name]);
      if (e) m[i.name] = e;
    }
    return m;
  }, [template.inputs, inputs]);
  const localOk = Object.keys(local).length === 0;

  // Dry-run фабрики по входам — когда человек перестал печатать и сами входы в порядке.
  const asked = useDebounced(clean, 450);
  const askedOk = template.inputs.every((i) => !localError(i, asked[i.name]));
  const dry = useQuery({
    queryKey: [...channelKeys.list, 'dry-run', asked] as const,
    queryFn: ({ signal }) =>
      createChannel(
        {
          channel_id: asked.channel_id,
          display_name: asked.display_name,
          language: asked.language || null,
          dry_run: true,
        },
        signal,
      ),
    enabled: askedOk,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const fresh = localOk && !!dry.data && !dry.isPlaceholderData && sameInputs(asked, clean);
  const result: CreateResult | undefined = fresh ? dry.data : undefined;
  const checking = localOk && !fresh && !dry.isError;
  const server = useMemo(() => serverErrors(result?.errors ?? []), [result]);
  const byField = inputErrorsByField(clean, server.byField);
  const inputsOk = !!result && Object.keys(byField).length === 0;
  const files = filesOf(result);

  // Блокировка — из шаблона или из последнего dry-run (если тот уже видит батч); оба — по
  // последнему скану фабрики, насколько он свежий — `batchesSeen`.
  const lock = result?.lock.locked ? result.lock : template.lock;
  const locked = lock.locked;
  const batchesSeen = useFreshness(lock, result?.lock.locked ? dry.dataUpdatedAt : receivedAt);

  const stanceBase = files.stance?.text ?? null;
  const thesisOn = hasThesis(stanceBase);
  const stance = draftStance(stanceBase, draft);

  const reached = (id: StepId) => id === 'name' || inputsOk;
  const index = STEPS.findIndex((s) => s.id === step);
  const go = (id: StepId) => {
    if (reached(id)) setStep(id);
  };

  const setInput = (name: InputName, value: string) => {
    setInputs((v) => ({ ...v, [name]: value }));
    setFailure(null);
  };
  const blur = (name: InputName) => setTouched((t) => (t.has(name) ? t : new Set([...t, name])));

  const doCreate = async () => {
    setFailure(null);
    setRun('create');
    let made: CreateResult;
    try {
      // Позиция с фразой — текстом файла из dry-run: фабрика запишет её тем же коммитом.
      made = await createChannel({
        channel_id: clean.channel_id,
        display_name: clean.display_name,
        language: clean.language || null,
        ...(stance !== null ? { stance_text: stance } : {}),
        dry_run: false,
      });
    } catch (e) {
      setRun(null);
      setFailure(problemOf(e, 'Канал не создан'));
      const p = e instanceof ChannelError ? e.problem : null;
      if (p?.code === 'batch_running')
        void qc.invalidateQueries({ queryKey: channelKeys.template });
      if (p?.errors.some((l) => l.field === 'channel_id' || l.field === 'display_name'))
        setStep('name');
      else if (p && stanceErrors(p.errors).length) setStep('topic');
      return;
    }
    const id = made.channel_id ?? clean.channel_id;
    if (made.channel) qc.setQueryData(channelKeys.detail(id), made.channel);
    void qc.invalidateQueries({ queryKey: channelKeys.list, exact: true });
    const landing: WizardLanding = {
      created: made.subject ?? `Канал ${clean.display_name}: создан`,
      withStance: stance !== null,
    };
    void navigate(`/channels/${encodeURIComponent(id)}`, { state: { wizard: landing } });
  };
  // Отказ создания из-за позиции — показать его на шаге с фразой.
  const stanceFailure = failure && stanceErrors(failure.errors).length ? failure : null;

  const todo = useMemo(
    () =>
      todoItems(
        readDoc(files.config?.text ?? null),
        readDoc(stance ?? stanceBase),
        template.no_pipeline,
        files.all.find((f) => f.path.endsWith('.md'))?.text ?? null,
      ),
    [files.config, files.all, stance, stanceBase, template.no_pipeline],
  );

  return (
    <div className="grid gap-gap">
      <Stepper step={step} reached={reached} onGo={go} />

      {locked ? (
        <div
          role="status"
          data-testid="create-lock"
          className="grid gap-1.5 rounded-lg border border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] px-card py-3.5"
        >
          <div className="font-semibold text-warning">Сейчас канал не создать: идёт батч</div>
          <p className="m-0">{lock.message}</p>
          <p className="m-0 text-muted-foreground">
            Заполнить и проверить можно; создать — когда батч закончится.
          </p>
          {lock.batches.length ? (
            <More className="mt-0">
              {lock.batches.map((b) => (
                <span key={b.dir}>батч: {b.dir}</span>
              ))}
              {batchesSeen ? <span>батчи: {batchesSeen}</span> : null}
            </More>
          ) : null}
        </div>
      ) : null}

      <Card aria-labelledby="step-title" className="grid gap-4" data-step={step}>
        <div>
          <div className="eyebrow">
            Шаг {index + 1} из {STEPS.length}
          </div>
          <h2 id="step-title" className="mt-0.5 text-[17px] font-semibold">
            {STEPS[index]!.label}
          </h2>
        </div>

        {step === 'name' ? (
          <NameStep
            template={template}
            inputs={inputs}
            touched={touched}
            local={local}
            server={byField}
            technical={(result?.errors ?? []).map(checkDetail)}
            checking={checking}
            failed={dry.isError ? dry.error : null}
            ok={inputsOk}
            onChange={setInput}
            onBlur={blur}
          />
        ) : step === 'topic' ? (
          <TopicStep
            thesisOn={thesisOn}
            failure={stanceFailure}
            note={thesisNote(stanceBase)}
            draft={draft}
            onDraft={setDraft}
            statusNote={statusNoteOf(files.config?.text)}
          />
        ) : step === 'voice' ? (
          <VoiceStep />
        ) : step === 'feeds' ? (
          <FeedsStep />
        ) : step === 'publish' ? (
          <PublishStep template={template} configText={files.config?.text ?? null} />
        ) : step === 'review' ? (
          <ReviewStep
            inputs={clean}
            result={result}
            checking={checking}
            stanceBase={stanceBase}
            stance={stance}
            draft={draft}
          />
        ) : (
          <CreateStep
            name={clean.display_name}
            withStance={stance !== null}
            locked={locked}
            lockMessage={lock.message}
            refreshing={lock.checking}
            batchesSeen={batchesSeen}
            ready={!!result?.ok}
            run={run}
            failure={failure}
            onCreate={() => void doCreate()}
          />
        )}

        {step !== 'name' && result && server.rest.length ? (
          <Problems
            testId="dry-run-problems"
            problem={{
              tone: 'danger',
              title: 'Фабрика не примет канал из шаблона',
              message: 'Это не про ваши входы: шаблон фабрики не проходит её же проверку.',
              errors: server.rest,
              details: [],
            }}
          />
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3.5">
          {index > 0 ? (
            <Button variant="ghost" onClick={() => setStep(STEPS[index - 1]!.id)} disabled={!!run}>
              ← Назад
            </Button>
          ) : (
            <span />
          )}
          {index < STEPS.length - 1 ? (
            <NextButton
              ok={reached(STEPS[index + 1]!.id)}
              why={
                checking
                  ? 'Фабрика ещё проверяет имя и id'
                  : 'Сначала исправьте имя и id: фабрика должна их принять'
              }
              label={`Далее: ${STEPS[index + 1]!.label}`}
              onClick={() => setStep(STEPS[index + 1]!.id)}
            />
          ) : null}
        </div>
      </Card>

      {step === 'create' ? <TodoList items={todo} /> : null}
    </div>
  );
}

function statusNoteOf(configText: string | null | undefined): string | null {
  const n = readDoc(configText ?? null)?.status_note;
  return typeof n === 'string' ? n : null;
}

function NextButton({
  ok,
  why,
  label,
  onClick,
}: {
  ok: boolean;
  why: string;
  label: string;
  onClick: () => void;
}) {
  const button = (
    <Button
      variant="default"
      aria-disabled={!ok || undefined}
      onClick={() => {
        if (ok) onClick();
      }}
    >
      {label} →
    </Button>
  );
  return ok ? button : <Tip content={why}>{button}</Tip>;
}

function Stepper({
  step,
  reached,
  onGo,
}: {
  step: StepId;
  reached: (id: StepId) => boolean;
  onGo: (id: StepId) => void;
}) {
  const index = STEPS.findIndex((s) => s.id === step);
  return (
    <nav aria-label="Шаги мастера" className="grid gap-2">
      <ol className="m-0 grid list-none grid-cols-7 gap-1 p-0 md:gap-1.5">
        {STEPS.map((s, i) => {
          const current = s.id === step;
          const can = reached(s.id);
          return (
            <li key={s.id} className="min-w-0">
              <Tip content={can ? s.tip : `${s.tip}. Откроется, когда фабрика примет имя и id`}>
                <button
                  type="button"
                  aria-current={current ? 'step' : undefined}
                  aria-disabled={!can || undefined}
                  aria-label={`Шаг ${i + 1}: ${s.label}`}
                  data-step-button={s.id}
                  onClick={() => onGo(s.id)}
                  className={cn(
                    'flex w-full min-w-0 flex-col items-center gap-1.5 rounded-sm border-t-2 px-0.5 pt-2 pb-1 text-center md:flex-row md:items-start md:gap-2 md:text-left',
                    current
                      ? 'border-primary text-foreground'
                      : i < index
                        ? 'border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] text-foreground'
                        : 'border-border text-muted-foreground',
                    !can && 'cursor-not-allowed opacity-60',
                  )}
                >
                  <span
                    className={cn(
                      'grid size-[24px] shrink-0 place-items-center rounded-full border font-mono text-[11px]',
                      current && 'border-primary bg-primary font-semibold text-primary-foreground',
                    )}
                  >
                    {i + 1}
                  </span>
                  <span
                    className={cn(
                      'hidden min-w-0 text-[12px] leading-tight md:block',
                      current && 'font-semibold',
                    )}
                  >
                    {s.label}
                  </span>
                </button>
              </Tip>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function FieldLabel({ htmlFor, label, tip }: { htmlFor: string; label: string; tip: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-semibold">
        {label}
      </label>
      <Tip content={tip} wide side="top">
        <button
          type="button"
          aria-label={`Что это: ${label}`}
          className="inline-grid size-[18px] shrink-0 place-items-center rounded-full border border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] text-[11px] leading-none text-primary-text"
        >
          ?
        </button>
      </Tip>
    </div>
  );
}

function NameStep({
  template,
  inputs,
  touched,
  local,
  server,
  technical,
  checking,
  failed,
  ok,
  onChange,
  onBlur,
}: {
  template: ChannelTemplate;
  inputs: Inputs;
  touched: ReadonlySet<InputName>;
  local: Partial<Record<InputName, string>>;
  server: Partial<Record<InputName, string[]>>;
  technical: string[];
  checking: boolean;
  failed: unknown;
  ok: boolean;
  onChange: (name: InputName, value: string) => void;
  onBlur: (name: InputName) => void;
}) {
  const uid = useId();
  return (
    <div className="grid gap-4">
      <p className="m-0 text-muted-foreground">
        Из этих трёх значений фабрика делает канал по своему шаблону. Фабрика проверяет их по ходу —
        ничего не создаётся, пока вы не нажмёте «Создать» на последнем шаге.
      </p>
      {template.inputs.map((input: TemplateInput) => {
        const id = `${uid}-${input.name}`;
        const value = inputs[input.name];
        // Своя проверка — сразу после ввода (или ухода с поля, если оно пустое); фабрики — после неё.
        const mine = local[input.name];
        const showMine = mine && (value.trim() !== '' || touched.has(input.name));
        const theirs = server[input.name] ?? [];
        const errs = showMine ? [mine] : theirs;
        return (
          <div key={input.name} className="grid gap-1.5" data-input={input.name}>
            <FieldLabel
              htmlFor={id}
              label={`${input.label}${input.required ? '' : ' (можно не менять)'}`}
              tip={stripTasks(input.note)}
            />
            <input
              id={id}
              type="text"
              value={value}
              autoComplete="off"
              spellCheck={false}
              placeholder={input.default ?? undefined}
              aria-invalid={errs.length > 0 || undefined}
              aria-describedby={errs.length ? `${id}-why` : undefined}
              onChange={(e) => onChange(input.name, e.target.value)}
              onBlur={() => onBlur(input.name)}
              className={cn(
                inputBase,
                'max-w-[420px]',
                input.name !== 'display_name' && 'font-mono',
              )}
            />
            {errs.length ? (
              <div id={`${id}-why`} className="grid gap-0.5 text-xs text-danger">
                {errs.map((e) => (
                  <span key={e}>{e}</span>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
      {technical.length ? (
        <More className="mt-0">
          {technical.map((t) => (
            <span key={t}>{t}</span>
          ))}
        </More>
      ) : null}
      <div aria-live="polite" className="min-h-5 text-[13px]">
        {failed ? (
          <span className="text-danger" data-testid="dry-run-failed">
            Фабрика не ответила на проверку:{' '}
            {failed instanceof Error ? failed.message : String(failed)}
          </span>
        ) : checking ? (
          <span className="animate-pulse text-muted-foreground">
            Фабрика проверяет… На занятой машине — до минуты.
          </span>
        ) : ok ? (
          <span className="text-success" data-testid="dry-run-ok">
            Фабрика примет эти имя и id
          </span>
        ) : null}
      </div>
    </div>
  );
}

function Guide({ title, children, more }: { title: string; children: ReactNode; more?: string[] }) {
  return (
    <div className="grid gap-1 rounded-sm border border-dashed px-3.5 py-3" data-guide={title}>
      <div className="font-semibold">{title}</div>
      <div className="grid gap-1.5 text-muted-foreground">{children}</div>
      {more?.length ? (
        <More className="mt-1">
          {more.map((m, i) => (
            <span key={i}>{m}</span>
          ))}
        </More>
      ) : null}
    </div>
  );
}

const LATER =
  'В шаблоне фабрики этого нет: у канала без конвейера фабрика эти настройки не читает и не проверяет. Они добавляются правкой канала в редакторе — после создания, вместе с конвейером.';

function TopicStep({
  thesisOn,
  failure,
  note,
  draft,
  onDraft,
  statusNote,
}: {
  thesisOn: boolean;
  /** Фабрика не приняла позицию при создании (ошибки с `field` `stance…`). */
  failure: Problem | null;
  note: string | null;
  draft: Draft;
  onDraft: (d: Draft) => void;
  statusNote: string | null;
}) {
  const id = useId();
  return (
    <div className="grid gap-4">
      {thesisOn ? (
        <div className="grid gap-1.5">
          <FieldLabel
            htmlFor={id}
            label="Позиция в одну фразу (можно оставить пустой)"
            tip={stripTasks(note) || 'Что делает каждый ролик канала — в одной фразе.'}
          />
          <textarea
            id={id}
            rows={3}
            value={draft.thesis}
            onChange={(e) => onDraft({ thesis: e.target.value })}
            className={cn(inputBase, 'min-h-[84px] resize-y leading-[1.45]')}
          />
          <p className="m-0 text-xs text-muted-foreground">
            Запишется в позицию канала тем же коммитом, что и сам канал. Пустая — позиция останется
            заготовкой шаблона.
          </p>
          {failure ? (
            <Problems
              testId="stance-failed"
              problem={{ ...failure, errors: stanceErrors(failure.errors) }}
            />
          ) : null}
        </div>
      ) : (
        <p className="m-0 text-muted-foreground">
          В шаблоне позиции фабрики сейчас нет поля для одной фразы — позиция пишется в редакторе
          канала после создания.
        </p>
      )}
      <Guide
        title="Тематика"
        more={['блок конфига: scope', ...(statusNote ? [stripTasks(statusNote)] : [])]}
      >
        <p className="m-0">
          Что канал берёт в батч: типы контента, порог популярности, сколько тайтлов за раз.
        </p>
        <p className="m-0">{LATER}</p>
      </Guide>
      <Guide title="Позиция целиком" more={['файл позиции: stance.json канала, поле left_open']}>
        <p className="m-0">
          Рамка канала, что вне её, голос, что считать фактом, отказ, декларация — это пишет человек
          в части «Позиция» редактора канала. Каналу без конвейера целиком она пока не нужна.
        </p>
      </Guide>
    </div>
  );
}

function VoiceStep() {
  return (
    <div className="grid gap-4">
      <Guide title="Голос озвучки" more={['блок конфига: voice_profile']}>
        <p className="m-0">Каким голосом и с какой скоростью озвучиваются ролики канала.</p>
        <p className="m-0">{LATER}</p>
      </Guide>
      <Guide title="Паттерны роликов" more={['блок конфига: patterns']}>
        <p className="m-0">Какие виды роликов канал делает и как они собираются.</p>
        <p className="m-0">{LATER}</p>
      </Guide>
      <Guide title="Голос в позиции" more={['файл позиции: часть voice']}>
        <p className="m-0">
          Как канал говорит — часть позиции; её пишет человек в редакторе канала.
        </p>
      </Guide>
    </div>
  );
}

function FeedsStep() {
  return (
    <div className="grid gap-4">
      <Guide title="Источники" more={['блок конфига: sources']}>
        <p className="m-0">
          Откуда канал берёт истории. Источник, чей robots.txt запрещает ботов Anthropic или всех
          ботов, фабрика не берёт — это правило она проверяет при каждом сохранении, и у канала без
          конвейера тоже.
        </p>
        <p className="m-0">{LATER}</p>
      </Guide>
      <Guide
        title="Списки канала"
        more={['рядом с конфигом: fact-sources, rights-holder-blacklist, footage-origin']}
      >
        <p className="m-0">
          Источники фактов, правообладатели, которых обходить, происхождение футажа — отдельные
          списки рядом с конфигом канала. Их заводят вместе с конвейером.
        </p>
      </Guide>
    </div>
  );
}

function PublishStep({
  template,
  configText,
}: {
  template: ChannelTemplate;
  configText: string | null;
}) {
  const bs = template.batch_schedule;
  const note = typeof bs?.note === 'string' ? bs.note : null;
  const cfg = readDoc(configText);
  const themeNote =
    cfg && typeof (cfg.theme as { note?: unknown } | undefined)?.note === 'string'
      ? (cfg.theme as { note: string }).note
      : null;
  return (
    <div className="grid gap-4">
      <p className="m-0 text-muted-foreground">
        Новый канал создаётся без конвейера: {template.no_pipeline}. Вот с чем он появится.
      </p>
      <ul className="m-0 grid list-none p-0">
        <InfoRow
          label="Расписание батчей"
          tip={stripTasks(note) || 'Новый канал создаётся выключенным из расписания'}
        >
          <span data-testid="schedule-off">
            {bs?.enabled === false ? 'выключено' : 'как в шаблоне'}
          </span>
        </InfoRow>
        <InfoRow
          label="Окно батча"
          tip="Когда фабрика может начать батч канала. Задаётся, когда канал включают в расписание"
        >
          <span className="text-muted-foreground">не задано — канал вне расписания</span>
        </InfoRow>
        <InfoRow
          label="Публикация"
          tip="У канала без конвейера нет публикатора: ни слота, ни очереди роликов"
        >
          <span className="text-muted-foreground">нет — нечего публиковать</span>
        </InfoRow>
        <InfoRow
          label="Палитра роликов"
          tip={stripTasks(themeNote) || 'Цвета экранной графики роликов канала'}
        >
          <span className="text-muted-foreground">нейтральная палитра шаблона</span>
        </InfoRow>
        <InfoRow
          label="Оформление в Studio"
          tip="Файл оформления канала: описание и ключевые слова для YouTube Studio, аватар и баннер"
        >
          <span className="text-muted-foreground">заготовка, не написано</span>
        </InfoRow>
      </ul>
      <More>
        <span>batch_schedule: {JSON.stringify(bs)}</span>
        <span>status: {template.status}</span>
      </More>
    </div>
  );
}

const FILE_LABEL: [RegExp, string][] = [
  [/\/stance\.json$/, 'Позиция канала'],
  [/\.md$/, 'Оформление в YouTube Studio'],
  [/^channels\/[^/]+\.json$/, 'Конфиг канала'],
];
const fileLabel = (path: string) => FILE_LABEL.find(([re]) => re.test(path))?.[1] ?? 'Файл';

function ReviewStep({
  inputs,
  result,
  checking,
  stanceBase,
  stance,
  draft,
}: {
  inputs: Inputs;
  result: CreateResult | undefined;
  checking: boolean;
  stanceBase: string | null;
  stance: string | null;
  draft: Draft;
}) {
  const diff = useMemo(
    () => (stance && stanceBase ? diffHunks(lineDiff(stanceBase, stance)) : []),
    [stance, stanceBase],
  );
  return (
    <div className="grid gap-4">
      <ul className="m-0 grid list-none p-0">
        <InfoRow label="Идентификатор">
          <span className="font-mono">{inputs.channel_id}</span>
        </InfoRow>
        <InfoRow label="Название">{inputs.display_name}</InfoRow>
        <InfoRow label="Язык роликов">
          <span className="font-mono">{inputs.language || 'по умолчанию фабрики'}</span>
        </InfoRow>
        <InfoRow label="Позиция в одну фразу">
          {draft.thesis.trim() ? (
            <span data-testid="review-thesis">«{draft.thesis.trim()}»</span>
          ) : (
            <span className="text-muted-foreground">пусто — заготовка шаблона</span>
          )}
        </InfoRow>
      </ul>

      {checking ? (
        <p role="status" className="m-0 animate-pulse text-muted-foreground">
          Фабрика проверяет…
        </p>
      ) : result?.ok ? (
        <Problems
          testId="review-ok"
          problem={{
            tone: 'ok',
            title: 'Фабрика примет канал',
            message:
              'Проверка шла всухую: ничего не записано. Позицию фабрика проверит целиком, когда мастер будет её записывать, — вторым шагом, сразу после создания.',
            errors: [],
            details: [],
          }}
        />
      ) : null}

      {result?.files.length ? (
        <div className="grid gap-2">
          <div className="font-semibold">Что фабрика запишет: {result.files.length} файла</div>
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {result.files.map((f) => (
              <li key={f.path} className="grid gap-0.5 rounded-sm border px-3 py-2">
                <span>{fileLabel(f.path)}</span>
                <More label="Файл целиком" className="mt-0">
                  <span>{f.path}</span>
                  <pre className="m-0 max-h-[320px] overflow-auto rounded-sm bg-muted p-2 text-[11px] leading-[1.45] whitespace-pre">
                    {f.text}
                  </pre>
                </More>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-1" data-testid="review-diff">
        <div className="font-semibold">Ваши правки сверх шаблона</div>
        {stance ? (
          <>
            <p className="m-0 text-muted-foreground">
              Позиция канала: одна фраза вместо пустой заготовки. Запишется второй правкой.
            </p>
            <More label="Разница с шаблоном" className="mt-0">
              <pre className="m-0 overflow-auto rounded-sm bg-muted p-2 text-[11px] leading-[1.45] whitespace-pre">
                {diff.map((l, i) => (
                  <span
                    key={i}
                    className={cn(
                      'block',
                      l.kind === '+' && 'text-success',
                      l.kind === '-' && 'text-danger',
                    )}
                  >
                    {l.kind} {l.text}
                  </span>
                ))}
              </pre>
            </More>
          </>
        ) : (
          <p className="m-0 text-muted-foreground">
            Нет — канал создаётся ровно по шаблону фабрики.
          </p>
        )}
      </div>
    </div>
  );
}

function CreateStep({
  name,
  withStance,
  locked,
  lockMessage,
  refreshing,
  batchesSeen,
  ready,
  run,
  failure,
  onCreate,
}: {
  name: string;
  withStance: boolean;
  locked: boolean;
  lockMessage: string | null;
  /** Фабрика как раз сканирует батчи заново (`lock.checking`). */
  refreshing: boolean;
  /** «проверено 12 с назад». */
  batchesSeen: string | null;
  ready: boolean;
  run: Run;
  failure: Problem | null;
  onCreate: () => void;
}) {
  const writes = useWrites();
  const why = !writes.allowed
    ? readOnlyTip(writes.reason ?? '')
    : locked
      ? (lockMessage ?? 'Идёт батч: пока он не закончится, канал не создать')
      : !ready
        ? 'Фабрика не приняла входы — вернитесь к шагу «Имя и id»'
        : null;
  const button = (
    <WriteButton
      variant="default"
      why={why}
      aria-disabled={run ? true : undefined}
      onClick={() => {
        if (!why && !run) onCreate();
      }}
      data-testid="create"
    >
      {run ? 'Создаю…' : `Создать канал ${name}`}
    </WriteButton>
  );
  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5" data-testid="plan">
        <div className="font-semibold">Что произойдёт</div>
        <ol className="m-0 grid gap-1 pl-5">
          <li>
            Фабрика создаст канал по шаблону — одна правка из трёх файлов
            {withStance ? ', позиция — уже с вашей фразой' : ''}. Перед этим она убеждается, что не
            идёт ни один батч: это может занять до минуты.
          </li>
          {withStance ? (
            <li>
              Фразу фабрика проверяет вместе с каналом: если не примет, не создастся ничего, а
              мастер покажет её замечания на шаге «Тематика и позиция».
            </li>
          ) : null}
          <li>Откроется редактор нового канала.</li>
        </ol>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {button}
        {run ? (
          <span role="status" className="animate-pulse text-muted-foreground">
            Создаю канал: фабрика проверяет, что не идёт ни один батч…
          </span>
        ) : why ? (
          <span className="text-[13px] text-muted-foreground" data-testid="create-why">
            {why}
          </span>
        ) : null}
      </div>
      {!run && (refreshing || batchesSeen) ? (
        <p
          className="m-0 text-xs text-muted-foreground"
          data-testid={refreshing ? 'lock-refresh' : 'lock-fresh'}
        >
          {refreshing
            ? 'Фабрика заново смотрит, не идёт ли батч.'
            : `Идёт ли батч, фабрика ${batchesSeen!.replace(/^проверено/, 'проверила')}.`}{' '}
          Нажать «Создать» можно и сейчас: при создании она проверит это ещё раз.
        </p>
      ) : null}
      {failure ? <Problems testId="create-failed" problem={failure} /> : null}
    </div>
  );
}
