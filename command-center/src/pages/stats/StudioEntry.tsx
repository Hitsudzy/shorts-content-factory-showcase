// Ввод прочитанного в YouTube Studio (CC-0077, API CC-0074): по каждому из последних роликов —
// ссылка «Открыть в Studio» и поле, куда вставляют строки со страницы ролика («Досмотрели» /
// «72,4 %»); при желании — доли числом и период. Дальше — как записи публикации (`WriteAction`): фабрика
// разбирает прочитанное и показывает план (что распознала, «было → станет», замечания словами),
// «да» с отсчётом пишет. Новое это чтение, повтор или замена — фабрика говорит только записью,
// поэтому в плане этого нет, а в итоге — есть. После записи перечитываются Studio и метрики.
import { useState } from 'react';

import type { StudioVideo } from '@/api/analytics';
import {
  emptyVideo,
  formWhy,
  noteText,
  planStudioRead,
  readOf,
  recordStudioRead,
  studioProblemText,
  useAfterStudioWrite,
  warningText,
  type StudioForm,
  type StudioParsedVideo,
  type StudioReadPlan,
  type StudioReadResult,
  type VideoForm,
} from '@/api/studioEntry';
import { More } from '@/components/common/More';
import { dateTimeMsk } from '@/pages/batches/format';
import { Disclosure, Done, Field, PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { pct, shortDay, videoName } from './format';

type Names = Record<string, string>;

function Warnings({ list, testId }: { list: string[] | undefined; testId: string }) {
  if (!list?.length) return null;
  return (
    <ul className="m-0 grid list-none gap-0.5 p-0 text-warning" data-testid={testId}>
      {list.map((w, i) => (
        <li key={i}>⚠ {warningText(w)}</li>
      ))}
    </ul>
  );
}

/** «было 64,1 % → станет 72,4 %»; прежнего чтения нет — «станет …, раньше не читали». */
function change(was: unknown, now: unknown, stored: boolean): string {
  const n = typeof now === 'number' ? pct(now) : 'не распознано';
  if (!stored) return `${n} · раньше не читали`;
  return `было ${typeof was === 'number' ? pct(was) : '—'} → станет ${n}`;
}

function PlanVideo({ v, name }: { v: StudioParsedVideo; name: string }) {
  const s = v.stored ?? null;
  const note = noteText(v.note);
  return (
    <li
      data-testid="studio-plan-video"
      data-video={v.video_id}
      className="grid gap-0.5 rounded-sm border p-2"
    >
      <span>
        <b className="font-semibold">{name}</b>
        {v.period_text ? (
          <span className="text-xs text-muted-foreground"> · {v.period_text}</span>
        ) : null}
      </span>
      {note ? (
        <span className="text-muted-foreground" data-testid="studio-plan-note">
          {note}
        </span>
      ) : (
        <>
          <span data-testid="studio-plan-viewed">
            Досмотрели: {change(s?.viewed_pct, v.viewed_pct, !!s)}
          </span>
          {v.swiped_pct != null || s?.swiped_pct != null ? (
            <span data-testid="studio-plan-swiped">
              Пролистали: {change(s?.swiped_pct, v.swiped_pct, !!s)}
            </span>
          ) : null}
        </>
      )}
      {s ? (
        <span className="text-xs text-muted-foreground">
          Прошлое чтение — {dateTimeMsk(s.read_at) ?? s.read_at}
        </span>
      ) : null}
      <Warnings list={v.warnings} testId="studio-plan-warnings" />
    </li>
  );
}

export function StudioPlan({ plan, names }: { plan: StudioReadPlan; names: Names }) {
  const general = plan.warnings;
  return (
    <>
      <PlanHead plan={plan} yes="можно внести" no="внести нельзя" />
      <p className="m-0 text-muted-foreground" data-testid="studio-plan-when">
        Прочитано {dateTimeMsk(plan.read_at) ?? plan.read_at} · внесёт: вы, из центра
      </p>
      {plan.videos.length ? (
        <ul className="m-0 grid list-none gap-1.5 p-0" data-testid="studio-plan-videos">
          {plan.videos.map((v) => (
            <PlanVideo
              key={v.video_id}
              v={v}
              name={names[v.video_id] ?? v.title ?? 'Ролик без названия'}
            />
          ))}
        </ul>
      ) : (
        <p className="m-0" data-testid="studio-plan-no-videos">
          Цифры роликов в этот раз не вносятся.
        </p>
      )}
      {plan.unstored.length ? (
        <div className="grid gap-1" data-testid="studio-plan-unstored">
          <b className="font-semibold">Без ролика — в статистику не лягут:</b>
          {plan.unstored.map((u, i) => (
            <span key={i}>{u.title ?? 'строки без названия ролика'}</span>
          ))}
        </div>
      ) : null}
      <Warnings list={general} testId="studio-plan-read-warnings" />
      <p className="m-0 text-xs text-muted-foreground">
        Новое это чтение, повтор или замена прежнего — фабрика скажет после записи.
      </p>
      <More className="mt-0">
        <span>
          read_at {plan.read_at} · hook {plan.hook} · ui_language {plan.ui_language ?? '—'} ·{' '}
          {plan.recorded_by}/{plan.via}
        </span>
        {plan.videos.map((v) => (
          <span key={v.video_id}>
            {v.video_id} · {v.entry_id ?? 'нет в журнале'} · {(v.raw_lines ?? []).join(' | ')}
            {v.warnings?.length ? ` · ${v.warnings.join('; ')}` : ''}
          </span>
        ))}
        {plan.warnings.length ? <span>{plan.warnings.join('; ')}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** Итог записи словами. */
export function StudioDone({
  result,
  onClose,
}: {
  result: StudioReadResult;
  onClose: () => void;
}) {
  const { added, replaced, unchanged } = result.studio;
  return (
    <Done tone="ok" testId="studio-done" title="Цифры Studio внесены" onClose={onClose}>
      <span data-testid="studio-done-videos">
        {added + replaced + unchanged
          ? `Чтения роликов: новых — ${added}, заменено — ${replaced}, без изменений — ${unchanged}.`
          : 'Цифр роликов в этот раз не было.'}
      </span>
      {!result.visit_logged ? (
        <span className="text-muted-foreground" data-testid="studio-done-visit">
          Это посещение Studio уже было записано — второй раз не записано.
        </span>
      ) : null}
      <More className="mt-0">
        <span>
          {result.read_at} · {result.hook} · {result.recorded_by}/{result.via}
        </span>
      </More>
    </Done>
  );
}

function VideoCard({
  v,
  form,
  onChange,
}: {
  v: StudioVideo;
  form: VideoForm;
  onChange: (f: VideoForm) => void;
}) {
  const set = (k: keyof VideoForm) => (x: string) => onChange({ ...form, [k]: x });
  return (
    <li
      data-testid="studio-entry-video"
      data-video={v.video_id}
      className="grid gap-2 rounded-sm border p-2.5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="min-w-0">
          <b className="font-semibold">{videoName(v)}</b>{' '}
          <span className="text-xs text-muted-foreground">
            вышел {shortDay(v.published.slice(0, 10))}
          </span>
        </span>
        <a
          href={v.studio_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-primary-text underline-offset-4 hover:underline"
        >
          Открыть в Studio
        </a>
      </div>
      <Field
        label="Строки из Studio"
        rows={3}
        value={form.lines}
        onChange={set('lines')}
        testId="studio-lines"
        placeholder={'Досмотрели\n72,4 %'}
        tip="Скопируйте со страницы ролика в Studio подпись и процент — например «Досмотрели» и «72,4 %». Можно больше строк: фабрика сама найдёт цифры"
      />
      <div className="grid grid-cols-2 gap-2">
        <Field
          label="Досмотрели, %"
          value={form.viewed}
          onChange={set('viewed')}
          testId="studio-viewed"
          placeholder="72,4"
          tip="Необязательно: если цифра в строках есть, фабрика возьмёт её оттуда. Вписанное сверяется со строками"
        />
        <Field
          label="Пролистали, %"
          value={form.swiped}
          onChange={set('swiped')}
          testId="studio-swiped"
          placeholder="27,6"
          tip="Необязательно: Studio показывает его не всегда. Из «досмотрели» фабрика его не вычисляет"
        />
      </div>
      <Field
        label="Период"
        value={form.period}
        onChange={set('period')}
        testId="studio-period"
        tip="За какой период Studio показала цифры — как написано на странице"
      />
    </li>
  );
}

export function StudioEntry({ channel, videos }: { channel: string; videos: StudioVideo[] }) {
  const fresh = (): StudioForm => ({
    videos: videos.map((v) => emptyVideo(v.video_id)),
  });
  const [form, setForm] = useState<StudioForm>(fresh);
  const [done, setDone] = useState<StudioReadResult | null>(null);
  const after = useAfterStudioWrite();
  const names: Names = Object.fromEntries(videos.map((v) => [v.video_id, videoName(v)]));
  const formOf = (id: string) => form.videos.find((f) => f.video_id === id) ?? emptyVideo(id);
  const setVideo = (f: VideoForm) =>
    setForm((s) => ({
      ...s,
      videos: s.videos.some((x) => x.video_id === f.video_id)
        ? s.videos.map((x) => (x.video_id === f.video_id ? f : x))
        : [...s.videos, f],
    }));
  const why = formWhy(form);
  return (
    <div className="mt-4 grid gap-2" data-testid="studio-entry">
      <Disclosure
        id="studio-entry"
        label="Внести прочитанное в Studio"
        tip="Вставить цифры, которые вы прочитали в YouTube Studio, — фабрика покажет, что поняла, и запишет после вашего «да»"
      >
        <p className="m-0 text-muted-foreground">
          Откройте ролик в Studio, скопируйте строки с процентами и вставьте сюда. Ролики, которые
          не заполнены, не вносятся.
        </p>
        <ul className="m-0 grid list-none gap-2 p-0" data-testid="studio-entry-videos">
          {videos.map((v) => (
            <VideoCard key={v.video_id} v={v} form={formOf(v.video_id)} onChange={setVideo} />
          ))}
        </ul>
        <WriteAction
          id="studio-entry"
          label="Проверить и внести…"
          title="Внести цифры Studio?"
          description="Фабрика разобрала прочитанное — вот что она запишет."
          body={why ? null : form}
          why={why}
          tip="Фабрика разберёт прочитанное и покажет план; запись — после вашего «да»"
          confirmLabel="Внести"
          plan={(f: StudioForm) => planStudioRead(channel, readOf(channel, f, new Date()))}
          act={(c) => recordStudioRead(channel, c)}
          view={(p) => <StudioPlan plan={p} names={names} />}
          problemText={studioProblemText}
          onSettled={after}
          onDone={(r) => {
            setDone(r);
            setForm(fresh());
          }}
        />
      </Disclosure>
      {done ? (
        <StudioDone result={done} onClose={() => setDone(null)} />
      ) : null}
    </div>
  );
}
