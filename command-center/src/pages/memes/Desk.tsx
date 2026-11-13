// Стол мемов банка (CC-0025): сводка, отметки (черновик центра → «Сохранить отметки» с `base`),
// «Применить разбор», поиск по меткам и состоянию, сетка и просмотр мема с клавишами для
// быстрого разбора. Чужое изменение черновика (`check_changed` или новый отпечаток при
// несохранённом) центр не затирает: говорит словами и предлагает загрузить отметки заново.
import { useMutation } from '@tanstack/react-query';
import { useEffect, useEffectEvent, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { useSearchParams } from 'react-router';

import { BatchError, problemCode } from '@/api/batchProblem';
import {
  putMarks,
  useAfterMemes,
  useMemeDesk,
  type MemeApplyResult,
  type MemeDesk,
  type MemeEntry,
  type SavedMark,
} from '@/api/memes';
import { nbDashes } from '@/api/humanText';
import { NO_REASON_TEXT } from '@/api/reasonRu';
import { useWrites } from '@/api/writes';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Refusal } from '@/pages/batches/parts';
import { inputBase } from '@/pages/channels/styles';

import { AddPanel, AddToggle, type AddTab, type GifSeed } from './Add';
import { ApplyAction, ApplyDone } from './Apply';
import {
  bodyOf,
  changedIds,
  cutOf,
  draftStore,
  stateOf,
  staleIds,
  useDraft,
  withCut,
  withNote,
  withVerdict,
  wholeOf,
  type Marks,
  type MemeState,
  type Verdict,
} from './draft';
import { bandWords, marksWord, memeName, memesWord, matches, topTags } from './format';
import { MemeCard } from './Grid';
import { JobCard } from './Job';
import { afterDash, busyWhy, namesIn, useBankJob } from './jobs';
import { BankTools, JobResult, ToolsToggle } from './Tools';
import { KEYS_TIP, Viewer } from './Viewer';
import { SkeletonTiles } from '@/components/common/Skeletons';

type Filter = 'all' | MemeState | 'cut' | 'whole';

const NO_MARKS: Marks = {};

const FILTERS: { id: Filter; label: string; tip: string }[] = [
  { id: 'all', label: 'Все', tip: 'Все мемы банка' },
  { id: 'new', label: 'Не разобраны', tip: 'Новые мемы, по которым ещё нет решения' },
  { id: 'keep', label: 'Оставить', tip: 'Отмечены «оставить»' },
  { id: 'drop', label: 'Убрать', tip: 'Отмечены «убрать»' },
  { id: 'cut', label: 'С вырезкой', tip: 'Отмечены «можно вырезать»' },
  { id: 'whole', label: 'Целиком', tip: 'Не отмечены «можно вырезать»; GIF — всегда целиком' },
  { id: 'in', label: 'В библиотеке', tip: 'Уже в библиотеке, без решения' },
];

const SEARCH_HINT = 'Поиск: имя, описание, метка';

/** Узкий экран (телефон): подсказки покороче. */
const NARROW = '(max-width: 639px)';
function useNarrow() {
  return useSyncExternalStore(
    (on) => {
      if (typeof window.matchMedia !== 'function') return () => {};
      const m = window.matchMedia(NARROW);
      m.addEventListener('change', on);
      return () => m.removeEventListener('change', on);
    },
    () => typeof window.matchMedia === 'function' && window.matchMedia(NARROW).matches,
    () => false,
  );
}

function fits(f: Filter, entry: MemeEntry, marks: Marks) {
  if (f === 'all') return true;
  if (f === 'cut') return cutOf(entry, marks[entry.id]);
  if (f === 'whole') return wholeOf(entry, marks[entry.id]);
  return stateOf(entry, marks[entry.id]) === f;
}

/** Набирает ли человек текст (тогда клавиши разбора молчат). */
function typing(t: EventTarget | null) {
  const el = t as HTMLElement | null;
  if (!el) return false;
  return (
    el.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) ||
    !!el.closest?.('[role="alertdialog"],[role="dialog"]')
  );
}

