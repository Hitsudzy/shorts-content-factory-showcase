// «Токен YouTube»: состояние токена публикатора без значения (`publisher_auth.py status` — фабрика
// читает только файл, без сети): плашка состояния и срок словами, режим приложения, когда выдан,
// разрешения (scope) — есть или нет, на месте ли файлы токена, клиента и состояния (их содержимое
// API не читает). Вход в Google — ваш, центр за вас не входит: команда переразрешения показана с
// кнопкой «Скопировать». Строка фабрики, код и поля файла состояния — под «подробнее».
import { useToken, type OAuthToken } from '@/api/oauth';
import { Card, CardHead } from '@/components/common/Card';
import { CopyButton } from '@/components/common/CopyButton';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { whenText } from '@/pages/notify/format';
import { Fact, Loaded } from '@/components/common/Loaded';

import {
  modeMismatch,
  modeText,
  needsSignIn,
  SCOPE,
  scopeLabel,
  termText,
  TOKEN_KIND,
} from './format';

function Scopes({ t }: { t: OAuthToken }) {
  const granted = t.scopes.granted ? new Set(t.scopes.granted) : null;
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="oauth-scopes">
      {t.scopes.required.map((s) => {
        const short = t.scopes.short[s] ?? s;
        const has = granted ? granted.has(s) : null;
        return (
          <StatusBadge
            key={s}
            tone={has === null ? 'idle' : has ? 'ok' : 'danger'}
            tip={`${SCOPE[short]?.tip ?? short}. ${
              has === null ? 'Есть ли у токена — неизвестно' : has ? 'Есть' : 'Нет у токена'
            }`}
          >
            <span data-testid="oauth-scope" data-scope={short} data-granted={String(has)}>
              {has === false ? 'нет: ' : ''}
              {scopeLabel(short)}
            </span>
          </StatusBadge>
        );
      })}
    </div>
  );
}

const present = (yes: boolean, tip: string) => (
  <StatusBadge tone={yes ? 'ok' : 'idle'} tip={tip}>
    {yes ? 'на месте' : 'нет'}
  </StatusBadge>
);

/** Команда переносится по пробелам и после «/», не посреди слова. */
function Breakable({ text }: { text: string }) {
  // Куски между пробелами и «/» не рвутся (и не по «-» в «--authorize»), перенос — только между.
  const parts = text.split(/(?<=\/)|(?= )/);
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {p.startsWith(' ') ? ' ' : null}
          <span className="whitespace-nowrap">{p.trimStart()}</span>
          {i < parts.length - 1 && !parts[i + 1]!.startsWith(' ') ? <wbr /> : null}
        </span>
      ))}
    </>
  );
}

function SignIn({ t }: { t: OAuthToken }) {
  const urgent = needsSignIn(t.kind);
  return (
    <div
      className="grid gap-2 rounded-sm border p-3"
      data-testid="oauth-signin"
      data-urgent={urgent ? '1' : undefined}
      style={
        urgent
          ? {
              borderColor: 'color-mix(in srgb, var(--warning) 40%, var(--border))',
              background: 'color-mix(in srgb, var(--warning) 7%, var(--card))',
            }
          : undefined
      }
    >
      <b className="text-sm font-semibold">
        {t.kind === 'no-auth'
          ? 'Разрешить доступ'
          : urgent
            ? 'Переразрешить доступ'
            : 'Переразрешить заранее'}
      </b>
      <p className="m-0 text-[13px]">
        Вход в Google — ваш: центр не входит за вас. Скопируйте команду входа и выполните её в
        терминале в папке фабрики — откроется браузер, ~30 секунд. Все галочки разрешений оставьте.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <CopyButton
          value={t.authorize_command}
          what="команда входа"
          tip="Скопировать команду в буфер — вставьте её в терминал"
          data-testid="oauth-command-copy"
        />
      </div>
      <More className="mt-0" label="Подробнее: команда входа">
        <code
          data-testid="oauth-command"
          className="rounded-sm border bg-background px-2.5 py-1.5 font-mono text-xs break-words"
        >
          <Breakable text={t.authorize_command} />
        </code>
      </More>
    </div>
  );
}

