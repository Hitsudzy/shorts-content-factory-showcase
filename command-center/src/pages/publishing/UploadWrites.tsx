// Загрузка выбранного в ленте ролика (CC-0069, API CC-0066). Два пути:
//  - на YouTube программой — только при включённом переключателе API-загрузки. План — сухой
//    прогон `upload.py`: сводка (`summary`), условия YouTube (`tos_notice`) и вопрос
//    (`question`); пользователь сам набирает «да» в поле ответа — поле всегда пустое, кнопки
//    «вставить» нет, центр «да» не подставляет. Ответ не «да» — `answer_required`, токен цел.
//    Загрузка идёт долго: окно показывает, сколько уже ждём, и второй раз не шлёт. Отказы —
//    `reauthorize` (переразрешить токен в терминале), `upload_failed`, `uploaded_unrecorded`
//    (ролик на YouTube, а записи нет — строки «внести руками» с «скопировать»);
//  - через Studio руками — «загружено через Studio»: что Studio показывает после сохранения
//    (поля или JSON `studio_fields.py read`) фабрика сверяет с карточкой (`mismatches`) и пишет
//    строку в журнал (`would-add`; уже есть — `exists`).
// Пути, id записи и строки фабрики — под «подробнее».
import { useId, useState } from 'react';

import { BatchError, problemCode } from '@/api/batchProblem';
import { useApiUpload, type PublishNote } from '@/api/publish';
import {
  planStudioRecord,
  planUpload,
  studioReadOf,
  studioRecord,
  upload,
  videoIdOf,
  type Mismatch,
  type StudioRecordPlan,
  type StudioRecordResult,
  type UploadPlan,
  type UploadResult,
} from '@/api/publishWrites';
import { Card, CardHead } from '@/components/common/Card';
import { StudioDue } from '@/components/studio/StudioRead';
import { CopyButton } from '@/components/common/CopyButton';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';
import { inputBase } from '@/pages/channels/styles';

