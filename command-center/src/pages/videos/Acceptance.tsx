// Приёмка ролика (CC-0062): «Да / Нет / Переделать» — `POST …/acceptance {verdict, words,
// reason?, reason_code?, amend?}` только по нажатию и после подтверждения (`ConfirmDialog`,
// вне рабочей фабрики погашен). Слова — как набраны, с заготовкой из имени ролика: фабрика
// пишет вердикт только под именем (CF-0328). «Нет»/«Переделать» — причина и её код (из
// словаря батча `reason_codes` или новый). Второй вердикт — с «почему меняем» (`amend`):
// поле открыто, если вердикт уже есть, и открывается на отказ `verdict_already_given`.
// Отказ фабрики — её `message` как есть, `code` и `details` — под «подробнее»; отказ
// `video_refused` (ролик отказан после монтажа, CC-0116) — своими словами (./refusal).
import { useId, useState } from 'react';
import { Link } from 'react-router';

import { problemCode } from '@/api/batchProblem';
import {
  REASON_CODE,
  useAccept,
  videoTitle,
  wordsPrefill,
  type AcceptResult,
  type ReasonCode,
  type Verdict,
  type Video,
} from '@/api/videos';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { AcceptBuild } from '@/pages/publishing/CardState';
import { withoutPath } from '@/pages/publishing/stashWords';
import { StatusBadge } from '@/components/common/Status';
import { Refusal } from '@/pages/batches/parts';
import { inputBase } from '@/pages/channels/styles';

import { leftOutText, namesakeText, notifiedText, type LeftOut } from './leftOut';
import { VIDEO_REFUSED_TEXT } from './refusal';

const NEW_CODE = '__new';

const COPY: Record<
  Verdict,
  {
    trigger: string;
    title: (name: string) => string;
    description: string;
    confirm: string;
    variant: 'default' | 'outline' | 'destructive';
    tip: string;
  }
> = {
  yes: {
    trigger: 'Да',
    title: (n) => `Принять ролик «${n}»?`,
    description:
      'Вердикт запишется в журнал приёмки фабрики вашими словами. В словах должно быть имя ролика — так вердикт привязан к ролику, а не к месту в списке.',
    confirm: 'Принять',
    variant: 'default',
    tip: 'Принять ролик: он сможет уйти в публикацию',
  },
  no: {
    trigger: 'Нет',
    title: (n) => `Снять ролик «${n}»?`,
    description:
      'Ролик не уйдёт в публикацию. Нужна причина одной фразой и её код — по коду фабрика считает, какие причины повторяются.',
    confirm: 'Снять',
    variant: 'destructive',
    tip: 'Снять ролик: в публикацию он не уйдёт',
  },
  redo: {
    trigger: 'Переделать',
    title: (n) => `Вернуть ролик «${n}» на переделку?`,
    description:
      'Вердикт запишется как отказ с пометкой «переделать» — с причиной и её кодом. Ролик не уйдёт в публикацию, пока его не пересоберут.',
    confirm: 'Вернуть на переделку',
    variant: 'outline',
    tip: 'Вернуть ролик на переделку: отказ с просьбой переделать',
  },
};

function codeLabel(c: ReasonCode) {
  const phrase = c.phrases[0];
  const count = c.count ? ` · ${c.count}` : '';
  return phrase ? `${c.code} — ${phrase}${count}` : `${c.code}${count}`;
}

