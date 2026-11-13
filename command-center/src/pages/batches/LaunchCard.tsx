// Запуск батча вручную (`POST /api/batches/launch/plan {channel}` → `POST …/launch {channel,
// confirm}`, CC-0046): окно открывается проверкой фабрики — защиты списком, `why`, что ручной
// запуск не проверяет; «Запустить» — только при `confirm` и пока не истёк его срок (отсчёт на
// кнопке). Отказ `confirm_*`/`check_changed` — проверка заново сама; 409 `refused` (вкл.
// «1 батч в сутки») — сообщение фабрики как есть. Успех — `line` фабрики, pid и журнал —
// под «подробнее»; список идущих батчей перечитывается. Отказ защиты, у которой есть батч
// (`batches` защиты; у `today` — упавший батч канала, что держит день, CC-0089), ведёт к его
// карточке на этом же экране: окно закрывается, фокус — на карточке. Вход Claude (CC-0177):
// план без входа — строка и «да» придержано до «Проверить снова»; вход не проверить — мягкое
// предупреждение, и в плане, и рядом с «Батч запущен»; 409 `not_logged_in` — текст фабрики.
import { useId, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';

import { launch, planLaunch, useAfterAction, type LaunchResult } from '@/api/batchActions';
import { problemCode } from '@/api/batchProblem';
import { useGoingBatches, useStrandedBatches } from '@/api/batches';
import { humanDashes, humanReason, nbShort, withoutCodes } from '@/api/humanText';
import type { PlanChannel } from '@/api/schedule';
import { Card, CardHead } from '@/components/common/Card';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { StudioDue } from '@/components/studio/StudioRead';
import { Button } from '@/components/ui/button';
import { inputBase } from '@/pages/channels/styles';

import { confirmText, guardLabel } from './actions';
import { manualBreakerText } from './breaker';
import { admissionText } from './budget';
import { FlowNotes, Outcome, ReplanButton } from './ActionParts';
import { dateTimeMsk } from './format';
import {
  LOGIN_MISSING_TEXT,
  loginMissing,
  loginUnknown,
  loginUnknownText,
  NOT_LOGGED_IN,
} from './login';
import { Ticked } from './Ticked';
import { useChannelNames, useChannelText } from './names';
import {
  batchAnchor,
  guardLinks,
  guardText,
  isKnownGuard,
  linkWhen,
  type GuardLink,
} from './stranded';
import { useConfirmFlow } from './useConfirmFlow';

function linkText(l: GuardLink): string | null {
  const when = linkWhen(l);
  if (l.kind === 'stranded')
    return `${l.row.holds_day ? 'Батч, что держит день' : 'Упавший батч'}: ${when ?? 'дата неизвестна'} →`;
  if (l.kind === 'open') return `Открытый батч: ${when ?? 'идёт'} →`;
  return null;
}

function firstChannel(channels: Record<string, PlanChannel>) {
  const ids = Object.keys(channels);
  return ids.find((id) => channels[id]!.plannable) ?? ids[0] ?? '';
}

export function LaunchCard({ channels }: { channels: Record<string, PlanChannel> }) {
  const name = useChannelNames();
  const say = useChannelText();
  // Строки фабрики: каналы именами, « - » — тире (CC-0131: «лента на 3 дн. вперёд (≥ 3) — батч»).
  const human = (text: string) => humanDashes(say(text));
  const ids = Object.keys(channels);
  // CC-0120: ссылка уведомления несёт `?channel=` — канал запуска выбран по ней.
  const [params] = useSearchParams();
  const asked = params.get('channel');
  const fromUrl = asked && ids.includes(asked) ? asked : null;
  // Выбор человека главнее адреса; новая ссылка (другой `?channel=`) — снова по адресу.
  const [picked, setChannel] = useState<string | null>(null);
  const [seenUrl, setSeenUrl] = useState(fromUrl);
  if (seenUrl !== fromUrl) {
    setSeenUrl(fromUrl);
    setChannel(null);
  }
  const channel = picked ?? fromUrl ?? firstChannel(channels);
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState<LaunchResult | null>(null);
  const after = useAfterAction();
  const selectId = useId();
  const stranded = useStrandedBatches();
  const going = useGoingBatches();
  /** Куда перейти, когда окно закроется (ссылка из отказа защиты). */
  const jumpTo = useRef<string | null>(null);

  const flow = useConfirmFlow({
    plan: planLaunch,
    act: (confirm: string, ch: string) => launch(ch, confirm),
    onDone: (r: LaunchResult) => {
      setDone(r);
      setOpen(false);
    },
    onSettled: () => after(),
  });

  const onOpenChange = (v: boolean) => {
    setOpen(v);
    if (v) {
      setDone(null);
      flow.start(channel);
    } else flow.reset();
  };
  const plan = flow.plan;
  // CC-0177: вход Claude — не защита, но без него «да» получит отказ: кнопку придерживаем, пока
  // человек не войдёт и не нажмёт «Проверить снова» (новый план). Отказ `not_logged_in` на «да»
  // (вход пропал после плана) — та же кнопка: токен потрачен.
  const noLogin = loginMissing(plan?.login);
  const loginWait = noLogin || problemCode(flow.actError) === NOT_LOGGED_IN;
  // Строка размыкателя (CF-0822) — пометкой выше, в списке «не проверяет» второй раз не повторяем.
  const skippedShown = plan ? plan.skipped.filter((s) => s !== plan.breaker?.line) : [];
  const linksOf = (g: Parameters<typeof guardLinks>[0]) =>
    guardLinks(g, stranded.data?.batches ?? [], going.data?.batches ?? []);
  // Отказ — словами центра по первой не пройденной защите, которую он знает; иначе строка
  // фабрики без путей и кодов. Сама строка — под «подробнее».
  const refused = plan?.guards.find((g) => !g.ok);
  const whyText = !plan
    ? ''
    : !plan.ok && refused && isKnownGuard(refused.name)
      ? human(guardText(refused, linksOf(refused)))
      : human(humanReason(plan.why));
  const jump = (batch: string) => {
    jumpTo.current = batchAnchor(batch);
    onOpenChange(false);
  };
  const onCloseAutoFocus = (e: Event) => {
    const id = jumpTo.current;
    jumpTo.current = null;
    const el = id ? document.getElementById(id) : null;
    if (!el) return;
    e.preventDefault();
    el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    el.focus({ preventScroll: true });
  };

  return (
    <Card
      aria-labelledby="launch-title"
      data-testid="batches-actions"
      data-tour="launch"
      className="grid content-start gap-3"
    >
      <CardHead eyebrow="Действия" title="Запуск вручную" titleId="launch-title" />
      <p className="m-0 text-muted-foreground">
        Батч канала сейчас, не дожидаясь расписания. Сначала фабрика проверяет, можно ли; запуск —
        только после вашего «да». Остановить и продолжить — на карточке батча вверху.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor={selectId} className="grid min-w-0 flex-1 gap-1 text-[13px]">
          <span className="text-muted-foreground">Канал</span>
          <select
            id={selectId}
            data-testid="launch-channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            className={inputBase}
          >
            {ids.map((id) => (
              <option key={id} value={id}>
                {name(id)}
              </option>
            ))}
          </select>
        </label>
        <ConfirmDialog
          open={open}
          onOpenChange={onOpenChange}
          tip="Фабрика проверит защиты запуска; батч стартует только после вашего «да»"
          trigger={
            <Button data-testid="launch-open" disabled={!channel}>
              Проверить и запустить…
            </Button>
          }
          title={`Запустить батч ${name(channel)}?`}
          description="Фабрика проверила, можно ли запустить батч сейчас."
          confirmLabel={loginWait ? 'Запустить' : confirmText('Запустить', flow)}
          pendingLabel="Запускаю…"
          pending={flow.acting}
          confirmDisabled={!flow.canConfirm || loginWait}
          confirmTestId="launch-confirm"
          onConfirm={() => void flow.confirm()}
          onCloseAutoFocus={onCloseAutoFocus}
          extraActions={
            loginWait ? (
              flow.planning ? null : (
                <Button variant="ghost" onClick={() => flow.replan()} data-testid="login-recheck">
                  Проверить снова
                </Button>
              )
            ) : (
              <ReplanButton flow={flow} onClick={() => flow.replan()} />
            )
          }
        >
          {/* CC-0120: хук «запуск батча» только подсвечивает «Прочитать Studio» — батч его не ждёт. */}
          <StudioDue hook="batch-start" channel={channel} enabled={open} />
          {plan ? (
            <div className="grid gap-3 text-[13px]" data-testid="launch-plan">
              <div className="flex flex-wrap items-center gap-2">
                {/* Защиты пройдены, но без входа «да» придержано — бейдж не зелёный (CC-0177). */}
                <StatusBadge tone={!plan.ok ? 'danger' : loginWait ? 'warn' : 'ok'}>
                  {!plan.ok
                    ? 'запуск сейчас невозможен'
                    : loginWait
                      ? 'запуск придержан: нет входа в Claude'
                      : 'можно запускать'}
                </StatusBadge>
                <span data-testid="launch-why">{whyText}</span>
              </div>
              {noLogin ? (
                <p
                  role="status"
                  data-testid="launch-login"
                  data-login="missing"
                  className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-2.5"
                >
                  <Ticked text={LOGIN_MISSING_TEXT} />
                </p>
              ) : loginUnknown(plan.login) ? (
                <p
                  data-testid="launch-login"
                  data-login="unknown"
                  className="m-0 text-[13px] text-warning"
                >
                  <Ticked text={loginUnknownText(plan.login?.line)} />
                </p>
              ) : null}
              <ul className="m-0 grid list-none gap-1.5 p-0" data-testid="launch-guards">
                {plan.guards.map((g) => {
                  const links = linksOf(g);
                  return (
                    <li
                      key={g.name}
                      data-testid="launch-guard"
                      data-ok={g.ok}
                      className="grid grid-cols-[18px_minmax(0,1fr)] items-baseline gap-1.5"
                    >
                      <span aria-hidden className={g.ok ? 'text-success' : 'text-danger'}>
                        {g.ok ? '✓' : '✗'}
                      </span>
                      <span>
                        <b className="font-semibold">{guardLabel(g.name)}</b>
                        <span className="sr-only">{g.ok ? ' — пройдено' : ' — не пройдено'}</span>
                        <span className="text-muted-foreground" data-testid="launch-guard-text">
                          {' '}
                          — {human(guardText(g, links))}
                        </span>
                        {links.map((l) => {
                          const text = linkText(l);
                          return text ? (
                            <Button
                              key={l.batch}
                              variant="ghost"
                              data-testid="launch-guard-batch"
                              data-batch={l.batch}
                              onClick={() => jump(l.batch)}
                              className="mt-1.5 flex h-auto min-h-[34px] max-w-full py-1 text-left whitespace-normal text-primary-text"
                            >
                              {text}
                            </Button>
                          ) : null;
                        })}
                      </span>
                    </li>
                  );
                })}
              </ul>
              {plan.breaker ? (
                <p
                  className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))] p-2.5"
                  data-testid="launch-breaker"
                >
                  {nbShort(manualBreakerText(plan.breaker, name))}
                </p>
              ) : null}
              {plan.budget ? (
                <p className="m-0 text-muted-foreground" data-testid="launch-budget">
                  Бюджет поиска: {nbShort(admissionText(plan.budget))}
                </p>
              ) : null}
              {skippedShown.length ? (
                <div className="grid gap-1" data-testid="launch-skipped">
                  <Tip content="Это проверки таймера расписания: при запуске вручную фабрика их не делает">
                    <span
                      tabIndex={0}
                      data-testid="launch-skipped-tip"
                      className="w-max text-muted-foreground underline decoration-dotted underline-offset-4"
                    >
                      Ручной запуск не проверяет
                    </span>
                  </Tip>
                  <ul className="m-0 grid list-disc gap-0.5 pl-5">
                    {skippedShown.map((s) => (
                      <li key={s}>{withoutCodes(s)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <More className="mt-0">
                <span>фабрика: {plan.why}</span>
                {plan.breaker?.line ? <span>защита от повтора: {plan.breaker.line}</span> : null}
                {plan.budget?.why ? <span>бюджет: {plan.budget.why}</span> : null}
                {plan.guards.map((g) => (
                  <span key={`line-${g.name}`}>
                    {g.name}: {g.line}
                  </span>
                ))}
                {plan.skipped.map((s) => (
                  <span key={`skip-${s}`}>не проверяет: {s}</span>
                ))}
                {plan.login ? (
                  <span>
                    вход claude: {plan.login.line}
                    {plan.login.checked ? '' : ' (не спрашивали)'}
                  </span>
                ) : null}
                <span>день фабрики {plan.today}</span>
                {plan.argv ? <span>запустит: {plan.argv.join(' ')}</span> : null}
                <span>отпечаток проверки {plan.fingerprint}</span>
                {plan.guards.flatMap((g) =>
                  linksOf(g).map((l) => (
                    <span key={`${g.name}-${l.batch}`}>
                      {guardLabel(g.name)}: батч {l.batch}
                    </span>
                  )),
                )}
                {plan.expires_in_s != null ? (
                  <span>подтверждение живёт {plan.expires_in_s} с</span>
                ) : null}
              </More>
            </div>
          ) : null}
          {/* Без входа отсчёт плана не показываем: «да» придержано до новой проверки. */}
          <FlowNotes
            flow={loginWait ? { ...flow, left: null } : flow}
            timeoutText="Фабрика не ответила вовремя. Посмотрите «Идёт сейчас» — батч мог стартовать."
          />
        </ConfirmDialog>
      </div>
      {done ? (
        <Outcome tone="ok" title="Батч запущен" testId="launch-done" onClose={() => setDone(null)}>
          <span data-testid="launch-line">{human(done.line)}</span>
          {loginUnknown(done.login) ? (
            <span data-testid="launch-login-warn" className="text-warning">
              <Ticked text={loginUnknownText(done.login?.line)} />
            </span>
          ) : null}
          <span className="text-muted-foreground">
            Он появится в «Идёт сейчас» со следующей проверкой.
          </span>
          <More className="mt-0">
            {done.pid != null ? <span>pid {done.pid}</span> : null}
            {done.log ? <span>журнал {done.log}</span> : null}
            {done.login ? <span>вход claude: {done.login.line}</span> : null}
            <span>
              запись запуска: {dateTimeMsk(done.row.at) ?? done.row.at} · {done.row.by ?? '—'}
              {done.row.kind ? ` · ${done.row.kind}` : ''}
            </span>
          </More>
        </Outcome>
      ) : null}
    </Card>
  );
}
