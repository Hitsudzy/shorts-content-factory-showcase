// Фоновая задача банка мемов (CC-0132; общий блок — его же берёт CC-0133: добавить картинку и
// GIF, контакт-лист, эмбеддинги). Задачу находит `useBankJob`: только что запущенную (`watch`
// из ответа «да») или идущую — из списка задач банка (`…/jobs`) и стола (`MemeDesk.job`), так
// перезагруженная страница видит свою задачу. Опрос — раз в `poll_s`, пока не `done`; в конце
// стол и обзор перечитываются. `JobCard` показывает любую задачу: вид и состояние словами
// фабрики (`kind_word`, `state_word`), ход «i из N», итог (свой у каждого вида — `result`),
// отказ строкой фабрики (`error.text`), код и хвост журнала — под «подробнее». Отмены нет.
// CC-0161: коммит итога (`commit`) — отказ git заметной строкой, коммит — приглушённо.
import type { ReactNode } from 'react';

import type { MemeJob } from '@/api/memeJobs';
import { nbDashes } from '@/api/humanText';
import { NO_REASON_TEXT } from '@/api/reasonRu';
import { More } from '@/components/common/More';
import { StatusBadge, type Tone } from '@/components/common/Status';
import { WarnLine } from '@/components/common/WarnLine';
import { Button } from '@/components/ui/button';
import { dateTimeMsk } from '@/pages/batches/format';
import { Elapsed } from '@/pages/publishing/Writes';

import {
  cap,
  errorWords,
  hasCyrillic,
  jobCommitView,
  jobWord,
  STEP_KINDS,
  stepText,
  stepWord,
} from './jobs';

const STATE_TONE: Record<MemeJob['state'], Tone> = {
  running: 'live',
  done: 'ok',
  failed: 'danger',
  interrupted: 'warn',
};

const BOX: Record<MemeJob['state'], string> = {
  running: 'var(--primary)',
  done: 'var(--success)',
  failed: 'var(--danger)',
  interrupted: 'var(--warning)',
};