function VerdictDialog({
  verdict,
  batch,
  video,
  name,
  reasonCodes,
  onAnswer,
}: {
  verdict: Verdict;
  batch: string;
  video: Video;
  name: string;
  reasonCodes: ReasonCode[];
  onAnswer: (r: AcceptResult) => void;
}) {
  const copy = COPY[verdict];
  const accept = useAccept(batch, video.slug);
  const decided = !!video.acceptance?.verdict;
  const rejecting = verdict !== 'yes';
  const [open, setOpen] = useState(false);
  const [words, setWords] = useState(() => wordsPrefill(video.slug));
  const [reason, setReason] = useState('');
  const [pick, setPick] = useState(reasonCodes.length ? '' : NEW_CODE);
  const [newCode, setNewCode] = useState('');
  const [amend, setAmend] = useState('');
  const [askAmend, setAskAmend] = useState(decided);
  const ids = { words: useId(), reason: useId(), code: useId(), newCode: useId(), amend: useId() };
  const code = pick === NEW_CODE ? newCode.trim() : pick;
  const badNew = pick === NEW_CODE && newCode.trim() !== '' && !REASON_CODE.test(newCode.trim());

  const onOpenChange = (v: boolean) => {
    setOpen(v);
    if (v) {
      accept.reset();
      setWords(wordsPrefill(video.slug));
      setReason('');
      setPick(reasonCodes.length ? '' : NEW_CODE);
      setNewCode('');
      setAmend('');
      setAskAmend(decided);
    }
  };
  const confirm = () =>
    accept.mutate(
      {
        verdict,
        // Слова — ровно как набраны: их фабрика и запишет.
        words,
        reason: rejecting ? reason.trim() || null : null,
        reason_code: rejecting ? code || null : null,
        amend: amend.trim() || null,
      },
      {
        onSuccess: (r) => {
          onAnswer(r);
          setOpen(false);
        },
        onError: (e) => {
          if (problemCode(e) === 'verdict_already_given') setAskAmend(true);
        },
      },
    );

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      trigger={
        <Button
          variant={copy.variant}
          data-testid={`verdict-${verdict}`}
          className="flex-1 sm:flex-none"
        >
          {copy.trigger}
        </Button>
      }
      tip={copy.tip}
      title={copy.title(name)}
      description={copy.description}
      confirmLabel={copy.confirm}
      pendingLabel="Записываю…"
      pending={accept.isPending}
      danger={verdict === 'no'}
      confirmTestId="verdict-confirm"
      onConfirm={confirm}
      error={
        accept.isError ? (
          <Refusal
            error={accept.error}
            title="Фабрика не записала вердикт"
            message={problemCode(accept.error) === 'video_refused' ? VIDEO_REFUSED_TEXT : null}
          />
        ) : null
      }
    >
      <div className="grid gap-3 text-[13px]" data-testid="verdict-form" data-verdict={verdict}>
        <label htmlFor={ids.words} className="grid gap-1">
          <span className="font-semibold">Ваши слова</span>
          <textarea
            id={ids.words}
            data-testid="verdict-words"
            rows={2}
            value={words}
            onChange={(e) => setWords(e.target.value)}
            className={inputBase}
          />
          <span className="text-xs text-muted-foreground">
            Запишутся как есть. Имя ролика — «{video.slug}» — уже вписано; без него фабрика вердикт
            не примет.
          </span>
        </label>
        {rejecting ? (
          <>
            <label htmlFor={ids.reason} className="grid gap-1">
              <span className="font-semibold">Причина — одной фразой</span>
              <input
                id={ids.reason}
                data-testid="verdict-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="например: хук скучный, нет кадра со студией"
                className={inputBase}
              />
            </label>
            <label htmlFor={ids.code} className="grid gap-1">
              <span className="font-semibold">Код причины</span>
              <select
                id={ids.code}
                data-testid="verdict-code"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
                className={inputBase}
              >
                {reasonCodes.length ? <option value="">— выберите код —</option> : null}
                {reasonCodes.map((c) => (
                  <option key={c.code} value={c.code}>
                    {codeLabel(c)}
                  </option>
                ))}
                <option value={NEW_CODE}>новый код…</option>
              </select>
            </label>
            {pick === NEW_CODE ? (
              <label htmlFor={ids.newCode} className="grid gap-1">
                <span className="font-semibold">Новый код</span>
                <input
                  id={ids.newCode}
                  data-testid="verdict-new-code"
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  placeholder="например: blurry_footage"
                  autoCapitalize="off"
                  spellCheck={false}
                  aria-invalid={badNew || undefined}
                  className={cn(inputBase, 'font-mono')}
                />
                <span className={cn('text-xs', badNew ? 'text-warning' : 'text-muted-foreground')}>
                  Строчная латиница, цифры и «_», с буквы: так фабрика считает повторы причин.
                </span>
              </label>
            ) : null}
          </>
        ) : null}
        {askAmend ? (
          <label htmlFor={ids.amend} className="grid gap-1" data-testid="verdict-amend-field">
            <span className="font-semibold">Почему меняем</span>
            <textarea
              id={ids.amend}
              data-testid="verdict-amend"
              rows={2}
              value={amend}
              onChange={(e) => setAmend(e.target.value)}
              placeholder="например: пересмотрел — хук всё-таки держит"
              className={inputBase}
            />
            <span className="text-xs text-muted-foreground">
              У ролика уже есть вердикт: заменить его можно, только сказав, почему передумали.
              Старый уйдёт в историю.
            </span>
          </label>
        ) : null}
      </div>
    </ConfirmDialog>
  );
}

/** Канал копилки: из пути `publish/<канал>/…`, иначе — из папки батча (не пересборки). */
function stashChannel(r: AcceptResult): string | null {
  const m = /^publish\/([^/]+)\//.exec(r.queued?.publish_path ?? '');
  if (m) return m[1]!;
  const dir = r.batch.split('/')[0];
  return dir && dir !== 'rebuilds' && r.batch.includes('/') ? dir : null;
}

