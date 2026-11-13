// «Отозвать доступ»: сухой прогон `api_data.py revoke` без `--yes` — что сделал бы отзыв (Google
// отзовёт разрешение, токен на этой машине удалится, данные API удалятся — по каналам, фабрика
// запишет отметку), словами; строки фабрики как напечатаны — под «подробнее». Отозвать из центра
// (CC-0087, API CC-0082) — если фабрика это умеет (`confirm_available`): план фабрики и «да»
// (`WriteAction`), итог — структурный: что ответил Google, удалён ли файл токена, строка журнала
// удалений. Google не ответил — ничего не изменилось, токен на месте (предупреждение). Значения
// токена нет нигде — только вид («refresh token») и путь под «подробнее».
import { useState } from 'react';

import {
  oauthProblemText,
  planRevoke,
  planSize,
  revokeAccess,
  useAfterPurge,
  useRevoke,
  type OAuthRevokeOutcome,
  type OAuthRevokePlan,
  type OAuthRevokePreview,
  type OAuthRevokeResult,
} from '@/api/oauth';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { WriteGate } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { whoText } from '@/pages/batches/format';
import { Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';
import { Loaded } from '@/components/common/Loaded';

import { channelsWord, googleText, itemsWord, REVOKE_OFF } from './format';
import { Shares } from './Shares';

type Dry = Pick<OAuthRevokePreview, 'token_present' | 'plan'>;

function Steps({ r, testId = 'oauth-revoke-steps' }: { r: Dry; testId?: string }) {
  const n = planSize(r.plan);
  return (
    <ol className="m-0 grid list-decimal gap-1.5 pl-5 text-[13px]" data-testid={testId}>
      <li>
        {r.token_present
          ? 'Google отзовёт разрешение фабрики — токен перестанет действовать.'
          : n
            ? 'Отзывать у Google нечего — токена нет; данные API удалятся всё равно.'
            : 'Отзывать у Google нечего — токена нет.'}
      </li>
      {r.token_present ? <li>Файл токена на этой машине удалится.</li> : null}
      <li>
        {n
          ? `Данные API удалятся: ${itemsWord(n)} — ${channelsWord(r.plan.channels.length)}:`
          : 'Данных API нет — удалять нечего.'}
        {n ? <Shares plan={r.plan} testId="oauth-revoke-shares" className="mt-1.5" /> : null}
      </li>
      <li>Фабрика запишет отметку об отзыве и строку в журнал удалений.</li>
    </ol>
  );
}

/** Строки исхода фабрики под «подробнее»: путь файла токена, журнал, ответ Google — без значения. */
function OutcomeMore({ o }: { o: OAuthRevokeOutcome }) {
  return (
    <>
      <span>
        revoke_result · dry_run {String(o.dry_run)} · ok {String(o.ok)} · exit {o.exit} · by{' '}
        {o.by ?? '—'} · via {o.via ?? '—'}
      </span>
      <span>
        google: {o.google.answer ?? '—'}
        {o.google.detail ? ` · ${o.google.detail}` : ''} · {o.google.url}
      </span>
      <span>
        token: {o.token.file} · {o.token.kind ?? o.token.missing ?? '—'} · existed{' '}
        {String(o.token.existed)} · deleted {String(o.token.deleted)}
      </span>
      <span>state: {o.state_file}</span>
      <span>
        журнал удалений: {o.log} · reason {o.reason}
      </span>
    </>
  );
}

function RevokePlanView({ plan }: { plan: OAuthRevokePlan }) {
  const dry: Dry = { token_present: plan.result.token.existed, plan: plan.plan };
  return (
    <>
      <PlanHead plan={plan} yes="можно отозвать" no="отозвать нельзя" />
      {plan.ok ? (
        <p
          className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] px-3 py-2"
          data-testid="oauth-revoke-irreversible"
        >
          <b className="font-semibold">Вернуть нельзя:</b> загрузка через API и сбор метрик встанут,
          пока вы снова не войдёте в Google; удалённые данные API не вернутся.
        </p>
      ) : null}
      {plan.ok ? (
        <>
          <p className="m-0">Что сделает отзыв:</p>
          <Steps r={dry} testId="oauth-revoke-plan-steps" />
        </>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground">
        Отзывает: {whoText(plan.by) ?? plan.by}, из центра — так и запишется в журнал удалений.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · by {plan.by} · via {plan.via}
        </span>
        <OutcomeMore o={plan.result} />
        {plan.plan.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

export function RevokeDone({
  result,
  onClose,
}: {
  result: OAuthRevokeResult;
  onClose: () => void;
}) {
  const o = result.result;
  const n = planSize(result.plan);
  return (
    <div data-testid="oauth-revoke-result" data-ok={result.ok ? '1' : '0'}>
      <Done
        tone={result.ok ? 'ok' : 'warn'}
        testId="oauth-revoke-done"
        title={result.ok ? 'Доступ отозван' : 'Доступ не отозван — Google не ответил'}
        onClose={onClose}
      >
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="oauth-revoke-outcome">
          {result.ok ? (
            <li data-testid="oauth-revoke-google">{googleText(o.google.answer)}.</li>
          ) : null}
          <li data-testid="oauth-revoke-token">
            {o.token.deleted
              ? 'Файл токена на этой машине удалён.'
              : o.token.existed
                ? 'Ничего не изменилось: файл токена на месте, данные API не тронуты.'
                : 'Файла токена не было.'}
          </li>
          {result.ok ? (
            <li data-testid="oauth-revoke-deleted">
              {n ? `Данные API удалены: ${itemsWord(n)}.` : 'Данных API не было.'}{' '}
              {o.deletion ? 'Запись в журнале удалений сделана: вы, из центра.' : ''}
            </li>
          ) : null}
        </ul>
        {!result.ok ? (
          <span data-testid="oauth-revoke-why">
            Попробуйте позже или отзовите на странице разрешений Google.
          </span>
        ) : null}
        <More className="mt-0">
          {result.why ? <span>{result.why}</span> : null}
          <OutcomeMore o={o} />
          {o.deletion
            ? Object.entries(o.deletion).map(([k, v]) => (
                <span key={k}>
                  {k}: {typeof v === 'string' ? v : JSON.stringify(v)}
                </span>
              ))
            : null}
        </More>
      </Done>
    </div>
  );
}

function RevokeView({ r }: { r: OAuthRevokePreview }) {
  const [done, setDone] = useState<OAuthRevokeResult | null>(null);
  const after = useAfterPurge();
  const available = r.confirm_available === true;
  const trigger = (
    <Button size="sm" variant="destructive" data-testid="oauth-revoke-open">
      Отозвать доступ…
    </Button>
  );
  return (
    <div className="grid gap-3" data-testid="oauth-revoke-view">
      <p className="m-0 text-[13px]">Что сделает отзыв доступа:</p>
      <Steps r={r} />
      <p className="m-0 text-[13px] text-muted-foreground">
        После отзыва загрузка через API и сбор метрик остановятся, пока вы снова не войдёте в
        Google. Цифры из Studio останутся.
      </p>
      <div
        className="flex flex-wrap items-center gap-2"
        data-testid="oauth-revoke-button"
        data-available={String(available)}
      >
        {available ? (
          <WriteAction
            id="oauth-revoke"
            label="Отозвать доступ…"
            title="Отозвать доступ к YouTube?"
            description="Фабрика составила план — вот что произойдёт после вашего «да»."
            body={true}
            tip="Фабрика покажет, что сделает отзыв; отзовёт — после вашего «да»"
            confirmLabel="Отозвать"
            pendingLabel="Отзываю…"
            danger
            plan={() => planRevoke()}
            act={revokeAccess}
            view={(p) => <RevokePlanView plan={p} />}
            problemText={oauthProblemText}
            onSettled={after}
            onDone={setDone}
          />
        ) : (
          <WriteGate why={REVOKE_OFF} wide>
            {trigger}
          </WriteGate>
        )}
        <Button size="sm" variant="ghost" asChild>
          <a
            href={r.google_page}
            target="_blank"
            rel="noreferrer noopener"
            data-testid="oauth-google-page"
          >
            Страница разрешений Google ↗
          </a>
        </Button>
      </div>
      {done ? <RevokeDone result={done} onClose={() => setDone(null)} /> : null}
      <More className="mt-0">
        <span>сухой прогон фабрики — как напечатан:</span>
        {r.lines.map((l, i) => (
          <span key={i} className="whitespace-pre-wrap">
            {l}
          </span>
        ))}
        <span>confirm_available: {String(r.confirm_available)}</span>
      </More>
    </div>
  );
}

export function Revoke() {
  const q = useRevoke();
  return (
    <Card aria-labelledby="oauth-revoke-title" data-testid="oauth-revoke">
      <CardHead
        eyebrow="Отзыв доступа к YouTube"
        title="Отозвать доступ"
        titleId="oauth-revoke-title"
      />
      <Loaded q={q} reading="Фабрика составляет план отзыва…" failed="План отзыва не составлен">
        {(r) => <RevokeView r={r} />}
      </Loaded>
    </Card>
  );
}