function Progress({ job, itemText }: { job: MemeJob; itemText?: (t: string) => string }) {
  const p = job.progress;
  const step = stepWord(p) ?? cap(jobWord(job));
  const counted = p && typeof p.i === 'number' && typeof p.of === 'number' && p.of > 0;
  const text = p?.text ? (itemText ? itemText(p.text) : stepText(job, p)) : null;
  const share = counted ? Math.min(100, Math.round((p.i! / p.of!) * 100)) : null;
  return (
    <div className="grid gap-1.5" data-testid="job-progress">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <b className="font-semibold">{step}</b>
        {counted ? (
          <span data-testid="job-count" className="tabular-nums">
            {STEP_KINDS.has(job.kind ?? '') ? 'шаг ' : ''}
            {p.i} из {p.of}
          </span>
        ) : null}
        {text ? (
          <span
            className="min-w-0 text-muted-foreground [overflow-wrap:anywhere]"
            data-testid="job-step-text"
          >
            {text}
          </span>
        ) : null}
      </div>
      <div
        role="progressbar"
        aria-label="Ход задачи"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={share ?? undefined}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={share === null ? 'h-full w-1/3 animate-pulse bg-primary' : 'h-full bg-primary'}
          style={share === null ? undefined : { width: `${share}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Блок одной фоновой задачи. `result` — итог законченной задачи (у каждого вида свой); без него
 * — только «готово». `itemText` — как назвать элемент хода (`progress.text`): у мемов — имя мема.
 */
export function JobCard({
  job,
  result,
  itemText,
  say = (t: string) => t,
  onClose,
  testId = 'meme-job',
}: {
  job: MemeJob;
  result?: ReactNode;
  itemText?: (t: string) => string;
  /** Строка фабрики для человека (у мемов — id именами); как есть — под «подробнее». */
  say?: (text: string) => string;
  onClose?: () => void;
  testId?: string;
}) {
  const color = BOX[job.state];
  const started = job.started_at ? Date.parse(job.started_at) : NaN;
  const err = job.error;
  const commit = jobCommitView(job);
  return (
    <div
      role="status"
      data-testid={testId}
      data-state={job.state}
      data-kind={job.kind ?? undefined}
      style={{
        borderColor: `color-mix(in srgb, ${color} 40%, var(--border))`,
        background: `color-mix(in srgb, ${color} 6%, var(--card))`,
      }}
      className="grid gap-2 rounded-sm border p-3 text-[13px] text-foreground"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {job.state === 'running' ? (
            <span className="size-2 animate-pulse rounded-full bg-primary" aria-hidden />
          ) : null}
          <b className="font-semibold" data-testid="job-title">
            {cap(jobWord(job))}
          </b>
          <StatusBadge tone={STATE_TONE[job.state]}>
            <span data-testid="job-state">{job.state_word}</span>
          </StatusBadge>
          {job.state === 'running' && !Number.isNaN(started) ? (
            <span className="text-xs text-muted-foreground">
              уже <Elapsed since={started} />
            </span>
          ) : null}
        </div>
        {job.done && onClose ? (
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="job-close">
            Скрыть
          </Button>
        ) : null}
      </div>

      {job.state === 'running' ? (
        <>
          <Progress job={job} itemText={itemText} />
          <p className="m-0 text-xs text-muted-foreground" data-testid="job-wait">
            Задача идёт в фоне&nbsp;— страницу можно закрыть. Отмены нет: пока она не кончится,
            сохранить отметки и применить разбор нельзя.
          </p>
        </>
      ) : null}

      {job.state === 'done' ? (
        <div className="grid gap-1.5" data-testid="job-result">
          {result ?? <span>Готово.</span>}
          <span className="text-xs text-muted-foreground">
            Банк перечитан.
            {commit?.kind === 'committed' ? (
              <span data-testid="job-commit"> · {commit.text}</span>
            ) : null}
          </span>
        </div>
      ) : null}

      {commit?.kind === 'refused' ? (
        <WarnLine testId="job-commit-refused" title={commit.title} action={commit.action} />
      ) : null}

      {job.state === 'failed' || job.state === 'interrupted' ? (
        <div className="grid gap-1" data-testid="job-error">
          <p
            className={job.state === 'failed' ? 'm-0 text-danger [overflow-wrap:anywhere]' : 'm-0'}
          >
            {err
              ? nbDashes(say(errorWords(err.text)))
              : job.state === 'interrupted'
                ? 'Задача оборвалась, не дописав итог.'
                : NO_REASON_TEXT}
          </p>
          <span className="text-xs text-muted-foreground">
            Банк перечитан&nbsp;— посмотрите, что успело измениться, и запустите заново, если нужно.
          </span>
        </div>
      ) : null}

      <More className="mt-0">
        <span>задача: {job.job_id}</span>
        <span>
          вид: {job.kind ?? '—'} · состояние: {job.state} · банк: {job.bank ?? '—'}
        </span>
        {job.started_at ? (
          <span>начата: {dateTimeMsk(job.started_at) ?? job.started_at}</span>
        ) : null}
        {job.ended_at ? <span>кончилась: {dateTimeMsk(job.ended_at) ?? job.ended_at}</span> : null}
        {job.by || job.via ? (
          <span>
            кто: {job.by ?? '—'} · через: {job.via ?? '—'}
          </span>
        ) : null}
        {job.log ? <span>журнал: {job.log}</span> : null}
        {job.params ? <span>параметры: {JSON.stringify(job.params)}</span> : null}
        {job.progress ? <span>шаг: {job.progress.step}</span> : null}
        {commit?.kind === 'committed' && commit.sha ? <span>коммит: {commit.sha}</span> : null}
        {commit?.kind === 'refused' ? (
          <span data-testid="job-commit-detail">
            git отказал в коммите{commit.detail ? `: ${commit.detail}` : ''}
          </span>
        ) : null}
        {err ? <span>код: {err.code}</span> : null}
        {err && err.text && (!hasCyrillic(err.text) || say(err.text) !== err.text) ? (
          <span>{err.text}</span>
        ) : null}
        {err?.en ? <span>{err.en}</span> : null}
        {err?.log_tail ? (
          <pre className="m-0 whitespace-pre-wrap" data-testid="job-log-tail">
            {err.log_tail}
          </pre>
        ) : null}
      </More>
    </div>
  );
}