/**
 * CF-0821 (CC-0152): принятый ролик не лёг в копилку — громкая метка «Не в копилке», своя строка
 * центра по коду и названию ролика, тёзка одной строкой и было ли уведомление. Строки фабрики,
 * батч и пути — под «Подробнее».
 */
function LeftOutMark({
  x,
  title,
  testId = 'left-out',
}: {
  x: LeftOut;
  title?: string | null;
  testId?: string;
}) {
  const ns = namesakeText(x.namesake);
  const sent = notifiedText(x.notified);
  return (
    <div
      data-testid={testId}
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_45%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_8%,var(--card))] p-2"
    >
      <StatusBadge tone="danger" className="w-max font-semibold">
        Не в копилке
      </StatusBadge>
      <span data-testid={`${testId}-alert`}>{leftOutText(x, title)}</span>
      {ns ? (
        <span data-testid={`${testId}-namesake`} className="text-muted-foreground">
          {ns}
        </span>
      ) : null}
      {sent ? <span className="text-xs text-muted-foreground">{sent}</span> : null}
      <More className="mt-0">
        {x.alert_ru ? <span>фабрика: {x.alert_ru}</span> : null}
        {x.slug || x.batch_id ? (
          <span>
            ролик: {x.slug ?? '—'}
            {x.batch_id ? ` · батч ${x.batch_id}` : ''}
            {x.code ? ` · ${x.code}` : ''}
          </span>
        ) : null}
        {x.namesake?.publish_path ? <span>тёзка: {x.namesake.publish_path}</span> : null}
        {x.namesake?.why ? <span>тёзка, почему другой: {x.namesake.why}</span> : null}
      </More>
    </div>
  );
}

/** CC-0122: куда лёг принятый ролик — копилка канала или почему нет (строка фабрики как есть). */
function Queued({ r, title }: { r: AcceptResult; title?: string | null }) {
  const q = r.queued;
  // CF-0821: верхний `left_out` без `queued` (старая очередь ответа) — тоже громко.
  if (!q && r.left_out) return <LeftOutMark x={r.left_out} title={title} />;
  if (!q) {
    if (r.verdict === 'yes' && r.pending)
      return (
        <p className="m-0" data-testid="acceptance-answer-queued" data-code="pending">
          В копилку канала ролик ляжет, когда вердикт закоммитится.
        </p>
      );
    return null;
  }
  const channel = stashChannel(r);
  const out = q.left_out || !!r.left_out;
  return (
    <div
      className="grid gap-0.5"
      data-testid="acceptance-answer-queued"
      data-code={q.code}
      data-left-out={out || undefined}
    >
      {out ? (
        <LeftOutMark
          title={title}
          x={{
            ...r.left_out,
            batch_id: r.left_out?.batch_id ?? r.batch,
            code: q.code ?? r.left_out?.code,
            text_ru: q.text_ru,
            alert_ru: q.alert_ru ?? r.left_out?.alert_ru,
            namesake: q.namesake ?? r.left_out?.namesake,
            notified: q.notified ?? r.left_out?.notified,
          }}
        />
      ) : null}
      <p className={cn('m-0', q.refused && 'text-warning')} hidden={out}>
        {q.ok ? 'Копилка: ' : q.refused ? 'Не в копилке: ' : ''}
        <span data-testid="acceptance-answer-queued-text">{withoutPath(q.text_ru)}</span>
      </p>
      {/* CC-0127: приёмка сама запустила сборку карточки — «собирается…» до итога. */}
      {q.card_build ? <AcceptBuild channel={channel} build={q.card_build} /> : null}
      {channel ? (
        <Link
          to={`/publishing?channel=${encodeURIComponent(channel)}`}
          className="w-max text-xs text-primary-text hover:underline"
          data-testid="acceptance-answer-stash"
        >
          {q.refused ? 'Доложить в копилку — на «Публикации»' : 'Копилка канала на «Публикации»'}
        </Link>
      ) : null}
    </div>
  );
}

