// Верхние карточки экрана «Версии и агенты»: фабрика (выпуск на `main`, версия README, где стоит
// копия, чистая ли), центр (версия, когда собран, пин модуля, договор API) и «что в работе» (ветки
// выпусков с живой рабочей копией). Коммиты, имена веток и файлов — под «Подробнее».
import type { ReactNode } from 'react';

import { CONTRACT } from '@/api/contract.gen';
import type { Versions } from '@/api/versions';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { whenText } from '@/pages/notify/format';
import { plural } from '@/pages/batches/format';

import { bare, branchText, branchTip, DOTTED, driftText, releaseOf, TIP } from './format';

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : '—');

/** Крупная версия — как числа на главной: Oswald. */
function Big({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <div
      className="font-display text-[34px] leading-none font-semibold tracking-[.02em]"
      data-testid={testId}
    >
      {children}
    </div>
  );
}

/** Строка «подпись — значение» списка карточки. */
function Row({ label, tip, children }: { label: string; tip?: string; children: ReactNode }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t py-2 text-[13px] first:border-t-0">
      {tip ? (
        <Tip wide content={tip}>
          <span tabIndex={0} className={`text-muted-foreground ${DOTTED}`}>
            {label}
          </span>
        </Tip>
      ) : (
        <span className="text-muted-foreground">{label}</span>
      )}
      <span className="flex flex-wrap items-center justify-end gap-1.5 text-right">{children}</span>
    </li>
  );
}

export function FactoryCard({ v }: { v: Versions }) {
  const f = v.factory;
  const dirty = f.dirty;
  return (
    <Card aria-labelledby="versions-factory-title" data-testid="versions-factory">
      <CardHead
        eyebrow="Фабрика"
        title="Выпуск на основной ветке"
        titleId="versions-factory-title"
      />
      <Big testId="versions-release">{f.release_tag ? bare(f.release_tag) : '—'}</Big>
      <p className="mt-1 mb-2 text-xs text-muted-foreground">
        {f.release_tag
          ? 'последний выпуск, до которого дошла основная ветка'
          : 'на основной ветке ещё нет выпуска'}
      </p>
      <ul className="m-0 grid list-none p-0">
        <Row label="Версия по описанию фабрики" tip={TIP.readme}>
          <span className="font-mono" data-testid="versions-readme">
            {f.version ?? 'не указана'}
          </span>
        </Row>
        <Row label="Эта копия">
          {f.git ? (
            <>
              {branchTip(f.branch) ? (
                <Tip wide content={branchTip(f.branch)}>
                  <span tabIndex={0} className={DOTTED} data-testid="versions-branch">
                    {branchText(f.branch)}
                  </span>
                </Tip>
              ) : (
                <span data-testid="versions-branch">{branchText(f.branch)}</span>
              )}
              <StatusBadge
                tone={f.branch_ok ? 'ok' : 'warn'}
                tip={
                  f.branch_ok
                    ? 'С основной ветки и с ветки выпуска фабрика может вести батч'
                    : 'Батч идёт только с основной ветки или с ветки выпуска'
                }
              >
                {f.branch_ok ? 'можно батч' : 'батч не пойдёт'}
              </StatusBadge>
            </>
          ) : (
            <StatusBadge
              tone="warn"
              tip="Папка фабрики не ведёт историю версий: выпуск и правки не проверить"
            >
              без истории версий
            </StatusBadge>
          )}
        </Row>
        <Row label="Рабочая копия">
          {dirty === null || dirty === undefined ? (
            <StatusBadge tone="idle" tip="Проверка правок не ответила — есть ли они, не видно">
              не проверить
            </StatusBadge>
          ) : dirty.length ? (
            <StatusBadge
              tone="warn"
              tip="В коде фабрики есть правки, которые не зафиксированы. Список файлов — под «Подробнее»"
            >
              в {dirty.length} {plural(dirty.length, 'файле', 'файлах', 'файлах')} правки
            </StatusBadge>
          ) : (
            <StatusBadge
              tone="ok"
              tip="Код фабрики совпадает с последней зафиксированной версией, правок нет"
            >
              чистая
            </StatusBadge>
          )}
        </Row>
      </ul>
      <More>
        <span>
          выпуск: {f.release_tag ?? '—'} · README: {f.version ?? '—'}
        </span>
        <span>
          HEAD {short(f.commit)} ({f.branch ?? 'detached'}) · main {short(f.main)}
        </span>
        {dirty?.length ? <span>изменены: {dirty.join(', ')}</span> : null}
        <span>договор API фабрики: {v.api}</span>
      </More>
    </Card>
  );
}

