// «Вырезать фон» и «Обрезать пустые поля» (CC-0132 → CC-0075 API): два шага, как «Применить
// разбор» — план фабрики (что вырежет или обрежет, что оставит и почему; `under` — обрезка
// растянула бы мем сильнее допустимого, решать пользователю; недоступность Vision — словами
// `cutout_available()`) и «да» с отсчётом. «Да» запускает задачу в фоне: её ход и итог — блок
// задачи на столе (./Job.tsx), после конца стол перечитывается. Пока задача идёт, обе кнопки
// погашены с причиной. Итоги задач этих видов — `CutoutDone` / `TrimDone` (`JobResult`).
import { useState, type ReactNode } from 'react';

import type { MemeDesk } from '@/api/memes';
import {
  cutoutResult,
  memeJobProblemText,
  planCutout,
  planTrim,
  startCutout,
  startTrim,
  trimResult,
  type CutoutBody,
  type MemeCutoutPlan,
  type MemeJob,
  type MemeJobStarted,
  type MemeTrimPlan,
  type MemeTrimRow,
  type TrimBody,
} from '@/api/memeJobs';
import { planEmbed, startEmbed, type MemeEmbedPlan } from '@/api/memeAdds';
import { nbDashes } from '@/api/humanText';
import { NO_REASON_TEXT } from '@/api/reasonRu';
import { More } from '@/components/common/More';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { Check, PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { AddDone, EmbedDone, SheetDone, type GifSeed } from './Add';
import { bandWords, memeName, memesWord, quoted } from './format';
import { afterDash, humanNote } from './jobs';

const hasCyrillic = (s: string) => /[а-яё]/i.test(s);
/** Причина словами фабрики (русская — как есть), иначе — «причина без описания». */
const said = (r: { reason?: string | null }) =>
  r.reason && hasCyrillic(r.reason) ? afterDash(r.reason) : NO_REASON_TEXT;

/** «1,28» — во сколько раз растянется мем. */
const ratio = (n: number) => String(Math.round(n * 100) / 100).replace('.', ',');
const NB = '\u00a0';
const size = (s: number[]) => (s.length >= 2 ? `${s[0]}×${s[1]}` : '—');

function Group({
  testId,
  title,
  ids = [],
  tone,
  children,
}: {
  testId: string;
  title: string;
  ids?: string[];
  tone?: 'warn' | 'danger';
  children?: ReactNode;
}) {
  return (
    <div className="grid gap-0.5" data-testid={testId}>
      <b
        className={
          tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warning' : 'font-semibold'
        }
      >
        {title}
      </b>
      {ids.length ? (
        <span className="text-muted-foreground [overflow-wrap:anywhere]">
          {ids.slice(0, 12).map(quoted).join(', ')}
          {ids.length > 12 ? ` и ещё ${ids.length - 12}` : ''}
        </span>
      ) : null}
      {children}
    </div>
  );
}

function Reasons({ rows }: { rows: { id: string; reason?: string | null }[] }) {
  return (
    <ul className="m-0 grid list-disc gap-0.5 pl-5">
      {rows.map((r) => (
        <li key={r.id} className="[overflow-wrap:anywhere]">
          {quoted(r.id)}
          {`${NB}— `}
          {said(r)}
        </li>
      ))}
    </ul>
  );
}

/** Заметки плана словами фабрики: пути — словами (сам путь — под «подробнее»), id мемов — именами. */
function Notes({ notes, ids }: { notes: string[]; ids: string[] }) {
  if (!notes.length) return null;
  return (
    <ul
      className="m-0 grid list-disc gap-0.5 pl-5 text-xs text-muted-foreground"
      data-testid="plan-notes"
    >
      {notes.map((n) => (
        <li key={n}>{nbDashes(humanNote(n, ids))}</li>
      ))}
    </ul>
  );
}

/** Строки «код и английское» отказов — под «подробнее». */
function ReasonsMore({ rows }: { rows: { id: string; reason?: string | null; en?: unknown }[] }) {
  return rows.map((r) => (
    <span key={r.id}>
      {r.id}: {r.reason ?? '—'}
      {typeof r.en === 'string' && r.en ? ` (${r.en})` : ''}
    </span>
  ));
}

export function CutoutPlanView({ plan, ids = [] }: { plan: MemeCutoutPlan; ids?: string[] }) {
  const why = plan.why ?? '';
  return (
    <>
      <PlanHead plan={plan} yes="можно вырезать" no="вырезать нельзя" />
      {!plan.available && !why.includes(plan.available_reason) ? (
        <p role="alert" className="m-0 text-danger" data-testid="cutout-unavailable">
          Вырезка на этой машине недоступна: {plan.available_reason}
        </p>
      ) : plan.available ? (
        <p className="m-0 text-xs text-muted-foreground" data-testid="cutout-available">
          Вырезает: {plan.available_reason}
        </p>
      ) : null}
      {plan.made.length ? (
        <Group
          testId="cutout-plan-made"
          title={`Вырежет фон: ${memesWord(plan.made.length)}`}
          ids={plan.made.map((m) => m.id)}
        />
      ) : null}
      {plan.unchanged.length ? (
        <Group
          testId="cutout-plan-unchanged"
          title={`Вырезка уже свежая${NB}— не трогает: ${memesWord(plan.unchanged.length)}`}
          ids={plan.unchanged}
        />
      ) : null}
      {plan.missing.length ? (
        <Group
          testId="cutout-plan-missing"
          title={`Нет файла картинки${NB}— пропустит: ${memesWord(plan.missing.length)}`}
          ids={plan.missing}
          tone="warn"
        />
      ) : null}
      {plan.outside_bank.length ? (
        <Group
          testId="cutout-plan-outside"
          title={`Не возьмёт: ${memesWord(plan.outside_bank.length)}`}
          tone="warn"
        >
          <Reasons rows={plan.outside_bank} />
        </Group>
      ) : null}
      {plan.refused.length ? (
        <Group
          testId="cutout-plan-refused"
          title={`Распознавание откажет: ${memesWord(plan.refused.length)}`}
          tone="warn"
        >
          <Reasons rows={plan.refused} />
        </Group>
      ) : null}
      <Notes notes={plan.notes} ids={ids} />
      <More className="mt-0">
        <span>
          {plan.action} · {plan.kind} · банк {plan.bank}
        </span>
        <span>параметры: {JSON.stringify(plan.params)}</span>
        {plan.made.map((m) => (
          <span key={m.id}>
            {m.id} → {m.file}
          </span>
        ))}
        <ReasonsMore rows={[...plan.outside_bank, ...plan.refused]} />
        {plan.job ? <span>идёт задача: {plan.job.job_id}</span> : null}
        {plan.machine_job ? (
          <span>
            задача на машине: {plan.machine_job.job_id} · банк {plan.machine_job.bank}
          </span>
        ) : null}
        {plan.notes
          .filter((n) => humanNote(n, ids) !== n)
          .map((n) => (
            <span key={n}>{n}</span>
          ))}
        <span>отпечаток плана: {plan.fingerprint}</span>
      </More>
    </>
  );
}

function TrimRowText({ r, under = false }: { r: MemeTrimRow; under?: boolean }) {
  return (
    <li className="[overflow-wrap:anywhere]">
      {quoted(r.id)}
      {`${NB}— ${bandWords(r)}; ${size(r.size)} → ${size(r.trimmed_size)}, `}
      {under
        ? `растянулся бы в ${ratio(r.stretch)} раза${NB}— допустимо до ${ratio(r.ceiling)}`
        : `растянется в ${ratio(r.stretch)} раза (допустимо до ${ratio(r.ceiling)})`}
      {!under && r.recut ? ' · вырезку придётся сделать заново' : ''}
    </li>
  );
}

export function TrimPlanView({ plan, ids = [] }: { plan: MemeTrimPlan; ids?: string[] }) {
  return (
    <>
      <PlanHead plan={plan} yes="можно обрезать" no="обрезать нельзя" />
      {plan.trim.length ? (
        <Group testId="trim-plan-trim" title={`Обрежет поля: ${memesWord(plan.trim.length)}`}>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {plan.trim.map((r) => (
              <TrimRowText key={r.id} r={r} />
            ))}
          </ul>
        </Group>
      ) : null}
      {plan.under.length ? (
        <Group
          testId="trim-plan-under"
          title={`Не обрежет, решать вам: ${memesWord(plan.under.length)} (${plan.under.length === 1 ? 'растянулся' : 'растянулись'} бы сильнее допустимого)`}
          tone="warn"
        >
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {plan.under.map((r) => (
              <TrimRowText key={r.id} r={r} under />
            ))}
          </ul>
        </Group>
      ) : null}
      {plan.left.length ? (
        <Group testId="trim-plan-left" title={`Не трогает: ${memesWord(plan.left.length)}`}>
          <Reasons rows={plan.left} />
        </Group>
      ) : null}
      <Notes notes={plan.notes} ids={ids} />
      <More className="mt-0">
        <span>
          {plan.action} · {plan.kind} · банк {plan.bank} · эмбеддинги заново: {String(plan.embed)}
        </span>
        <span>параметры: {JSON.stringify(plan.params)}</span>
        {[...plan.trim, ...plan.under].map((r) => (
          <span key={r.id}>
            {r.id}: {r.file} · {r.phrase} · {r.phrase_ru ?? '—'} · crop {JSON.stringify(r.crop)}
          </span>
        ))}
        <ReasonsMore rows={plan.left} />
        {plan.job ? <span>идёт задача: {plan.job.job_id}</span> : null}
        {plan.machine_job ? (
          <span>
            задача на машине: {plan.machine_job.job_id} · банк {plan.machine_job.bank}
          </span>
        ) : null}
        {plan.notes
          .filter((n) => humanNote(n, ids) !== n)
          .map((n) => (
            <span key={n}>{n}</span>
          ))}
        <span>отпечаток плана: {plan.fingerprint}</span>
      </More>
    </>
  );
}

// ---- итоги задач

export function CutoutDone({ job }: { job: MemeJob }) {
  const r = cutoutResult(job.result);
  return (
    <div className="grid gap-1.5" data-testid="cutout-done">
      <Group testId="cutout-done-made" title={`Вырезан фон: ${memesWord(r.made.length)}`}>
        {r.made.length ? (
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {r.made.map((m) => (
              <li key={m.id} className="grid w-20 gap-0.5 text-xs">
                {m.urls?.cut ? (
                  <img
                    src={m.urls.cut}
                    alt={`Вырезка: ${memeName(m.id)}`}
                    loading="lazy"
                    className="aspect-square w-20 rounded-sm border bg-[repeating-conic-gradient(var(--muted)_0_25%,transparent_0_50%)] bg-[length:12px_12px] object-contain"
                  />
                ) : null}
                <span className="line-clamp-2 [overflow-wrap:anywhere]" title={memeName(m.id)}>
                  {memeName(m.id)}
                </span>
                {typeof m.coverage === 'number' ? (
                  <span className="text-muted-foreground">
                    {`предмет${NB}— ${Math.round(m.coverage * 100)}%${NB}кадра`}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </Group>
      {r.refused.length ? (
        <Group
          testId="cutout-done-refused"
          title={`Распознавание отказало: ${memesWord(r.refused.length)}`}
          tone="warn"
        >
          <Reasons rows={r.refused} />
        </Group>
      ) : null}
      {r.unchanged.length ? (
        <Group
          testId="cutout-done-unchanged"
          title={`Не тронуты${NB}— вырезка свежая: ${memesWord(r.unchanged.length)}`}
          ids={r.unchanged}
        />
      ) : null}
      {r.missing.length ? (
        <Group
          testId="cutout-done-missing"
          title={`Пропущены${NB}— нет файла картинки: ${memesWord(r.missing.length)}`}
          ids={r.missing}
          tone="warn"
        />
      ) : null}
      {r.outside_bank.length ? (
        <Group
          testId="cutout-done-outside"
          title={`Не взяты: ${memesWord(r.outside_bank.length)}`}
          tone="warn"
        >
          <Reasons rows={r.outside_bank} />
        </Group>
      ) : null}
      {r.written === false ? (
        <span className="text-muted-foreground">В банке ничего не записано.</span>
      ) : null}
      <More className="mt-0">
        {r.made.map((m) => (
          <span key={m.id}>
            {m.id} → {m.file ?? '—'} · bbox {JSON.stringify(m.bbox_px ?? null)}
          </span>
        ))}
        <ReasonsMore rows={[...r.refused, ...r.outside_bank]} />
      </More>
    </div>
  );
}

export function TrimDone({ job }: { job: MemeJob }) {
  const r = trimResult(job.result);
  const e = r.embedding;
  const embedText = e?.error
    ? hasCyrillic(e.error)
      ? e.error
      : `Признаки для поиска похожих мемов не пересчитались: ${NO_REASON_TEXT}`
    : e?.done
      ? 'Признаки для поиска похожих мемов пересчитаны.'
      : null;
  return (
    <div className="grid gap-1.5" data-testid="trim-done">
      <Group testId="trim-done-trim" title={`Обрезаны поля: ${memesWord(r.changed.length)}`}>
        {r.trim.length ? (
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {r.trim.map((x) => (
              <TrimRowText key={x.id} r={x} />
            ))}
          </ul>
        ) : null}
      </Group>
      {r.under.length ? (
        <Group
          testId="trim-done-under"
          title={`Оставлены целыми: ${memesWord(r.under.length)} (растянулись бы сильнее допустимого)`}
          ids={r.under.map((x) => x.id)}
          tone="warn"
        />
      ) : null}
      {r.left.length ? (
        <Group
          testId="trim-done-left"
          title={`Не тронуты: ${memesWord(r.left.length)}`}
          ids={r.left.map((x) => x.id)}
        />
      ) : null}
      {r.originals ? (
        <span className="text-muted-foreground">Оригиналы картинок сохранены в папке банка.</span>
      ) : null}
      {embedText ? (
        <span
          data-testid="trim-done-embedding"
          className={e?.error ? (e.fatal ? 'text-danger' : 'text-warning') : undefined}
        >
          {embedText}
        </span>
      ) : null}
      <More className="mt-0">
        {r.originals ? <span>оригиналы: {r.originals}</span> : null}
        {e?.line ? <span>{e.line}</span> : null}
        {e?.en ? <span>{e.en}</span> : null}
        <ReasonsMore rows={r.left} />
      </More>
    </div>
  );
}

/** Итог законченной задачи по её виду; незнакомый вид — без итога (просто «готово»). */
export function JobResult({
  job,
  onOpen,
  onGif,
}: {
  job: MemeJob;
  /** Открыть новую запись на столе (после «добавить картинку» и GIF). */
  onOpen?: (id: string) => void;
  /** Отрезок с листа кадров → форма «GIF из видео». */
  onGif?: (s: Omit<GifSeed, 'n'>) => void;
}) {
  if (job.kind === 'cutout') return <CutoutDone job={job} />;
  if (job.kind === 'trim_blank') return <TrimDone job={job} />;
  if (job.kind === 'add_image' || job.kind === 'add_gif')
    return <AddDone job={job} onOpen={onOpen} />;
  if (job.kind === 'sheet') return <SheetDone job={job} onGif={onGif} />;
  if (job.kind === 'embed') return <EmbedDone job={job} />;
  return <span>Готово.</span>;
}

/** План пересчёта признаков — слова центра: что пересчитается и худшее время. */
export function EmbedPlanView({ plan }: { plan: MemeEmbedPlan }) {
  return (
    <>
      <PlanHead plan={plan} yes="можно пересчитать" no="пересчитать нельзя" />
      <span data-testid="embed-plan-time">Предел времени: {plan.max_seconds_word}</span>
      <Notes notes={plan.notes} ids={[]} />
      <More className="mt-0">
        <span>
          {plan.action} · {plan.kind} · банк {plan.bank} · худшее время {plan.max_seconds} с
        </span>
        {plan.job ? <span>идёт задача: {plan.job.job_id}</span> : null}
        {plan.machine_job ? (
          <span>
            задача на машине: {plan.machine_job.job_id} · банк {plan.machine_job.bank}
          </span>
        ) : null}
        <span>отпечаток плана: {plan.fingerprint}</span>
      </More>
    </>
  );
}

// ---- кнопки

/** Мемы банка с «можно вырезать» (применённой разбором): сколько с вырезкой и без. */
function cutCounts(desk: MemeDesk) {
  const cut = desk.entries.filter((e) => e.cutout && !e.gif);
  return {
    all: cut.length,
    ready: cut.filter((e) => e.cut_file).length,
  };
}

const TOOLS_PANEL = 'meme-tools-panel';

/**
 * Кнопка, что раскрывает обработку банка, — в строке поиска стола: раскрытая панель встаёт под
 * этой строкой, а свёрнутая ничего не сдвигает.
 */
export function ToolsToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <Tip content="Обработка картинок банка фабрикой: сначала план, задача — после вашего «да»" wide>
      <Button
        size="sm"
        variant="outline"
        aria-expanded={open}
        aria-controls={TOOLS_PANEL}
        data-testid="meme-tools-toggle"
        className="max-sm:flex-1"
        aria-label="Обработка банка: вырезать фон, обрезать поля, пересчитать признаки"
        onClick={onToggle}
      >
        Обработка банка
        <span aria-hidden>{open ? '▴' : '▾'}</span>
      </Button>
    </Tip>
  );
}

/** Панель обработки банка: вырезка фона и обрезка полей (раскрывает `ToolsToggle`). */
export function BankTools({
  channel,
  bankLabel,
  desk,
  busy,
  onStarted,
  onSettled,
}: {
  channel: string;
  bankLabel: string;
  desk: MemeDesk;
  /** Почему нельзя: идёт задача банка (отмены нет). */
  busy: string | null;
  onStarted: (s: MemeJobStarted) => void;
  onSettled: () => void;
}) {
  const [force, setForce] = useState(false);
  const c = cutCounts(desk);
  const bands = desk.status.blank_bands.length;
  const ids = desk.entries.map((e) => e.id);
  return (
    <div
      id={TOOLS_PANEL}
      data-testid="meme-tools-form"
      className="grid gap-4 rounded-sm border p-3 text-[13px] text-foreground md:grid-cols-2"
    >
      <div className="grid content-start gap-2" data-testid="meme-cutout-panel">
        <b className="font-semibold">Вырезать фон</b>
        <span className="text-muted-foreground">
          {c.all
            ? `Можно вырезать: ${memesWord(c.all)}${NB}— вырезка есть у ${c.ready}, нет у ${c.all - c.ready}.`
            : 'В банке нет мемов с «можно вырезать»: отметьте их и примените разбор.'}{' '}
          Фабрика вырежет фон по контуру тем, у кого вырезки нет или она устарела.
        </span>
        <Check
          label="Вырезать заново и свежие вырезки"
          checked={force}
          onChange={setForce}
          testId="meme-cutout-force"
          tip="Без этой галочки фабрика не трогает мемы, у которых вырезка свежая"
        />
        <div>
          <WriteAction<CutoutBody, MemeCutoutPlan, MemeJobStarted>
            id="meme-cutout"
            label="Вырезать фон…"
            title={`Вырезать фон в банке ${bankLabel}?`}
            description={`Фабрика проверила, что вырежет. Вырезка пойдёт в фоне${NB}— её ход виден на столе.`}
            body={{ ids: null, force }}
            why={busy ?? (c.all ? null : 'В банке нет мемов с «можно вырезать»')}
            tip="Фабрика покажет план; вырезка начнётся после вашего «да»"
            confirmLabel="Вырезать"
            pendingLabel="Запускаю…"
            triggerVariant="outline"
            plan={(b) => planCutout(channel, b)}
            act={(confirm) => startCutout(channel, confirm)}
            view={(p) => <CutoutPlanView plan={p} ids={ids} />}
            problemText={memeJobProblemText}
            onSettled={onSettled}
            onDone={onStarted}
          />
        </div>
      </div>
      <div className="grid content-start gap-2" data-testid="meme-trim-panel">
        <b className="font-semibold">Обрезать пустые поля</b>
        <span className="text-muted-foreground">
          {bands
            ? `Пустая полоса подписи у ${memesWord(bands)}.`
            : 'Пустых полос подписи фабрика не заметила.'}{' '}
          Фабрика обрежет файлы картинок, оригиналы сохранит и заново посчитает признаки для поиска
          похожих мемов.
        </span>
        <div>
          <WriteAction<TrimBody, MemeTrimPlan, MemeJobStarted>
            id="meme-trim"
            label="Обрезать пустые поля…"
            title={`Обрезать пустые поля в банке ${bankLabel}?`}
            description={`Фабрика проверила, что обрежет. Обрезка пойдёт в фоне${NB}— её ход виден на столе.`}
            body={{ id: null }}
            why={busy}
            tip="Фабрика покажет план; обрезка начнётся после вашего «да»"
            confirmLabel="Обрезать"
            pendingLabel="Запускаю…"
            triggerVariant="outline"
            plan={(b) => planTrim(channel, b)}
            act={(confirm) => startTrim(channel, confirm)}
            view={(p) => <TrimPlanView plan={p} ids={ids} />}
            problemText={memeJobProblemText}
            onSettled={onSettled}
            onDone={onStarted}
          />
        </div>
      </div>
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-3 md:col-span-2"
        data-testid="meme-embed-panel"
      >
        <span className="min-w-0 flex-1 basis-60 text-muted-foreground">
          <b className="font-semibold text-foreground">Признаки для поиска похожих мемов</b>
          {`${NB}— фабрика пересчитывает их сама после добавления и обрезки; заново для всего банка${NB}— если поиск похожих ошибается.`}
        </span>
        <WriteAction<Record<string, never>, MemeEmbedPlan, MemeJobStarted>
          id="meme-embed"
          label="Пересчитать признаки…"
          title={`Пересчитать признаки для поиска похожих мемов в банке ${bankLabel}?`}
          description={`Файлы и отметки мемов не меняются. Пересчёт пойдёт в фоне${NB}— его ход виден на столе.`}
          body={{}}
          why={busy}
          tip="Центр покажет план; пересчёт начнётся после вашего «да»"
          confirmLabel="Пересчитать"
          pendingLabel="Запускаю…"
          triggerVariant="ghost"
          plan={() => planEmbed(channel)}
          act={(confirm) => startEmbed(channel, confirm)}
          view={(p) => <EmbedPlanView plan={p} />}
          problemText={memeJobProblemText}
          onSettled={onSettled}
          onDone={onStarted}
        />
      </div>
    </div>
  );
}