import { RESERVE_DAY, RESERVE_WHY, withoutBatchTail } from './stashWords';
import { Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';
import { SkeletonText } from '@/components/common/Skeletons';

// ---------------------------------------------------------------- загрузка на YouTube
function Answer({
  question,
  value,
  onChange,
}: {
  question: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div className="grid gap-1" data-testid="upload-answer-field">
      <label htmlFor={id} className="font-semibold">
        {question}
      </label>
      <input
        id={id}
        data-testid="upload-answer"
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onPaste={(e) => e.preventDefault()}
        className={inputBase}
      />
      <span className="text-xs text-muted-foreground">
        Ответ набираете вы — прочитав сводку и условия YouTube.
      </span>
    </div>
  );
}

function UploadPlanView({
  plan,
  answer,
  setAnswer,
}: {
  plan: UploadPlan;
  answer: string;
  setAnswer: (v: string) => void;
}) {
  return (
    <>
      <PlanHead plan={plan} yes="можно загрузить" no="загрузить нельзя" />
      {plan.summary ? (
        <div className="grid gap-1">
          <span className="text-muted-foreground">Что уйдёт на YouTube:</span>
          <pre
            data-testid="upload-summary"
            className="m-0 rounded-sm border bg-muted/40 p-2.5 font-sans text-[13px] whitespace-pre-wrap [overflow-wrap:anywhere]"
          >
            {plan.summary}
          </pre>
        </div>
      ) : null}
      {plan.publish_at ? (
        <p className="m-0" data-testid="upload-when">
          До {dateTimeMsk(plan.publish_at) ?? plan.publish_at} ролик будет приватным, потом выйдет
          сам.
        </p>
      ) : null}
      {plan.tos_notice ? (
        <div
          role="note"
          data-testid="upload-tos"
          className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-3"
        >
          <b className="font-semibold">Условия YouTube</b>
          <span className="[overflow-wrap:anywhere]">{plan.tos_notice}</span>
        </div>
      ) : null}
      {plan.ok && plan.question ? (
        <Answer question={plan.question} value={answer} onChange={setAnswer} />
      ) : null}
      <More className="mt-0">
        <span>заметка: {withoutBatchTail(plan.note ?? '')}</span>
        <span>файл: {withoutBatchTail(plan.video ?? '')}</span>
        {plan.entry_id ? <span>приёмка: {plan.entry_id}</span> : null}
        {plan.channel_id ? <span>канал YouTube: {plan.channel_id}</span> : null}
        {plan.token ? <span>{plan.token}</span> : null}
        <span>{plan.switch.line}</span>
        {plan.dry_run.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** Отказ загрузки — что делать дальше: переразрешить токен или внести запись руками. */
function UploadAfter({ error }: { error: unknown }) {
  const code: string | null = problemCode(error);
  const details = error instanceof BatchError ? (error.problem?.details ?? []) : [];
  if (code === 'reauthorize')
    return (
      <p className="m-0 text-[13px]" data-testid="upload-reauthorize">
        Ничего не загружено. Переразрешите доступ к YouTube в терминале фабрики (команда — под
        «подробнее») и проверьте загрузку заново.
      </p>
    );
  if (code === 'upload_failed')
    return (
      <p className="m-0 text-[13px]" data-testid="upload-failed-note">
        YouTube ролик не принял. Посмотрите причину под «подробнее» — повторять можно после новой
        проверки.
      </p>
    );
  if (code !== 'uploaded_unrecorded') return null;
  return (
    <div
      className="grid gap-1.5 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] p-3 text-[13px]"
      data-testid="upload-manual"
    >
      <b className="font-semibold">Ролик уже на YouTube — не загружайте его ещё раз.</b>
      <span>Внесите руками то, что фабрика не записала:</span>
      <ol className="m-0 grid list-decimal gap-1.5 pl-5">
        {details.map((d, i) => (
          <li key={i} data-testid="upload-manual-line">
            <div className="flex items-start justify-between gap-2">
              <code className="min-w-0 font-mono text-xs [overflow-wrap:anywhere] select-all">
                {d}
              </code>
              <CopyButton
                value={d}
                what={`строка ${i + 1}`}
                tip="Скопировать строку, чтобы внести её руками"
                data-testid="upload-manual-copy"
              />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function UploadDone({ r, onClose }: { r: UploadResult; onClose: () => void }) {
  const vid = (r.row as { video_id?: string } | null)?.video_id;
  return (
    <Done tone="ok" testId="upload-done" title="Загружено на YouTube" onClose={onClose}>
      <span>Ролик ждёт своего слота приватным; запись о загрузке легла в журнал.</span>
      <More className="mt-0">
        {vid ? <span>ролик: {vid}</span> : null}
        {r.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </More>
    </Done>
  );
}

// ---------------------------------------------------------------- запись Studio
const FIELD_NAMES: Record<string, string> = {
  title: 'Название',
  description: 'Описание',
  tags: 'Теги',
  visibility: 'Видимость',
  publish_at: 'Время публикации',
  made_for_kids: 'Для детей',
  altered_content: 'Изменённый контент',
  paid_promotion: 'Платная реклама',
};

const shown = (v: unknown) =>
  v == null ? '—' : typeof v === 'string' ? v || '(пусто)' : JSON.stringify(v);

function RecordPlanView({ plan }: { plan: StudioRecordPlan }) {
  const mism = plan.mismatches as Mismatch[];
  return (
    <>
      <PlanHead plan={plan} yes="можно записать" no="записать нельзя" />
      {plan.status ? (
        <p className="m-0 flex flex-wrap items-center gap-2" data-testid="record-status">
          {plan.status === 'would-add' ? (
            <StatusBadge tone="ok" tip="Фабрика добавит строку о загрузке в журнал">
              добавит запись
            </StatusBadge>
          ) : (
            <StatusBadge tone="idle" tip="Такая строка в журнале загрузок уже есть">
              уже в журнале
            </StatusBadge>
          )}
          {plan.status === 'would-add'
            ? 'Studio показывает то же, что в карточке.'
            : 'Этот ролик уже записан — писать нечего.'}
        </p>
      ) : null}
      {mism.length ? (
        <div className="grid gap-1" data-testid="record-mismatches">
          <span className="font-medium">Studio показывает не то, что в карточке:</span>
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {mism.map((m, i) => (
              <li
                key={i}
                data-testid="record-mismatch"
                data-field={m.field}
                className="grid gap-0.5 rounded-sm border p-2"
              >
                <b className="font-semibold">{FIELD_NAMES[m.field] ?? m.field}</b>
                <span className="[overflow-wrap:anywhere]">
                  <span className="text-muted-foreground">в карточке: </span>
                  {shown(m.expected)}
                </span>
                <span className="[overflow-wrap:anywhere]">
                  <span className="text-muted-foreground">в Studio: </span>
                  {shown(m.read)}
                </span>
              </li>
            ))}
          </ul>
          <span className="text-muted-foreground">
            Поправьте поле в Studio и проверьте заново — или скажите о расхождении до слота.
          </span>
        </div>
      ) : null}
      <More className="mt-0">
        <span>заметка: {withoutBatchTail(plan.note ?? '')}</span>
        <span>ролик: {plan.video_id}</span>
        {plan.replaces ? <span>заменяет: {plan.replaces}</span> : null}
        {plan.row ? <span>{JSON.stringify(plan.row)}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function RecordDone({ r, onClose }: { r: StudioRecordResult; onClose: () => void }) {
  const s = r.streak;
  return (
    <Done tone="ok" testId="record-done" title="Записано: загружено через Studio" onClose={onClose}>
      <span>
        Подряд без правок: {s.streak} из {s.goal}
        {s.done ? ' — цель взята' : ''}.
      </span>
      <More className="mt-0">
        <span>{JSON.stringify(r.row)}</span>
        {r.ledger ? <span>{JSON.stringify(r.ledger)}</span> : null}
      </More>
    </Done>
  );
}

const EMPTY_READ = { title: '', description: '', tags: '', visibility: '', publishAt: '' };

function StudioRecord({
  channel,
  note,
  batchId,
}: {
  channel: string;
  note: PublishNote;
  batchId: string | null;
}) {
  const [vid, setVid] = useState('');
  const [read, setRead] = useState(EMPTY_READ);
  const [json, setJson] = useState('');
  const [replaces, setReplaces] = useState('');
  const [done, setDone] = useState<StudioRecordResult | null>(null);
  const videoId = videoIdOf(vid);
  const got = studioReadOf(read, json);
  const why = !videoId
    ? 'Впишите id ролика из Studio или ссылку на него'
    : got.why
      ? got.why
      : null;
  const set = (k: keyof typeof EMPTY_READ) => (v: string) => setRead((x) => ({ ...x, [k]: v }));
  return (
    <>
      <Disclosure
        id="studio-record"
        label="Загружено через Studio"
        tip="Вы загрузили ролик в Studio сами: фабрика сверит поля с карточкой и запишет загрузку в журнал"
      >
        <p className="m-0 text-xs text-muted-foreground">
          Перепишите то, что Studio показывает после сохранения, — фабрика сверит с карточкой.
        </p>
        <Field
          label="Ролик в Studio"
          value={vid}
          onChange={setVid}
          testId="record-video"
          placeholder="id из 11 знаков или ссылка youtube.com/shorts/…"
          tip="Id ролика, который показывает Studio, или ссылка на ролик"
          invalid={!!vid.trim() && !videoId}
        />
        <Field label="Название" value={read.title} onChange={set('title')} testId="record-title" />
        <Field
          label="Описание"
          rows={3}
          value={read.description}
          onChange={set('description')}
          testId="record-description"
        />
        <Field
          label="Теги"
          value={read.tags}
          onChange={set('tags')}
          testId="record-tags"
          tip="Через запятую — как в поле тегов Studio"
        />
        <div className="grid gap-2.5 sm:grid-cols-2">
          <Field
            label="Видимость"
            value={read.visibility}
            onChange={set('visibility')}
            testId="record-visibility"
            placeholder="Запланировано"
          />
          <Field
            label="Время публикации"
            value={read.publishAt}
            onChange={set('publishAt')}
            testId="record-publish-at"
            placeholder="2026-10-12T01:00+03:00"
            tip="Дата и время, как стоят в Studio, с часовым поясом"
          />
        </div>
        <Field
          label="Или JSON целиком"
          rows={2}
          value={json}
          onChange={setJson}
          testId="record-json"
          placeholder='{"title": "…", "tags": […], "visibility": "Запланировано", "publish_at": "…"}'
          tip="Что прочитала проверка Studio у оператора; если вставлен — поля выше не берутся"
          invalid={!!json.trim() && !!got.why}
        />
        <Field
          label="Заменяет ролик"
          value={replaces}
          onChange={setReplaces}
          testId="record-replaces"
          placeholder="необязательно: id прошлой загрузки"
          tip="Только при перезаливе: id ролика, который этот заменяет"
        />
        <WriteAction
          id="studio-record"
          label="Проверить и записать…"
          title="Записать загрузку из Studio?"
          description="Фабрика сверила то, что показывает Studio, с карточкой ролика."
          body={
            videoId && got.read
              ? {
                  slug: note.slug,
                  day: note.day,
                  ...(batchId ? { batch_id: batchId } : {}),
                  video_id: videoId,
                  read: got.read,
                  replaces: videoIdOf(replaces) ?? (replaces.trim() || null),
                }
              : null
          }
          why={why}
          tip="Фабрика сверит поля с карточкой и покажет план; запись — после вашего «да»"
          confirmLabel="Записать"
          plan={(b) => planStudioRecord(channel, b)}
          act={(c) => studioRecord(channel, c)}
          view={(p) => <RecordPlanView plan={p} />}
          onDone={(r) => {
            setDone(r);
            setVid('');
            setRead(EMPTY_READ);
            setJson('');
            setReplaces('');
          }}
        />
      </Disclosure>
      {done ? <RecordDone r={done} onClose={() => setDone(null)} /> : null}
    </>
  );
}

// ---------------------------------------------------------------- карточка
function Upload({
  channel,
  note,
  batchId,
}: {
  channel: string;
  note: PublishNote;
  batchId: string | null;
}) {
  const sw = useApiUpload(channel);
  const st = sw.data?.channels.find((c) => c.channel === channel);
  const [answer, setAnswer] = useState('');
  const [done, setDone] = useState<UploadResult | null>(null);
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <WriteAction
          id="upload"
          label="Загрузить на YouTube…"
          title="Загрузить ролик на YouTube?"
          description="Фабрика проверила ролик сухим прогоном — ничего не отправлено. Загрузка — после вашего «да»."
          body={{ slug: note.slug, day: note.day, ...(batchId ? { batch_id: batchId } : {}) }}
          tip="Фабрика проверит ролик, карточку и переключатель и покажет, что уйдёт на YouTube"
          confirmLabel="Загрузить"
          pendingLabel="Загружаю…"
          ready={!!answer.trim()}
          onOpen={() => setAnswer('')}
          plan={(b) => planUpload(channel, b)}
          act={(c) => upload(channel, c, answer)}
          view={(p) => <UploadPlanView plan={p} answer={answer} setAnswer={setAnswer} />}
          waiting={
            <span data-testid="upload-waiting">
              Ролик уходит на YouTube — это может занять несколько минут. Окно ждёт ответа фабрики;
              второй раз загрузка не начнётся.
            </span>
          }
          keptNote={(code) =>
            code === 'answer_required'
              ? 'Подтверждение ещё годно — впишите «да» и нажмите ещё раз.'
              : 'Подтверждение ещё годно — подождите и нажмите ещё раз.'
          }
          after={(e) => <UploadAfter error={e} />}
          onDone={(r) => {
            setDone(r);
            setAnswer('');
          }}
        />
        {st ? (
          <StatusBadge
            tone={st.on ? 'ok' : 'idle'}
            tip={
              st.on
                ? 'Переключатель API-загрузки канала включён'
                : 'Переключатель API-загрузки выключен: фабрика откажет, ролик грузите через Studio'
            }
          >
            {st.on ? 'API-загрузка включена' : 'API-загрузка выключена'}
          </StatusBadge>
        ) : null}
      </div>
      {done ? <UploadDone r={done} onClose={() => setDone(null)} /> : null}
    </>
  );
}

export function UploadWrites({
  channel,
  note,
  batchId = null,
  selected,
  failed,
}: {
  channel: string;
  note: PublishNote | undefined;
  /** CC-0183: какой из тёзок копилки: записи шлют его батч. */
  batchId?: string | null;
  selected: boolean;
  /** Карточка ролика не читается — грузить нечего (отказ — в карточке для Studio). */
  failed: boolean;
}) {
  return (
    <Card aria-labelledby="upload-title" data-testid="upload-writes" data-tour="upload">
      <CardHead eyebrow="Загрузка" title="Ролик на YouTube" titleId="upload-title" />
      {/* CC-0120: хук «загрузка» — подсвеченная «Прочитать Studio», если пора; сам ничего не запускает. */}
      <StudioDue hook="upload" channel={channel} className="mb-3" />
      {!selected ? (
        <EmptyState title="Ролик не выбран">
          Нажмите занятый слот в ленте — здесь можно будет загрузить его или отметить загрузку из
          Studio.
        </EmptyState>
      ) : failed ? (
        <p className="m-0 text-muted-foreground" data-testid="upload-no-note">
          Карточка ролика не читается — загрузка и отметка Studio недоступны.
        </p>
      ) : !note ? (
        <SkeletonText lines={2} label="Читаю карточку ролика…" />
      ) : note.day === RESERVE_DAY ? (
        <p className="m-0 text-muted-foreground" data-testid="upload-reserve">
          {RESERVE_WHY}
        </p>
      ) : (
        <div className="grid gap-3 text-[13px]">
          <Upload channel={channel} note={note} batchId={batchId} />
          <StudioRecord channel={channel} note={note} batchId={batchId} />
        </div>
      )}
    </Card>
  );
}