function TokenView({ t }: { t: OAuthToken }) {
  const k = TOKEN_KIND[t.kind];
  const st = t.state;
  return (
    <div className="grid gap-3" data-testid="oauth-token-view" data-kind={t.kind}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={k.tone} tip={k.tip}>
          <span data-testid="oauth-token-kind">{k.label}</span>
        </StatusBadge>
        <b className="font-semibold [overflow-wrap:anywhere]" data-testid="oauth-token-term">
          {termText(t)}
        </b>
      </div>
      {modeMismatch(t) ? (
        <p className="m-0 text-[13px] text-warning" data-testid="oauth-mode-hint">
          Токен выдан, пока приложение было в тестовом режиме Google, — у него остался срок. Новый
          вход снимет его.
        </p>
      ) : null}
      <dl className="m-0 grid gap-3 sm:grid-cols-2">
        <Fact label="Режим приложения">
          <span data-testid="oauth-mode">
            {modeText(t.token_mode ?? t.oauth_mode, t.lifetime_days)}
          </span>
        </Fact>
        <Fact label="Выдан">
          {whenText(st?.authorized_at, t.now) ? `${whenText(st?.authorized_at, t.now)} МСК` : '—'}
        </Fact>
        <div className="sm:col-span-2">
          <Fact label="Разрешения">
            <Scopes t={t} />
          </Fact>
        </div>
        <div className="sm:col-span-2">
          <Fact label="Файлы на этой машине">
            <span
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5"
              data-testid="oauth-files"
            >
              <span className="inline-flex items-center gap-1.5">
                токен{' '}
                {present(
                  t.token_present,
                  'Файл токена: центр только видит, что он есть, — содержимое не читается и не показывается',
                )}
              </span>
              <span className="inline-flex items-center gap-1.5">
                клиент OAuth{' '}
                {present(
                  t.client_secret_present,
                  'Файл OAuth-клиента из Google Cloud: без него войти нельзя. Содержимое не читается',
                )}
              </span>
              <span className="inline-flex items-center gap-1.5">
                состояние{' '}
                {present(
                  t.state_present,
                  'Файл рядом с токеном: когда выдан, срок, разрешения, отметки отказа. Значения токена в нём нет',
                )}
              </span>
            </span>
          </Fact>
        </div>
      </dl>
      <SignIn t={t} />
      <More className="mt-0">
        <span data-testid="oauth-token-line">{t.line}</span>
        <span>
          код {t.code} · часы фабрики {t.now} · истекает {t.expires_at ?? '—'} · осталось{' '}
          {t.hours_left ?? '—'} ч
        </span>
        <span>
          PUBLISHER_OAUTH_MODE={t.oauth_mode} · токен выдан в {t.token_mode ?? '—'} ·
          PUBLISHER_TOKEN_LIFETIME_DAYS={t.lifetime_days} · PUBLISHER_TOKEN_REMIND_HOURS=
          {t.remind_hours}
        </span>
        {st
          ? Object.entries(st)
              .filter(([, v]) => v !== null && v !== undefined)
              .map(([key, v]) => (
                <span key={key}>
                  {key}: {typeof v === 'string' ? v : JSON.stringify(v)}
                </span>
              ))
          : null}
      </More>
    </div>
  );
}

export function Token() {
  const q = useToken();
  return (
    <Card aria-labelledby="oauth-token-title" data-testid="oauth-token">
      <CardHead
        eyebrow="Только состояние — без запросов в Google"
        title="Токен YouTube"
        titleId="oauth-token-title"
      />
      <Loaded q={q} reading="Читаю состояние токена…" failed="Состояние токена не прочитать">
        {(t) => <TokenView t={t} />}
      </Loaded>
    </Card>
  );
}