/** Ответ фабрики на вердикт: записано / ждёт конца батча / просьба не в очереди. */
function Answer({ r, title }: { r: AcceptResult; title?: string | null }) {
  return (
    <div
      role="status"
      data-testid="acceptance-answer"
      data-pending={r.pending || undefined}
      className={cn(
        'grid gap-1 rounded-sm border p-2.5 text-[13px]',
        r.pending
          ? 'border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))]'
          : 'border-[color-mix(in_srgb,var(--success)_40%,var(--border))] bg-[color-mix(in_srgb,var(--success)_7%,var(--card))]',
      )}
    >
      <p className="m-0 font-semibold" data-testid="acceptance-answer-text">
        {r.pending
          ? 'Записано, ждёт конца батча.'
          : r.committed
            ? 'Записано.'
            : 'Принято фабрикой.'}
      </p>
      {r.pending && r.batches.length ? (
        <ul className="m-0 grid list-none gap-0.5 p-0" data-testid="acceptance-answer-batches">
          {r.batches.map((b) => (
            <li key={b.dir}>{b.why ?? 'идёт батч'}</li>
          ))}
        </ul>
      ) : null}
      {r.pending ? (
        <p className="m-0 text-muted-foreground">
          Фабрика закоммитит вердикт, когда батч закончится.
        </p>
      ) : null}
      <Queued r={r} title={title} />
      {r.flushed?.left_out?.length ? (
        <div className="grid gap-1" data-testid="acceptance-answer-flush-left-out">
          <p className="m-0">Из очереди вердиктов в копилку не легли:</p>
          {r.flushed.left_out.map((x, i) => (
            <LeftOutMark key={x.entry_id ?? i} x={x} testId="flush-left-out" />
          ))}
        </div>
      ) : null}
      {r.redo && !r.redo.queued ? (
        <p className="m-0" data-testid="acceptance-answer-redo">
          Просьба записана, в очередь оператору ещё не поставлена.
        </p>
      ) : null}
      <More className="mt-0">
        {r.subject ? <span>коммит: {r.subject}</span> : null}
        {r.commit ? <span>sha: {r.commit}</span> : null}
        <span>журнал: {r.log}</span>
        {r.queue ? <span>очередь: {r.queue}</span> : null}
        {r.batches.map((b) => (
          <span key={b.dir}>идёт: {b.dir}</span>
        ))}
        {r.flushed?.subject ? <span>сначала закоммичена очередь: {r.flushed.subject}</span> : null}
        {r.flushed?.why ? <span>очередь: {r.flushed.why}</span> : null}
        {r.redo?.reason ? <span>переделка: {r.redo.reason}</span> : null}
        {r.queued ? (
          <span>
            копилка: {r.queued.code}
            {r.queued.publish_path ? ` · ${r.queued.publish_path}` : ''}
          </span>
        ) : null}
        {r.queued?.text_ru ? (
          <span data-testid="acceptance-answer-queued-raw">строка фабрики: {r.queued.text_ru}</span>
        ) : null}
        {r.queued?.namesake?.entry_id ? <span>тёзка: {r.queued.namesake.entry_id}</span> : null}
        {r.queued?.notified ? <span>уведомление: {JSON.stringify(r.queued.notified)}</span> : null}
        {r.flushed?.left_out?.map((x, i) => (
          <span key={`lo-${i}`}>
            не в копилке из очереди: {x.entry_id ?? x.slug} · {x.code}
            {x.text_ru ? ` · ${x.text_ru}` : ''}
          </span>
        ))}
        {r.queued?.card_build ? (
          <span>
            карточка: {r.queued.card_build.launched ? 'сборка запущена' : 'сборка не запущена'}
            {r.queued.card_build.run_id ? ` · ${r.queued.card_build.run_id}` : ''}
            {r.queued.card_build.skipped ? ` · ${r.queued.card_build.skipped}` : ''}
            {r.queued.card_build.refusals?.length
              ? ` · ${r.queued.card_build.refusals.join(', ')}`
              : ''}
            {r.queued.card_build.log ? ` · ${r.queued.card_build.log}` : ''}
            {r.queued.card_build.why ? ` · почему: ${r.queued.card_build.why}` : ''}
          </span>
        ) : null}
      </More>
    </div>
  );
}

/** Кнопки вердикта в карточке приёмки и ответ фабрики на последний из них. */
export function AcceptanceActions({
  batch,
  video,
  reasonCodes,
}: {
  batch: string;
  video: Video;
  reasonCodes: ReasonCode[];
}) {
  const [answer, setAnswer] = useState<AcceptResult | null>(null);
  const name = videoTitle(video);
  const props = { batch, video, name, reasonCodes, onAnswer: setAnswer };
  return (
    <div data-slot="acceptance-actions" className="grid gap-2.5">
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label="Ваше решение по ролику"
        data-tour="acceptance"
      >
        <VerdictDialog verdict="yes" {...props} />
        <VerdictDialog verdict="redo" {...props} />
        <VerdictDialog verdict="no" {...props} />
      </div>
      {answer ? <Answer r={answer} title={name} /> : null}
    </div>
  );
}