function Notices({ desk, stale }: { desk: MemeDesk; stale: string[] }) {
  const st = desk.status;
  const share = Math.round((st.blank_band_min_share ?? 0) * 100);
  const items = [
    stale.length ? (
      <li key="stale" data-testid="notice-stale">
        Есть отметки мемов, которых в банке уже нет: {stale.length}. Фабрика их не учитывает, центр
        уберёт их при сохранении.
        <More className="mt-0.5">
          {stale.map((id) => (
            <span key={id}>{id}</span>
          ))}
        </More>
      </li>
    ) : null,
    st.blank_bands.length ? (
      <li key="bands" data-testid="notice-bands">
        У {memesWord(st.blank_bands.length)} пустая полоса подписи — больше {share}% высоты. Её
        срежет фабрика, сам мем не меняется.{' '}
        <details className="inline">
          <summary className="inline cursor-pointer text-primary-text">Какие мемы</summary>
          <ul className="m-0 mt-1 grid list-disc gap-0.5 pl-5">
            {st.blank_bands.map((b) => (
              <li key={b.id}>
                {memeName(b.id)} — {bandWords(b)}
              </li>
            ))}
          </ul>
          <More className="mt-1">
            {st.blank_bands.map((b) => (
              <span key={b.id}>
                {b.id}: {b.phrase}
              </span>
            ))}
          </More>
        </details>
      </li>
    ) : null,
    st.blank_band_errors.length ? (
      <li key="band-errors" data-testid="notice-band-errors">
        Не удалось проверить на пустые полосы: {memesWord(st.blank_band_errors.length)}.
        <ul className="m-0 mt-1 grid list-disc gap-0.5 pl-5">
          {st.blank_band_errors.map((e, i) => (
            <li key={`${e.id}-${i}`} className="[overflow-wrap:anywhere]">
              {memeName(e.id)} —{' '}
              {e.error && /[а-яё]/i.test(e.error) ? afterDash(e.error) : NO_REASON_TEXT}
            </li>
          ))}
        </ul>
        <More className="mt-1">
          {st.blank_band_errors.map((e, i) => (
            <span key={i}>
              {e.id}: {e.error}
              {e.en ? ` (${e.en})` : ''}
            </span>
          ))}
        </More>
      </li>
    ) : null,
    !st.blank_bands_checked ? (
      <li key="unchecked" data-testid="notice-unchecked">
        Пустые полосы подписи сейчас не проверены — фабрике не хватило инструмента для картинок.
        {st.blank_bands_note && /[а-яё]/i.test(st.blank_bands_note) ? (
          <span className="block text-muted-foreground" data-testid="bands-note">
            {nbDashes(st.blank_bands_note)}
          </span>
        ) : null}
        {st.blank_bands_note || st.blank_bands_note_en ? (
          <More className="mt-1">
            {st.blank_bands_note ? <span>{st.blank_bands_note}</span> : null}
            {st.blank_bands_note_en ? <span>{st.blank_bands_note_en}</span> : null}
          </More>
        ) : null}
      </li>
    ) : null,
  ].filter(Boolean);
  if (!items.length) return null;
  return (
    <div
      role="status"
      data-testid="desk-notices"
      aria-labelledby="desk-notices-title"
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] px-3 py-2 text-[13px]"
    >
      <h3 id="desk-notices-title" className="text-[13px] font-semibold">
        Что заметила фабрика
      </h3>
      <ul className="m-0 grid list-none gap-1.5 p-0">{items}</ul>
    </div>
  );
}

