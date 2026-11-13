// Бюджет поиска текущих суток квоты (`plan.quota_budget.today`, CF-0830, CC-0152): лимит, сколько
// потрачено (записано и ожидается у батчей без записи), сколько осталось и сколько батчей в эти
// сутки уже было и сколько можно. Квота поиска YouTube общая на все каналы — это в подсказке.
// Батчи суток квоты (`held`) — каналом, временем и кто запустил («запустило расписание»,
// «запуск вручную»); строки фабрики — под «Подробнее».
import type { SchedulePlan } from '@/api/schedule';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { Tip } from '@/components/common/Tip';

import { BUDGET_TIP, budgetLines, heldBatches, heldText } from './budget';
import { useChannelNames, useChannelText } from './names';
import { Row } from './parts';

/** `YYYY-MM-DD` → «10.10». */
const ddmm = (day: string) => {
  const [, m, d] = day.split('-');
  return d && m ? `${d}.${m}` : day;
};

export function SearchBudget({ plan }: { plan: SchedulePlan }) {
  const name = useChannelNames();
  const human = useChannelText();
  const qb = plan.quota_budget;
  const t = qb?.today;
  if (!qb || !t) return null;
  const l = budgetLines(t);
  const held = heldBatches(t.held ?? []);
  const multi = qb.windows_channels ?? [];
  const expected = Object.entries(plan.channels)
    .filter(([, c]) => c.plannable && c.expected_searches)
    .map(([id, c]) => ({ id, e: c.expected_searches! }));
  return (
    <Card aria-labelledby="budget-title" data-testid="search-budget" className="grid content-start">
      <CardHead
        eyebrow="Бюджет поиска YouTube"
        title={
          <Tip content={BUDGET_TIP} wide>
            <span
              tabIndex={0}
              data-testid="budget-tip"
              className="cursor-help underline decoration-muted-foreground decoration-dotted underline-offset-4"
            >
              Сутки квоты {ddmm(t.quota_day)}
            </span>
          </Tip>
        }
        titleId="budget-title"
      />
      <ul className="m-0 grid list-none p-0 text-[13px]">
        <Row label="Лимит" tip="Поисков в сутки квоты на все каналы вместе" testId="budget-limit">
          {l.limit}
        </Row>
        <Row
          label="Потрачено"
          tip="Записанные поиски батчей этих суток квоты и ожидаемые у батчей, чей расход ещё не записан"
          testId="budget-spent"
        >
          {l.spent}
        </Row>
        <Row
          label="Осталось"
          tip="До запаса — сколько ещё можно потратить, чтобы фабрика допустила второй батч; в скобках — всего до лимита суток"
          testId="budget-left"
        >
          {l.left}
        </Row>
        <Row
          label="Батчей"
          tip="Сколько батчей уже было в эти сутки квоты и сколько можно — потолок фабрики"
          testId="budget-batches"
        >
          {l.batches}
        </Row>
      </ul>
      {held.length ? (
        <p className="m-0 mt-2 text-[13px] text-muted-foreground" data-testid="budget-held">
          {held.length === 1 ? 'Батч этих суток: ' : 'Батчи этих суток: '}
          {held.map((h) => heldText(h, name)).join('; ')}
        </p>
      ) : null}
      <p className="m-0 mt-2 text-[13px] text-muted-foreground" data-testid="budget-multi">
        {multi.length
          ? `Второй батч в сутки квоты может взять: ${multi.map(name).join(', ')}`
          : 'Ни у одного канала нет нескольких окон\u00a0— второго батча в сутки квоты не будет'}
      </p>
      <More className="mt-1">
        {expected.map(({ id, e }) => (
          <span key={id}>
            {name(id)} ждёт на батч: {human(e.line ?? String(e.searches))}
          </span>
        ))}
        {t.held?.map((h) => (
          <span key={`raw-${h}`}>батч суток: {h}</span>
        ))}
        {t.unrecorded?.map((u, i) => (
          <span key={`u-${i}`}>
            без записи: {u.batch ?? u.channel ?? '—'}
            {u.expected != null ? ` · ожидается ${u.expected}` : ''}
          </span>
        ))}
        {qb._note ? <span>правило: {qb._note}</span> : null}
      </More>
    </Card>
  );
}
