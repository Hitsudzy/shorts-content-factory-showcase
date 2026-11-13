// Экран канала: обзор, настройки формой по блокам, «сырой JSON», история правок.
// Черновик — тексты обоих файлов (конфиг и позиция); форма правит их точечно, без
// переформатирования, и в API уходит именно текст (`config_text`), а с ним — `base`.
import { useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useMemo, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router';

import {
  ChannelError,
  channelKeys,
  useChannel,
  useCheckChannel,
  useSaveChannel,
  type ChannelDetail,
  type ChannelEdit,
  type CheckLine,
} from '@/api/channels';
import { AskButton } from '@/components/ask/AskDialog';
import { Card } from '@/components/common/Card';
import { ConfirmAction } from '@/components/common/ConfirmAction';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { ConfigForm } from './ConfigForm';
import {
  changedKeys,
  channelName,
  errorKeys,
  errorTarget,
  fieldKey,
  humanCheck,
  jsonProblems,
  readDoc,
  setValue,
  type FileKind,
} from './fields';
import { landingOf, todoItems, type WizardLanding } from './firstBatch';
import { useFreshness } from './useFreshness';
import { ChannelData } from './ChannelData';
import { History } from './History';
import { Avatar, ChannelState } from './identity';
import { OverviewRows } from './parts';
import { problemOf, type Problem } from './problem';
import { Problems } from './Problems';
import { TodoList } from './TodoList';
import { Pending, SkeletonCard, SkeletonList } from '@/components/common/Skeletons';

const RawEditor = lazy(() => import('./RawEditor'));

type Tab = 'form' | 'raw' | 'history' | 'data';
const TABS: { id: Tab; label: string; tip: string }[] = [
  {
    id: 'form',
    label: 'Настройки',
    tip: 'Конфиг и позиция канала формой: блок на каждый раздел, подсказка у каждого поля',
  },
  {
    id: 'raw',
    label: 'Сырой JSON',
    tip: 'Файл целиком, как он лежит в фабрике: с подсветкой и проверкой записи',
  },
  {
    id: 'history',
    label: 'История',
    tip: 'Кто и когда менял файлы канала; правку из центра можно вернуть',
  },
  {
    id: 'data',
    label: 'Данные канала',
    tip: 'Концовка, источники фактов и партнёрские ссылки канала — посмотреть',
  },
];

/** `v` растёт с каждой правкой черновика: по нему видно, что итог проверки устарел. */
type Draft = { rev: string; v: number; config: string; stance: string | null };

const fresh = (d: ChannelDetail): Draft => ({
  rev: d.revision,
  v: 0,
  config: d.config_text,
  stance: d.stance_text,
});

export function ChannelPage() {
  const { channel } = useParams();
  const q = useChannel(channel);
  if (q.isPending)
    return (
      <Pending label="Загружаю канал…" className="gap-(--space-gap)">
        <SkeletonCard bare rows={2} />
        <SkeletonCard bare rows={0}>
          <SkeletonList bare rows={6} badge={false} />
        </SkeletonCard>
      </Pending>
    );
  if (q.isError) {
    const p = q.error instanceof ChannelError ? q.error.problem : null;
    if (p?.code === 'unknown_channel')
      return (
        <EmptyState title="Такого канала нет">
          {p.message}{' '}
          <Link className="text-primary-text" to="/channels">
            К списку каналов
          </Link>
        </EmptyState>
      );
    return (
      <ErrorState
        title="Не удалось загрузить канал"
        error={q.error}
        onRetry={() => void q.refetch()}
      >
        {p?.message ?? 'Проверьте, что API фабрики запущен.'}
      </ErrorState>
    );
  }
  return <ChannelEditor detail={q.data} receivedAt={q.dataUpdatedAt} />;
}

function ChannelEditor({ detail, receivedAt }: { detail: ChannelDetail; receivedAt: number }) {
  const qc = useQueryClient();
  // Блокировка — по последнему скану батчей фабрики: насколько он свежий.
  const batchesSeen = useFreshness(detail.lock, receivedAt);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get('tab'))?.id ?? 'form') as Tab;
  /** Вкладки правки (форма, сырой JSON): у них — проверка, итог и кнопки сохранения. */
  const editing = tab === 'form' || tab === 'raw';
  const setTab = (t: Tab) =>
    setParams(
      (p) => {
        if (t === 'form') p.delete('tab');
        else p.set('tab', t);
        return p;
      },
      { replace: true },
    );
  const [rawFile, setRawFile] = useState<FileKind>('config');

  // Пришли из мастера «Новый канал»: что создано (один коммит, позиция — в нём же).
  const location = useLocation();
  const [landing] = useState(() => landingOf(location.state));
  const [draft, setDraft] = useState<Draft>(() => fresh(detail));
  const [problem, setProblem] = useState<Problem | null>(null);
  const [problemFor, setProblemFor] = useState<number | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<{ key: string; n: number } | null>(null);
  if (draft.rev !== detail.revision) {
    // Файлы канала сменились (сохранение, «вернуть», «загрузить заново»): черновик — с них.
    setDraft(fresh(detail));
    setProblem(null);
    setPending(new Set());
  }

  const check = useCheckChannel(detail.id);
  const save = useSaveChannel(detail.id);

  const docs = useMemo(
    () => ({ config: readDoc(draft.config), stance: readDoc(draft.stance) }),
    [draft.config, draft.stance],
  );
  const savedDocs = useMemo(
    () => ({ config: detail.config, stance: detail.stance }),
    [detail.config, detail.stance],
  );
  const changed = useMemo(
    () => changedKeys(detail.fields, docs, savedDocs),
    [detail.fields, docs, savedDocs],
  );
  const syntax = useMemo(
    () => ({
      config: jsonProblems(draft.config),
      stance: draft.stance === null ? [] : jsonProblems(draft.stance),
    }),
    [draft.config, draft.stance],
  );
  const dirty = draft.config !== detail.config_text || draft.stance !== detail.stance_text;
  const locked = detail.lock.locked;
  const broken = syntax.config.length > 0 || syntax.stance.length > 0;
  const draftKey = draft.v;
  const changedCount = useMemo(
    () =>
      detail.fields.filter((f) => f.kind !== 'object' && changed.has(fieldKey(f.file, f.path)))
        .length,
    [detail.fields, changed],
  );

  // Ошибки проверки — на поля формы; устаревают, как только черновик поменяли после проверки.
  const lines: readonly CheckLine[] = useMemo(() => problem?.errors ?? [], [problem]);
  const fieldErrors = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const k of errorKeys(lines)) m.set(k, []);
    for (const l of lines) {
      const t = errorTarget(l.field);
      if (!t) continue;
      const h = humanCheck(l);
      m.get(fieldKey(t.file, t.path))?.push(h.ru ? h.why : `Не прошло проверку: ${h.why}`);
    }
    return m;
  }, [lines]);

  const onChange = useCallback((file: FileKind, path: readonly string[], value: unknown) => {
    setDraft((d) => {
      const text = d[file];
      if (text === null) return d;
      return { ...d, v: d.v + 1, [file]: setValue(text, path, value) };
    });
    setSaved(null);
  }, []);
  const onPending = useCallback((key: string, p: boolean) => {
    setPending((s) => {
      if (s.has(key) === p) return s;
      const next = new Set(s);
      if (p) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);
  const jump = (line: CheckLine) => {
    const t = errorTarget(line.field);
    if (!t) return;
    setTab('form');
    setFocus((f) => ({ key: fieldKey(t.file, t.path), n: (f?.n ?? 0) + 1 }));
  };

  const body = (): ChannelEdit => ({
    base: detail.revision,
    config_text: draft.config,
    ...(draft.stance !== null && draft.stance !== detail.stance_text
      ? { stance_text: draft.stance }
      : {}),
    ...(note.trim() ? { note: note.trim() } : {}),
  });

  const runCheck = () => {
    setSaved(null);
    check.mutate(body(), {
      onSuccess: (r) => {
        setProblemFor(draftKey);
        setProblem(
          r.ok
            ? {
                tone: 'ok',
                title: 'Проверка пройдена',
                message: 'Фабрика примет эту правку.',
                errors: [],
                details: [],
              }
            : {
                tone: 'danger',
                title: 'Проверка не пройдена',
                message: `Фабрика не примет правку: ${r.errors.length} ${r.errors.length === 1 ? 'замечание' : r.errors.length < 5 ? 'замечания' : 'замечаний'}. Ничего не сохранено.`,
                errors: r.errors,
                details: [],
              },
        );
      },
      onError: (e) => {
        setProblemFor(draftKey);
        setProblem(problemOf(e, 'Проверить не получилось'));
      },
    });
  };

  const runSave = () => {
    setSaved(null);
    save.mutate(body(), {
      onSuccess: (r) => {
        setProblem(null);
        setNote('');
        setSaved(r.subject.replace(/\s*\(из центра\)$/, ''));
      },
      onError: (e) => {
        setProblemFor(draftKey);
        // Идёт батч — блокировку перечитывает сам useSaveChannel; черновик остаётся.
        setProblem(problemOf(e, 'Не сохранено'));
      },
    });
  };

  const reload = () => {
    setProblem(null);
    setSaved(null);
    void qc.invalidateQueries({ queryKey: channelKeys.detail(detail.id) });
    void qc.invalidateQueries({ queryKey: channelKeys.list, exact: true });
  };
  const conflict = problem?.code === 'conflict';
  const stale = problem !== null && problemFor !== draftKey && problem.tone !== 'ok';

  const whyNoSave = locked
    ? (detail.lock.message ?? 'Идёт батч канала: правка закрыта')
    : broken
      ? 'Сначала исправьте запись JSON — ошибки показаны во вкладке «Сырой JSON»'
      : pending.size
        ? 'В форме есть значение, которое не читается: исправьте поле, отмеченное красным'
        : !dirty
          ? 'Правок нет — сохранять нечего'
          : null;
  const busy = save.isPending || check.isPending;
  const name = channelName(detail);

  return (
    <>
      <div className="grid gap-1">
        <Link to="/channels" className="w-max text-xs text-primary-text">
          ← Все каналы
        </Link>
      </div>
      <Card aria-labelledby="channel-title" className="grid gap-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <Avatar id={detail.id} name={name} className="size-[42px] text-base" />
          {/* На телефоне имя занимает всю строку рядом с аватаром, метка и «Попросить» — строкой
              ниже: длинное имя канала не наезжает на них (CC-0138). */}
          <div className="min-w-0 flex-1 basis-[calc(100%-54px)] sm:basis-0">
            <div className="eyebrow">Канал</div>
            <h1
              id="channel-title"
              className="font-display text-[26px] leading-tight font-semibold tracking-[.02em] [overflow-wrap:anywhere] uppercase"
            >
              {name}
            </h1>
          </div>
          <ChannelState c={{ error: null, locked, no_pipeline: detail.no_pipeline }} />
          <AskButton
            testId="ask-channel"
            label="Попросить"
            tip="Попросить оператора об этом канале: канал подставится сам"
            target={{ channel: detail.id }}
          />
        </div>
        <ul className="m-0 grid list-none gap-x-8 p-0 md:grid-cols-2">
          <OverviewRows
            channel={detail.id}
            summary={{ locked, no_pipeline: detail.no_pipeline }}
            detail={detail}
            loading={false}
            fresh={batchesSeen}
          />
        </ul>
        {detail.errors.length ? (
          <Problems
            testId="factory-errors"
            onJump={jump}
            problem={{
              tone: 'warn',
              title: 'Фабрика уже сейчас находит замечания в файлах канала',
              message: 'Их нужно исправить, иначе следующая правка не сохранится.',
              errors: detail.errors,
              details: [],
            }}
          />
        ) : null}
        <More className="mt-0">
          <span>канал: {detail.id}</span>
          <span>конфиг: {detail.config_path}</span>
          {detail.stance_path ? <span>позиция: {detail.stance_path}</span> : null}
          <span>ревизия: {detail.revision}</span>
          {batchesSeen ? <span data-testid="lock-fresh">батчи: {batchesSeen}</span> : null}
          {detail.no_pipeline ? <span>{detail.no_pipeline}</span> : null}
        </More>
      </Card>

      {landing ? <WizardBanner landing={landing} detail={detail} /> : null}

      {locked ? (
        <div
          role="status"
          data-testid="lock-banner"
          className="grid gap-1.5 rounded-lg border border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] px-card py-3.5"
        >
          <div className="font-semibold text-warning">Правка закрыта, пока идёт батч</div>
          <p className="m-0">{detail.lock.message}</p>
          <p className="m-0 text-muted-foreground">
            Смотреть настройки и историю можно; сохранить и вернуть — когда батч закончится.
          </p>
          {detail.lock.batches.length ? (
            <More className="mt-0">
              {detail.lock.batches.map((b) => (
                <span key={b.dir}>
                  батч: {b.dir}
                  {b.last ? ` · последнее событие ${b.last}` : ''}
                </span>
              ))}
              {batchesSeen ? <span>батчи: {batchesSeen}</span> : null}
            </More>
          ) : null}
        </div>
      ) : null}

      <div
        role="tablist"
        aria-label="Вид"
        className="no-scrollbar flex w-full max-w-full gap-0.5 overflow-x-auto rounded-lg border bg-card p-0.5 sm:w-max"
      >
        {TABS.map((t) => (
          <Tip key={t.id} content={t.tip}>
            <button
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex-1 rounded-sm px-3.5 py-1.5 text-[13px] whitespace-nowrap text-muted-foreground sm:flex-none',
                tab === t.id && 'bg-muted font-semibold text-foreground',
              )}
            >
              {t.label}
            </button>
          </Tip>
        ))}
      </div>

      {editing && problem ? (
        <Problems
          problem={
            stale ? { ...problem, title: `${problem.title} (до последних правок)` } : problem
          }
          onJump={jump}
          testId="check-result"
          action={
            conflict ? (
              dirty ? (
                <ConfirmAction
                  trigger={<Button size="sm">Загрузить свежую версию</Button>}
                  title="Загрузить свежую версию канала?"
                  description="Ваши несохранённые правки пропадут. Если они нужны, скопируйте их из вкладки «Сырой JSON» до загрузки."
                  confirmLabel="Загрузить"
                  onConfirm={reload}
                />
              ) : (
                <Button size="sm" onClick={reload}>
                  Загрузить свежую версию
                </Button>
              )
            ) : null
          }
        />
      ) : null}
      {editing && saved ? (
        <Problems
          testId="saved"
          problem={{ tone: 'ok', title: 'Сохранено', message: saved, errors: [], details: [] }}
        />
      ) : null}

      {tab === 'form' ? (
        docs.config === null ? (
          <ErrorState title="Текст конфига сейчас не читается как JSON">
            Форма покажется снова, когда запись станет правильной: исправьте её во вкладке «Сырой
            JSON» или отмените правки.
          </ErrorState>
        ) : (
          <ConfigForm
            fields={detail.fields}
            docs={docs}
            errors={fieldErrors}
            changed={changed}
            disabled={locked || busy}
            disabledWhy={locked ? 'Поля только для чтения: идёт батч канала' : null}
            onChange={onChange}
            onPending={onPending}
            focus={focus}
          />
        )
      ) : tab === 'raw' ? (
        <section className="grid gap-2" aria-label="Сырой JSON">
          {detail.stance_text !== null ? (
            <div
              role="group"
              aria-label="Файл"
              className="flex w-max gap-0.5 rounded-lg border bg-card p-0.5"
            >
              {(['config', 'stance'] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  aria-pressed={rawFile === f}
                  onClick={() => setRawFile(f)}
                  className={cn(
                    'rounded-sm px-3 py-1 text-xs text-muted-foreground',
                    rawFile === f && 'bg-muted font-semibold text-foreground',
                  )}
                >
                  {f === 'config' ? 'Конфиг' : 'Позиция'}
                </button>
              ))}
            </div>
          ) : null}
          <Suspense
            fallback={
              <p role="status" className="m-0 animate-pulse text-muted-foreground">
                Открываю редактор…
              </p>
            }
          >
            <RawEditor
              key={rawFile}
              label={rawFile === 'config' ? 'Конфиг канала, JSON' : 'Позиция канала, JSON'}
              value={(rawFile === 'stance' ? draft.stance : draft.config) ?? ''}
              readOnly={locked || busy}
              onChange={(text) => {
                setSaved(null);
                setDraft((d) => ({ ...d, v: d.v + 1, [rawFile]: text }));
              }}
            />
          </Suspense>
          {syntax[rawFile].length ? (
            <div role="alert" data-testid="syntax" className="text-danger">
              Запись JSON с ошибкой — строка {syntax[rawFile][0]!.line}, столбец{' '}
              {syntax[rawFile][0]!.column}: {syntax[rawFile][0]!.text}.
              {syntax[rawFile].length > 1 ? ` И ещё ${syntax[rawFile].length - 1}.` : ''}
            </div>
          ) : (
            <p className="m-0 text-xs text-muted-foreground">
              Запись JSON правильная. «Проверить» спросит фабрику, примет ли она содержимое.
            </p>
          )}
        </section>
      ) : tab === 'data' ? (
        <ChannelData channel={detail.id} />
      ) : (
        <History detail={detail} dirty={dirty} />
      )}

      {editing ? (
        <div
          data-testid="save-bar"
          className="sticky bottom-0 z-[5] -mx-gutter grid gap-2 border-t bg-background/95 px-gutter py-3 backdrop-blur sm:mx-0 sm:rounded-lg sm:border sm:bg-card sm:px-card"
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="text-[13px]" data-testid="draft-state">
              {dirty
                ? changedCount
                  ? `Не сохранено, изменено полей: ${changedCount}`
                  : 'Не сохранено: изменён текст файла'
                : 'Правок нет'}
            </span>
            {save.isPending ? (
              <span role="status" className="text-xs text-muted-foreground">
                Сохраняю: фабрика проверяет правку и открытые батчи — это может занять несколько
                секунд.
              </span>
            ) : check.isPending ? (
              <span role="status" className="text-xs text-muted-foreground">
                Проверяю…
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="edit-note" className="sr-only">
              Зачем эта правка
            </label>
            <input
              id="edit-note"
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={locked}
              placeholder="Зачем правка (необязательно, попадёт в историю)"
              className="h-[34px] min-w-0 flex-[1_1_220px] rounded-sm border border-input bg-background px-2.5 text-[13px] outline-none focus-visible:border-ring disabled:opacity-60"
            />
            <div className="flex flex-[1_1_auto] flex-wrap justify-end gap-2">
              {dirty && !busy ? (
                <ConfirmAction
                  trigger={<Button variant="ghost">Отменить правки</Button>}
                  title="Отменить несохранённые правки?"
                  description="Форма и текст файла вернутся к тому, что сейчас лежит в фабрике."
                  confirmLabel="Отменить правки"
                  cancelLabel="Оставить"
                  onConfirm={() => {
                    setDraft(fresh(detail));
                    setProblem(null);
                    setPending(new Set());
                  }}
                />
              ) : null}
              <SaveButton
                why={locked ? whyNoSave : broken ? whyNoSave : null}
                busy={busy}
                onClick={runCheck}
                tip="Спросить фабрику, примет ли она правку. Ничего не сохраняется"
              >
                {check.isPending ? 'Проверяю…' : 'Проверить'}
              </SaveButton>
              <SaveButton
                primary
                writes
                why={whyNoSave}
                busy={busy}
                onClick={runSave}
                tip="Фабрика проверит правку и сохранит её коммитом; потом её можно вернуть из истории"
              >
                {save.isPending ? 'Сохраняю…' : 'Сохранить'}
              </SaveButton>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

/** Итог мастера «Новый канал» и что ещё нужно до первого батча. */
function WizardBanner({ landing, detail }: { landing: WizardLanding; detail: ChannelDetail }) {
  const todo = useMemo(
    () => todoItems(detail.config, detail.stance, detail.no_pipeline),
    [detail.config, detail.stance, detail.no_pipeline],
  );
  return (
    <>
      <div
        role="status"
        data-testid="wizard-landing"
        className="grid gap-1.5 rounded-lg border border-[color-mix(in_srgb,var(--success)_40%,var(--border))] bg-[color-mix(in_srgb,var(--success)_7%,var(--card))] px-card py-3.5"
      >
        <div className="font-semibold text-success">Канал создан</div>
        <p className="m-0">
          {landing.withStance
            ? 'Канал создан по шаблону фабрики — с вашей позицией, одной правкой.'
            : 'Канал создан по шаблону фабрики.'}
        </p>
        <More className="mt-0">
          <span>{landing.created}</span>
        </More>
      </div>
      <TodoList items={todo} />
    </>
  );
}

function SaveButton({
  primary = false,
  writes = false,
  why,
  busy,
  onClick,
  tip,
  children,
}: {
  primary?: boolean;
  /** Кнопка пишет в фабрику (CC-0059): вне рабочей фабрики погашена с причиной. */
  writes?: boolean;
  why: string | null;
  busy: boolean;
  onClick: () => void;
  tip: string;
  children: React.ReactNode;
}) {
  const variant = primary ? 'default' : 'outline';
  if (writes)
    return (
      <WriteButton
        variant={variant}
        why={why}
        tip={tip}
        disabled={busy}
        onClick={onClick}
        data-testid="channel-save"
      >
        {children}
      </WriteButton>
    );
  if (why)
    return (
      <Tip content={why}>
        <Button variant={variant} aria-disabled onClick={(e) => e.preventDefault()}>
          {children}
        </Button>
      </Tip>
    );
  return (
    <Tip content={tip}>
      <Button variant={variant} disabled={busy} onClick={onClick}>
        {children}
      </Button>
    </Tip>
  );
}