export function Desk({ channel, bankLabel }: { channel: string; bankLabel: string }) {
  const desk = useMemeDesk(channel);
  const data = desk.data;
  const draft = useDraft(data);
  const writes = useWrites();
  const after = useAfterMemes();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [tags, setTags] = useState<string[]>([]);
  const viewer = useRef<HTMLDivElement>(null);
  const scrollAsked = useRef(false);
  const [done, setDone] = useState<MemeApplyResult | null>(null);
  const bankJob = useBankJob(channel, data?.job);
  const [tools, setTools] = useState(false);
  const [adding, setAdding] = useState<{ tab: AddTab; seed: GifSeed | null } | null>(null);
  const narrow = useNarrow();
  const chips = useRef<HTMLDivElement>(null);
  const [chipsFade, setChipsFade] = useState(false);
  const fadeChips = () => {
    const el = chips.current;
    setChipsFade(!!el && el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  };
  useEffect(() => {
    fadeChips();
    window.addEventListener('resize', fadeChips);
    return () => window.removeEventListener('resize', fadeChips);
  });

  useEffect(() => {
    if (data) draftStore.sync(data);
  }, [data]);

  const bank = data?.bank ?? '';
  const entries = useMemo(() => data?.entries ?? [], [data]);
  const ids = useMemo(() => new Set(entries.map((e) => e.id)), [entries]);
  const local = draft?.local ?? NO_MARKS;
  const changed = draft ? changedIds(draft.local, draft.saved).filter((id) => ids.has(id)) : [];
  const stale = staleIds(local, ids);

  const save = useMutation({
    mutationFn: (v: { sent: Marks; base: string | null }) =>
      putMarks(channel, bodyOf(v.sent, ids), v.base),
    onSuccess: (r, v) => {
      draftStore.saved(bank, r.fingerprint ?? null, v.sent);
    },
    onError: (e) => {
      if (problemCode(e) === 'check_changed') draftStore.conflict(bank);
    },
    onSettled: () => void after(),
  });

  const shown = useMemo(
    () =>
      entries.filter(
        (e) =>
          fits(filter, e, local) && matches(e, q) && tags.every((t) => (e.tags ?? []).includes(t)),
      ),
    [entries, filter, local, q, tags],
  );

  const openId = params.get('m');
  const opened = openId ? (entries.find((e) => e.id === openId) ?? null) : null;
  const at = opened ? shown.findIndex((e) => e.id === opened.id) : -1;
  const open = (id: string | null, scroll = false) => {
    const p = new URLSearchParams(params);
    if (id) p.set('m', id);
    else p.delete('m');
    scrollAsked.current = scroll && !!id;
    setParams(p, { replace: true });
  };
  // Мем открыли из сетки или клавишей: просмотр — в поле зрения (на телефоне он над сеткой).
  useEffect(() => {
    if (!scrollAsked.current || !opened) return;
    scrollAsked.current = false;
    viewer.current?.scrollIntoView?.({ block: 'nearest' });
  }, [opened]);
  const step = (d: 1 | -1) => {
    if (!shown.length) return null;
    if (at < 0) return d === 1 ? shown[0]!.id : shown[shown.length - 1]!.id;
    return shown[at + d]?.id ?? null;
  };

  const edit = (fn: (l: Marks, s: Marks) => Marks) => {
    if (!data || !writes.allowed) return;
    draftStore.edit(bank, data, fn);
  };
  const verdict = (id: string, v: Verdict, toggle = true) =>
    edit((l) => withVerdict(l, id, v, toggle));
  const cut = (e: MemeEntry) => edit((l, s) => withCut(l, s[e.id], e));

  // Клавиши разбора: слушатель один, обработчик видит свежее состояние (useEffectEvent).
  const onKey = useEffectEvent((e: KeyboardEvent) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || typing(e.target)) return;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const id = step(e.key === 'ArrowRight' ? 1 : -1);
      if (id) {
        e.preventDefault();
        open(id, true);
      }
      return;
    }
    if (e.key === 'Escape' && opened) {
      open(null);
      return;
    }
    if (!opened || !writes.allowed) return;
    if (e.code === 'KeyK' || e.code === 'KeyD') {
      e.preventDefault();
      const next = step(1);
      verdict(opened.id, e.code === 'KeyK' ? 'keep' : 'drop', false);
      if (next) open(next, true);
    } else if (e.code === 'KeyC') {
      e.preventDefault();
      cut(opened);
    }
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => onKey(e);
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  // Уход со страницы с несохранёнными отметками — браузер переспросит.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (draftStore.anyDirty()) e.preventDefault();
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, []);

  if (desk.isPending)
    return (
      <SkeletonTiles
        count={8}
        aspect="4 / 3"
        badge={false}
        className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-4"
        label="Читаю банк мемов…"
      />
    );
  if (desk.isError || !data || !draft)
    return (
      <ErrorState
        title="Банк мемов не прочитать"
        error={desk.error}
        onRetry={() => void desk.refetch()}
      >
        {desk.error instanceof BatchError && desk.error.problem
          ? desk.error.problem.message
          : 'Проверьте, что API фабрики запущен.'}
      </ErrorState>
    );

  const counts = Object.fromEntries(
    FILTERS.map((f) => [f.id, entries.filter((e) => fits(f.id, e, local)).length]),
  ) as Record<Filter, number>;
  const popular = topTags(entries);
  const tagList = [...tags.filter((t) => !popular.includes(t)), ...popular];
  const dirty = changed.length > 0;
  const reload = async () => {
    const r = await desk.refetch();
    if (r.data) draftStore.replace(r.data);
    save.reset();
  };
  const conflict = draft.conflict;
  const busy = bankJob.running ? busyWhy(bankJob.running) : null;
  const saveWhy = conflict
    ? 'Отметки изменились в другом месте — сначала загрузите их заново'
    : busy
      ? busy
      : !dirty
        ? 'Несохранённых отметок нет'
        : save.isPending
          ? 'Сохраняю…'
          : undefined;
  const applyWhy = conflict
    ? 'Отметки изменились в другом месте — сначала загрузите их заново'
    : busy
      ? busy
      : dirty
        ? 'Сначала сохраните отметки: фабрика применяет сохранённые'
        : null;

  return (
    <Card
      aria-labelledby="desk-title"
      data-testid="meme-desk"
      data-bank={bank}
      className="grid gap-4"
    >
      <CardHead
        eyebrow={data.default_bank ? 'Банк по умолчанию' : 'Свой банк канала'}
        title={`${memesWord(entries.length)} · новых без решения: ${counts.new}`}
        titleId="desk-title"
      />

      {conflict ? (
        <div
          role="alert"
          data-testid="desk-conflict"
          className="grid gap-2 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-3 text-[13px]"
        >
          <b className="font-semibold text-danger">Отметки изменились в другом месте</b>
          <span>
            Пока вы разбирали мемы, черновик этого банка поменяли — в другой вкладке или на столе в
            терминале. Ваши отметки не сохранены, чтобы не затереть чужие. Загрузите отметки заново
            — ваши несохранённые ({changed.length}) пропадут, их придётся поставить ещё раз.
          </span>
          <div>
            <Button size="sm" onClick={() => void reload()} data-testid="desk-reload">
              Загрузить отметки заново
            </Button>
          </div>
        </div>
      ) : null}

      {done ? <ApplyDone r={done} onClose={() => setDone(null)} /> : null}

      {bankJob.job ? (
        <JobCard
          job={bankJob.job}
          result={
            bankJob.job.done ? (
              <JobResult
                job={bankJob.job}
                onOpen={(id) => open(id, true)}
                onGif={(s) => setAdding({ tab: 'gif', seed: { ...s, n: Date.now() } })}
              />
            ) : null
          }
          onClose={bankJob.close}
          say={(t) => namesIn(t, [...ids])}
        />
      ) : null}
      {bankJob.error ? (
        <Refusal error={bankJob.error} title="Ход задачи банка не прочитать" />
      ) : null}

      {!writes.allowed ? (
        <p className="m-0 text-xs text-muted-foreground" data-testid="desk-readonly">
          Только смотреть: мемы можно листать и искать, а ставить отметки и применять разбор —
          только на рабочей фабрике.
        </p>
      ) : null}

      <Notices desk={data} stale={stale} />

      <div className="grid gap-2" data-testid="meme-filters">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            aria-label="Поиск мемов"
            data-testid="meme-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={narrow ? 'Поиск по мемам' : SEARCH_HINT}
            title={SEARCH_HINT}
            className={cn(
              inputBase,
              'w-auto min-w-0 flex-1 basis-32 max-sm:basis-full sm:max-w-80',
            )}
          />
          <Tip content={KEYS_TIP} wide>
            <Button size="sm" variant="ghost" data-testid="keys-legend" className="max-sm:hidden">
              Клавиши
            </Button>
          </Tip>
          <ToolsToggle open={tools} onToggle={() => setTools(!tools)} />
          <AddToggle
            open={!!adding}
            onToggle={() => setAdding(adding ? null : { tab: 'image', seed: null })}
          />
        </div>
        {tools ? (
          <BankTools
            channel={channel}
            bankLabel={bankLabel}
            desk={data}
            busy={busy}
            onStarted={(s) => bankJob.watch(s.job_id)}
            onSettled={() => void after()}
          />
        ) : null}
        {adding ? (
          <AddPanel
            channel={channel}
            bankLabel={bankLabel}
            ids={[...ids]}
            busy={busy}
            tab={adding.tab}
            onTab={(tab) => setAdding({ ...adding, tab })}
            seed={adding.seed}
            onStarted={(s) => bankJob.watch(s.job_id)}
            onSettled={() => void after()}
          />
        ) : null}
        <div
          ref={chips}
          onScroll={fadeChips}
          data-fade={chipsFade || undefined}
          className={cn(
            'flex gap-1.5 overflow-x-auto pb-1',
            // Ряд шире экрана (телефон): правый край гаснет — видно, что дальше есть ещё.
            chipsFade && '[mask-image:linear-gradient(to_right,#000_calc(100%-2rem),transparent)]',
          )}
          role="group"
          aria-label="Какие мемы показать"
        >
          {FILTERS.map((f) => (
            <Tip key={f.id} content={f.tip}>
              <Button
                size="sm"
                variant={filter === f.id ? 'default' : 'ghost'}
                aria-pressed={filter === f.id}
                data-testid={`filter-${f.id}`}
                onClick={() => setFilter(f.id)}
              >
                {f.label} · {counts[f.id]}
              </Button>
            </Tip>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Метки">
          {tagList.map((t) => {
            const on = tags.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                data-testid="tag-filter"
                onClick={() => setTags(on ? tags.filter((x) => x !== t) : [...tags, t])}
                className={cn(
                  'rounded-full border px-2 py-0.5 text-xs',
                  on
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:border-muted-foreground',
                )}
              >
                {t}
              </button>
            );
          })}
        </div>
        <p className="m-0 text-xs text-muted-foreground" data-testid="meme-shown">
          Показано: {shown.length} из {entries.length}
          {q || tags.length || filter !== 'all' ? (
            <>
              {' · '}
              <button
                type="button"
                className="text-primary-text underline underline-offset-4"
                onClick={() => {
                  setQ('');
                  setTags([]);
                  setFilter('all');
                }}
              >
                сбросить
              </button>
            </>
          ) : null}
        </p>
      </div>

      <div className={cn('grid gap-4', opened && 'lg:grid-cols-[minmax(0,1fr)_minmax(0,400px)]')}>
        {opened ? (
          <div ref={viewer} className="min-w-0 scroll-mt-36 lg:order-2">
            <div className="lg:sticky lg:top-36">
              <Viewer
                key={opened.id}
                entry={opened}
                mark={local[opened.id]}
                saved={data.decisions[opened.id] as SavedMark | undefined}
                changed={changed.includes(opened.id)}
                position={at >= 0 ? `${at + 1} из ${shown.length}` : null}
                onVerdict={(v) => verdict(opened.id, v)}
                onCut={() => cut(opened)}
                onNote={(t) => edit((l) => withNote(l, opened.id, t))}
                onPrev={step(-1) && at >= 0 ? () => open(step(-1)) : null}
                onNext={step(1) ? () => open(step(1)) : null}
                onClose={() => open(null)}
                onTag={(t) => {
                  if (!tags.includes(t)) setTags([...tags, t]);
                }}
              />
            </div>
          </div>
        ) : null}
        <div className="min-w-0">
          {shown.length ? (
            <ul
              data-testid="memes"
              className={cn(
                'm-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3',
                opened ? 'xl:grid-cols-4' : 'lg:grid-cols-5 xl:grid-cols-6',
              )}
            >
              {shown.map((e) => (
                <MemeCard
                  key={e.id}
                  entry={e}
                  mark={local[e.id]}
                  changed={changed.includes(e.id)}
                  selected={opened?.id === e.id}
                  onOpen={() => open(e.id, true)}
                />
              ))}
            </ul>
          ) : (
            <EmptyState title={entries.length ? 'Таких мемов нет' : 'Банк пуст'}>
              {entries.length
                ? 'Поменяйте поиск или фильтр.'
                : 'Новые мемы появятся, когда фабрика их добавит.'}
            </EmptyState>
          )}
        </div>
      </div>

      <div
        data-testid="desk-bar"
        className="sticky bottom-0 z-[5] -mx-1 grid gap-2 rounded-sm border bg-card/95 px-2 pt-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] backdrop-blur-sm sm:flex sm:flex-wrap sm:items-center sm:pb-2"
      >
        <span
          className="min-w-0 truncate text-[13px] sm:flex-1"
          data-testid="desk-unsaved"
          title={dirty ? `Не сохранено: ${marksWord(changed.length)}` : undefined}
        >
          {dirty ? (
            <b className="font-semibold text-primary-text">
              Не сохранено: {changed.length}
              <span className="max-sm:hidden">
                {' '}
                {marksWord(changed.length).replace(/^\d+ /, '')}
              </span>
            </b>
          ) : (
            <span className="text-muted-foreground">Все отметки сохранены</span>
          )}
        </span>
        <div
          className="flex min-w-0 items-center gap-2 max-sm:justify-end"
          data-testid="desk-actions"
        >
          {dirty && !conflict ? (
            <Tip content="Вернуть отметки, как они сохранены в фабрике">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => draftStore.replace(data)}
                data-testid="desk-discard"
              >
                Отменить<span className="max-sm:hidden">&nbsp;правки</span>
              </Button>
            </Tip>
          ) : null}
          <WriteButton
            size="sm"
            variant={dirty ? 'default' : 'outline'}
            why={saveWhy}
            aria-busy={save.isPending || undefined}
            onClick={() => save.mutate({ sent: draft.local, base: draft.base })}
            data-testid="desk-save"
            tip="Отметки уйдут в черновик стола мемов фабрики; в банке ничего не поменяется до «Применить разбор»"
          >
            {save.isPending ? (
              'Сохраняю…'
            ) : (
              <>
                Сохранить<span className="max-sm:hidden">&nbsp;отметки</span>
              </>
            )}
          </WriteButton>
          <ApplyAction
            channel={channel}
            bankLabel={bankLabel}
            why={applyWhy}
            onDone={setDone}
            onSettled={() => void after()}
          />
        </div>
      </div>
      {save.isError && problemCode(save.error) !== 'check_changed' ? (
        <Refusal error={save.error} title="Отметки не сохранились" />
      ) : null}
      <More>
        <span>банк: {data.bank}</span>
        <span>папка: {data.folder}</span>
        <span>отпечаток черновика: {data.fingerprint ?? 'черновика нет'}</span>
        <span>отпечаток индекса: {data.index_fingerprint ?? '—'}</span>
      </More>
    </Card>
  );
}
