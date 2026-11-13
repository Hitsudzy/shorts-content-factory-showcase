// «Каналы уведомлений»: сухая проверка `notify.py test` — какие каналы доставки включены, какие из
// них отправляют текст с этой машины, и по каждому — поля `preview` (`notify.test_preview`, CC-0087):
// примет ли он сообщение, а если нет — почему (какой настройки нет — словами), и что он получил бы.
// Строки проверки фабрики, как она их напечатала, и путь журнала — под «подробнее». Ничего не
// отправляется, журнал не трогается. Отправить по-настоящему — «Отправить пробное сообщение…»
// (./TestSend, CC-0115): план → ваше «да».
import { useCheck, type NotifyBackendPreview, type NotifyCheck } from '@/api/notify';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Button } from '@/components/ui/button';
import { Loaded } from '@/components/common/Loaded';

import { BACKEND, backendLabel, previewText } from './format';
import { TestSend } from './TestSend';

/** Почему канал пропустил бы сообщение — словами (строку фабрики — под «подробнее»). */
function skipText(p: NotifyBackendPreview): string {
  if (!p.known) return 'фабрика такого канала не знает — сообщение он не получит';
  if (p.external)
    return 'не настроен — в настройках фабрики нет его адреса, сообщение он пропустит';
  return 'сообщение он пропустит';
}

function WouldGet({ text }: { text: string }) {
  const t = previewText(text);
  return (
    <span className="grid gap-0.5">
      <span className="text-xs text-muted-foreground">Получил бы:</span>
      <span
        className="border-l-2 border-primary pl-3 text-[13px] whitespace-pre-wrap [overflow-wrap:anywhere]"
        data-testid="notify-check-would-get"
      >
        {t.lines.join('\n') || '—'}
        {t.link ? (
          <span className="block text-xs text-muted-foreground">и ссылку на центр</span>
        ) : null}
      </span>
    </span>
  );
}

function Preview({ rows }: { rows: NotifyBackendPreview[] }) {
  return (
    <ul className="m-0 grid list-none gap-2 p-0" data-testid="notify-check-preview">
      {rows.map((p) => (
        <li
          key={p.name}
          data-testid="notify-check-backend"
          data-name={p.name}
          data-ready={p.ready ? '1' : '0'}
          className="grid gap-1 rounded-sm border px-3 py-2"
        >
          <span className="flex flex-wrap items-center gap-2">
            <b className="font-semibold">{backendLabel(p.name)}</b>
            <StatusBadge
              tone={p.ready ? 'ok' : 'warn'}
              tip={p.ready ? 'Канал примет сообщение' : 'Канал пропустит сообщение'}
            >
              {p.ready ? 'примет' : 'пропустит'}
            </StatusBadge>
            {p.external ? (
              <StatusBadge tone="idle" tip="Текст уходит с этой машины во внешний сервис">
                уходит с машины
              </StatusBadge>
            ) : null}
          </span>
          {!p.ready ? (
            <span className="text-xs text-warning" data-testid="notify-check-skip">
              {skipText(p)}
            </span>
          ) : null}
          {p.would_get ? <WouldGet text={p.would_get} /> : null}
          {p.skip_reason || p.would_get ? (
            <More className="mt-0">
              {p.skip_reason ? (
                <span>
                  {p.name}: {p.skip_reason}
                </span>
              ) : null}
              {p.would_get ? (
                <span className="whitespace-pre-wrap">текст фабрики: {p.would_get}</span>
              ) : null}
            </More>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Summary({ c }: { c: NotifyCheck }) {
  const external = new Set(c.external);
  const isDefault =
    c.backends.length === c.default.length && c.backends.every((b) => c.default.includes(b));
  return (
    <div className="grid gap-2" data-testid="notify-check-summary">
      <div className="flex flex-wrap items-center gap-1.5" data-testid="notify-check-on">
        <span className="text-muted-foreground">Включены:</span>
        {c.backends.length ? (
          c.backends.map((b) => (
            <StatusBadge
              key={b}
              tone={external.has(b) ? 'warn' : 'ok'}
              tip={BACKEND[b]?.tip ?? 'Канал доставки, который центр не знает'}
            >
              {backendLabel(b)}
            </StatusBadge>
          ))
        ) : (
          <span>ни один</span>
        )}
      </div>
      <p className="m-0" data-testid="notify-check-external">
        {c.external.length
          ? `С этой машины уходит: ${c.external.map(backendLabel).join(', ')} — текст уведомления получает внешний сервис.`
          : 'С этой машины ничего не уходит: включены только местные каналы.'}
      </p>
      <p className="m-0 text-xs text-muted-foreground" data-testid="notify-check-default">
        {isDefault
          ? `Это настройка по умолчанию: ${c.default.map(backendLabel).join(', ')}.`
          : `По умолчанию — ${c.default.map(backendLabel).join(', ')}; остальные включены в настройках фабрики.`}
      </p>
    </div>
  );
}

export function Check() {
  const q = useCheck();
  return (
    <Card aria-labelledby="notify-check-title" data-testid="notify-check">
      <CardHead
        eyebrow="Проверка всухую · ничего не отправляется"
        title="Каналы уведомлений"
        titleId="notify-check-title"
        actions={
          <Button
            size="sm"
            variant="ghost"
            data-testid="notify-check-again"
            disabled={q.isFetching}
            onClick={() => void q.refetch()}
          >
            {q.isFetching && !q.isPending ? 'Проверяю…' : 'Проверить ещё раз'}
          </Button>
        }
      />
      <Loaded q={q} reading="Фабрика проверяет каналы…" failed="Проверка каналов не прошла">
        {(c) => (
          <div className="grid gap-3">
            <Summary c={c} />
            {c.preview.length ? <Preview rows={c.preview} /> : null}
            <p className="m-0 text-xs text-muted-foreground" data-testid="notify-check-sent">
              {c.sent
                ? 'Проверка отправила сообщение.'
                : 'Ничего не отправлено, журнал не тронут — это проверка всухую.'}
            </p>
            <TestSend />
            <More className="mt-0">
              <span>notify.py test — как напечатано:</span>
              {c.lines.map((l, i) => (
                <span key={i} className="whitespace-pre-wrap" data-testid="notify-check-line">
                  {l}
                </span>
              ))}
            </More>
          </div>
        )}
      </Loaded>
    </Card>
  );
}
