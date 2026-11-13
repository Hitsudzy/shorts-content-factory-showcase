// Холды публикации канала (`GET /api/publish/holds?channel`): открытые (ролик не уйдёт, пока
// холд не снят) и снятые раньше. Холд content-sensitivity, у которого строка пришла с
// `signable: true`, центр подписывает от имени пользователя (CC-0071, API CC-0070): рядом —
// плеер ролика (сначала посмотреть), «Посмотрел, снимаю холд» раскрывает обязательную заметку,
// дальше — план фабрики (что отметил compliance-checker, что значит подпись) и «да» с отсчётом
// (./Writes). `signable: false` — вместо кнопки строка фабрики, почему нет. Реестр не читается —
// фабрика держит всё.
import { useId, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { publishKeys, RELEASED_DAYS, useHolds, type HoldRow } from '@/api/publish';
import { codeWithWords, reasonWords } from '@/api/reasonRu';
import { scenesText } from '@/api/sensitivityScenes';
import { holdSign, planHoldSign, type HoldSignPlan, type HoldTarget } from '@/api/publishWrites';
import { fpsOf, posterOf, useVideos, videoTitle } from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { WriteGate } from '@/components/common/WriteButton';
import { useToast } from '@/components/common/useToast';
import { Button } from '@/components/ui/button';
import { dateTimeMsk } from '@/pages/batches/format';
import { Player } from '@/pages/videos/Player';

import { flaggedText, holdWhen } from './format';
import { HoldScenes } from './HoldScenes';
import { ReleasedHolds } from './ReleasedHolds';
import { Field, PlanHead, WriteAction } from './Writes';
import { SkeletonList, SkeletonText } from '@/components/common/Skeletons';

const HOLD_TIP = 'Холд не пускает ролик в публикацию, пока его не снимут';

const SIGN_TIP =
  'Сначала посмотрите ролик. Подпись уйдёт от вашего имени с пометкой «из центра» — после плана фабрики и вашего «да»';

/** Ролик холда из батча: плеер, чтобы посмотреть его здесь, прежде чем снимать холд. */
function HoldVideo({ channel, hold }: { channel: string; hold: HoldRow }) {
  const batch = hold.batch_id ? `${channel}/${hold.batch_id}` : null;
  const q = useVideos(batch);
  const note = (text: string, alert = false) => (
    <p
      role={alert ? 'alert' : 'note'}
      data-testid="hold-video-missing"
      className="m-0 rounded-sm border p-3 text-[13px] text-muted-foreground"
    >
      {text}
    </p>
  );
  if (!batch) return note('В холде не записан батч — ролик здесь не показать.');
  if (q.isPending) return <SkeletonText lines={1} lineHeight={19.5} label="Читаю ролик…" />;
  if (q.isError)
    return note('Ролики батча не прочитать — проверьте, что API фабрики запущен.', true);
  const v = q.data.videos.find((x) => !!hold.script_id && x.script_id === hold.script_id);
  if (!v) return note('Этого ролика нет в списке роликов батча — посмотреть его здесь нельзя.');
  if (!v.mp4.exists) return note('Файла ролика нет — посмотреть его здесь нельзя.');
  return (
    <div data-testid="hold-video" data-slug={v.slug} className="grid gap-1">
      <Player
        key={v.slug}
        src={v.mp4.url}
        poster={posterOf(v.preview)}
        fps={fpsOf(null, v)}
        duration={v.duration}
        title={videoTitle(v)}
      />
      <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {videoTitle(v)}
      </span>
    </div>
  );
}

function Row({ k, testId, children }: { k: string; testId: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="m-0 [overflow-wrap:anywhere]" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

/** Строка фабрики «Сцены флага: …» в `flagged` — её показывает отдельная строка плана. */
const SCENES_LINE = /^Сцены флага:/;

/** План подписи: что отметил compliance-checker, что значит подпись, заметка и кто подписывает. */
function SignPlan({ plan }: { plan: HoldSignPlan }) {
  const scenes = scenesText(plan.sensitivity_scenes, plan.topic_id);
  const flagged = scenes ? plan.flagged.filter((f) => !SCENES_LINE.test(f)) : plan.flagged;
  return (
    <>
      <PlanHead plan={plan} yes="можно снять" no="снять нельзя" />
      <dl className="m-0 grid gap-2">
        <Row k="Что отметила проверка на риски" testId="sign-plan-flagged">
          {flagged.length ? (
            <ul className="m-0 grid list-disc gap-0.5 pl-5">
              {flagged.map((f) => (
                <li key={f}>{flaggedText(f)}</li>
              ))}
            </ul>
          ) : (
            'ничего не записано'
          )}
        </Row>
        {scenes ? (
          <Row k="Сцены флага" testId="sign-plan-scenes">
            {scenes}
          </Row>
        ) : null}
        <Row k="Что значит подпись" testId="sign-plan-meaning">
          {plan.meaning}
        </Row>
        <Row k="Заметка" testId="sign-plan-note">
          {plan.note}
        </Row>
        <Row k="Подпись" testId="sign-plan-signature">
          вы, из центра
        </Row>
      </dl>
      <More className="mt-0">
        <span>холд: {plan.hold_id}</span>
        {plan.flagged.map((f) => (
          <span key={`raw-${f}`}>{f}</span>
        ))}
        {plan.script_id ? <span>сценарий: {plan.script_id}</span> : null}
        {plan.verdict ? <span>вердикт: {plan.verdict}</span> : null}
        <span>
          подпишет: {plan.signature.user} · {plan.signature.via}
        </span>
        <span>реестр: {plan.ledger}</span>
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

/** «Посмотрел, снимаю холд»: заметка (обязательна) → план фабрики → «да» с отсчётом. */
function HoldSign({ channel, hold }: { channel: string; hold: HoldRow }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const panel = useId();
  const qc = useQueryClient();
  const toast = useToast();
  const target: HoldTarget | null =
    hold.batch_id && hold.topic_id ? { batch_id: hold.batch_id, topic_id: hold.topic_id } : null;
  const text = note.trim();
  return (
    <div className="grid gap-2" data-testid="hold-sign">
      <WriteGate tip={SIGN_TIP} wide>
        <Button
          size="sm"
          className="w-max"
          aria-expanded={open}
          aria-controls={panel}
          data-testid="hold-sign-toggle"
          onClick={() => setOpen((v) => !v)}
        >
          Посмотрел, снимаю холд
          <span aria-hidden>{open ? '▴' : '▾'}</span>
        </Button>
      </WriteGate>
      {open && target ? (
        <div
          id={panel}
          data-testid="hold-sign-form"
          className="grid gap-2.5 rounded-sm border p-3 text-[13px] text-foreground"
        >
          <Field
            label="Заметка — почему ролик можно публиковать"
            rows={3}
            value={note}
            onChange={setNote}
            testId="hold-sign-note"
            placeholder="Например: посмотрел — пострадавших крупно нет, кадры из новостей"
            tip="Обязательна: фабрика запишет её в реестр холдов рядом с вашей подписью «из центра»"
          />
          <WriteAction
            id="hold-sign"
            label="Проверить и снять…"
            title="Снять холд — подписать от вашего имени?"
            description="Фабрика проверила холд и показывает, что будет подписано."
            body={text || null}
            why={text ? null : 'Напишите заметку: почему ролик можно публиковать'}
            tip="Фабрика проверит холд и покажет план; подпись — после вашего «да»"
            confirmLabel="Подписать"
            pendingLabel="Подписываю…"
            plan={(n) => planHoldSign(channel, target, n)}
            act={(c) => holdSign(channel, target, c)}
            view={(p) => <SignPlan plan={p} />}
            onDone={(r) => {
              qc.setQueryData(publishKeys.holds(channel), r.holds);
              void qc.invalidateQueries({ queryKey: publishKeys.released(channel, RELEASED_DAYS) });
              toast('Холд снят: подпись записана от вашего имени, из центра');
              setNote('');
              setOpen(false);
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

/** Кто и когда подписал снятый холд (`signature {user, date, note, via}`), если записано. */
function signedText(sig: HoldRow['signature']): string | null {
  if (!sig) return null;
  const s = sig as Record<string, unknown>;
  const str = (k: string) => (typeof s[k] === 'string' ? (s[k] as string) : null);
  const who = str('user') ?? str('by');
  const when = dateTimeMsk(str('date') ?? str('at'));
  const via = str('via') === 'center' ? ', из центра' : '';
  const note = str('note');
  if (!who && !when) return null;
  const name = who === 'user' ? 'вы' : (who ?? '—');
  return `подпись: ${name}${via}${when ? `, ${when}` : ''}${note ? ` — ${note}` : ''}`;
}

function OpenHold({ channel, hold: h }: { channel: string; hold: HoldRow }) {
  const signable = h.signable === true;
  return (
    <li
      data-testid="hold"
      data-signable={signable ? '1' : '0'}
      className="grid gap-3 border-t py-2.5 first:border-t-0 first:pt-0"
    >
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
        <div className="grid gap-0.5">
          <span className="font-semibold [overflow-wrap:anywhere]">
            {reasonWords(h) ?? 'Причина не записана'}
          </span>
          <span className="text-xs text-muted-foreground">с {holdWhen(h)}</span>
          <HoldScenes hold={h} />
          <More className="mt-1">
            <span>холд: {h.hold_id}</span>
            {h.batch_id ? <span>батч: {h.batch_id}</span> : null}
            {h.script_id ? <span>сценарий: {h.script_id}</span> : null}
            {h.topic_id ? <span>тема: {h.topic_id}</span> : null}
            {h.reason_code ? <span>код: {codeWithWords(h)}</span> : null}
            {h.sign_refusal ? <span>не подписать: {h.sign_refusal.code}</span> : null}
          </More>
        </div>
        <StatusBadge tone="warn" tip={HOLD_TIP}>
          холд
        </StatusBadge>
      </div>
      {signable ? (
        <div className="grid items-start gap-3 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)]">
          <div className="w-full max-w-[220px]">
            <HoldVideo channel={channel} hold={h} />
          </div>
          <HoldSign channel={channel} hold={h} />
        </div>
      ) : h.sign_refusal ? (
        <p
          data-testid="hold-sign-refusal"
          data-code={h.sign_refusal.code}
          className="m-0 text-[13px] text-muted-foreground [overflow-wrap:anywhere]"
        >
          {h.sign_refusal.text_ru}
        </p>
      ) : null}
    </li>
  );
}

export function Holds({ channel }: { channel: string }) {
  const q = useHolds(channel);
  const open = q.data?.open ?? [];
  const resolved = (q.data?.rows ?? []).filter((r) => !open.some((o) => o.hold_id === r.hold_id));
  return (
    <Card
      id="holds"
      aria-labelledby="holds-title"
      data-testid="holds"
      data-tour="holds"
      className="scroll-mt-36"
    >
      <CardHead
        eyebrow="Холды публикации"
        title={q.data ? (open.length ? `Открытых: ${open.length}` : 'Открытых нет') : 'Холды'}
        titleId="holds-title"
      />
      {q.isPending ? (
        <SkeletonList rows={3} sub={1} label="Читаю холды…" />
      ) : q.isError ? (
        <ErrorState title="Холды не прочитать" error={q.error} onRetry={() => void q.refetch()}>
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : q.data.problem ? (
        <div
          role="alert"
          data-testid="holds-problem"
          className="rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] p-3 text-[13px]"
        >
          <div className="font-semibold text-danger">Реестр холдов не читается</div>
          <p className="m-0 mt-1 text-muted-foreground">
            Пока его не починят, фабрика держит каждый ролик — в публикацию ничего не уйдёт.
          </p>
          <More>
            <span>{q.data.problem}</span>
            <span>реестр: {q.data.path}</span>
          </More>
        </div>
      ) : (
        <>
          {open.length ? (
            <ul className="m-0 grid list-none p-0" data-testid="holds-open">
              {open.map((h) => (
                <OpenHold key={h.hold_id ?? h.raised_at} channel={channel} hold={h} />
              ))}
            </ul>
          ) : (
            <EmptyState title="Открытых холдов нет">Ничто не держит ролики канала.</EmptyState>
          )}
          {resolved.length ? (
            <details className="mt-3 text-[13px]" data-testid="holds-resolved">
              <summary className="w-max cursor-pointer text-primary-text">
                Снятые раньше: {resolved.length}
              </summary>
              <ul className="m-0 mt-2 grid list-none gap-2 p-0">
                {resolved.map((h) => {
                  const signed = signedText(h.signature);
                  return (
                    <li
                      key={h.hold_id ?? h.raised_at}
                      className="grid gap-0.5"
                      data-testid="hold-resolved"
                    >
                      <span>{h.reason ?? 'Причина не записана'}</span>
                      <HoldScenes hold={h} />
                      {h.resolved_at || !signed ? (
                        <span className="text-xs text-muted-foreground">
                          снят {dateTimeMsk(h.resolved_at) ?? '—'}
                          {h.resolved_reason ? `: ${h.resolved_reason}` : ''}
                        </span>
                      ) : null}
                      {signed ? (
                        <span className="text-xs text-muted-foreground" data-testid="hold-signed">
                          {signed}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </details>
          ) : null}
          <ReleasedHolds channel={channel} />
          <More>
            <span>реестр: {q.data.path}</span>
          </More>
        </>
      )}
    </Card>
  );
}