export function CenterCard({ v }: { v: Versions }) {
  const c = v.center;
  const mod = v.modules.find((m) => m.module === 'frontend') ?? v.modules[0] ?? null;
  const built = whenText(c.built_at);
  const sameContract = v.api === CONTRACT.version;
  return (
    <Card aria-labelledby="versions-center-title" data-testid="versions-center">
      <CardHead
        eyebrow="Командный центр"
        title="Установленная версия"
        titleId="versions-center-title"
      />
      <Big testId="versions-center-version">{c.version ?? '—'}</Big>
      <p className="mt-1 mb-2 text-xs text-muted-foreground">
        {c.built ? (built ? `собран ${built} МСК` : 'собран') : 'фабрика не нашла собранный центр'}
      </p>
      <ul className="m-0 grid list-none p-0">
        <Row label="Пин в фабрике" tip={TIP.pin}>
          {mod ? (
            <>
              <span className="font-mono">{mod.rev}</span>
              {mod.ok ? (
                <StatusBadge tone="ok" tip="Центр собран ровно из версии, закреплённой в фабрике">
                  на пине
                </StatusBadge>
              ) : (
                <StatusBadge
                  tone="warn"
                  tip={`${driftText(mod) ?? 'Расходится с пином'}. На батчи это не влияет — только на то, какой центр вы видите`}
                >
                  <span data-testid="versions-center-drift">расходится</span>
                </StatusBadge>
              )}
            </>
          ) : (
            <span className="text-muted-foreground">не закреплён</span>
          )}
        </Row>
        <Row label="Договор API" tip={TIP.contract}>
          {sameContract ? (
            <StatusBadge tone="ok" tip="Центр собран под тот же договор API, что отдаёт фабрика">
              совпадает
            </StatusBadge>
          ) : (
            <StatusBadge
              tone="warn"
              tip="Центр собран под другой договор API, чем у фабрики: часть экранов может не открыться. Пересоберите центр"
            >
              <span data-testid="versions-contract-diff">разный</span>
            </StatusBadge>
          )}
        </Row>
      </ul>
      <More>
        <span>
          центр {c.version ?? '—'} · раздача {c.dist ?? '—'}
          {c.built_at ? ` · собран ${c.built_at}` : ''}
        </span>
        <span>
          договор: центр {CONTRACT.version} · фабрика {v.api}
        </span>
        {mod ? (
          <span>
            {mod.path} · пин {mod.rev} → {short(mod.sha)} · HEAD {short(mod.head)}
            {mod.build ? ` · сборка из ${mod.build.rev ?? '—'} ${short(mod.build.sha)}` : ''}
          </span>
        ) : null}
        {mod?.why ? <span>{mod.why}</span> : null}
        {mod?.line ? <span>{mod.line}</span> : null}
      </More>
    </Card>
  );
}

export function InWorkCard({ v }: { v: Versions }) {
  const work = v.factory.versions_in_work ?? [];
  const tag = v.factory.release_tag;
  return (
    <Card aria-labelledby="versions-work-title" data-testid="versions-work">
      <CardHead
        eyebrow="Что в работе"
        title={
          work.length
            ? `${work.length} ${plural(work.length, 'версия готовится', 'версии готовятся', 'версий готовятся')}`
            : 'Ничего не готовится'
        }
        titleId="versions-work-title"
      />
      {work.length ? (
        <ul className="m-0 grid list-none gap-2 p-0" data-testid="versions-work-list">
          {work.map((b) => (
            <li
              key={b}
              data-testid="versions-work-item"
              className="flex flex-wrap items-center justify-between gap-2 rounded-sm border px-3 py-2"
            >
              <Tip wide content={TIP.release}>
                <span
                  tabIndex={0}
                  data-testid="versions-work-version"
                  className="font-display text-[20px] leading-none font-semibold tracking-[.02em]"
                >
                  {releaseOf(b) ?? b}
                </span>
              </Tip>
              <StatusBadge
                tone="live"
                tip="У ветки этого выпуска есть рабочая копия: версию сейчас собирают, на основной ветке её ещё нет"
              >
                готовится
              </StatusBadge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="versions-work-empty">
          Сейчас ни один выпуск не собирается: у веток выпусков нет рабочих копий
          {tag ? ` — фабрика работает на ${bare(tag)}` : ''}.
        </p>
      )}
      <p className="mt-3 mb-0 text-xs text-muted-foreground">
        Готовый выпуск попадает на основную ветку и становится версией фабрики.
      </p>
      {work.length ? (
        <More>
          {work.map((b) => (
            <span key={b}>{b}</span>
          ))}
        </More>
      ) : null}
    </Card>
  );
}
