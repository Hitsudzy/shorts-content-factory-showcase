import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { FilmStrip } from './FilmStrip';
import { spareText, type Frame, type FrameState } from './going';

const frame = (n: number, state: FrameState, extra: Partial<Frame> = {}): Frame => ({
  n,
  kind: 'trends',
  title: `Кадр ${n}`,
  tip: '',
  state,
  done: 0,
  total: 1,
  stages: [`stage-${n}`],
  current: false,
  ...extra,
});

const span = (stage: string, duration_s: number | null, open = false) => ({
  stage,
  started: null,
  done: null,
  open,
  duration_s,
});

const strip = (frames: Frame[], props: Partial<Parameters<typeof FilmStrip>[0]> = {}) => {
  render(
    <TooltipProvider>
      <FilmStrip frames={frames} {...props} />
    </TooltipProvider>,
  );
  return within(screen.getByTestId('film-strip')).getAllByRole('listitem');
};

describe('кинолента: законченное видно сразу (CC-0126)', () => {
  it('пять состояний различимы и без цвета: своё состояние, подпись и плёнка у каждого', () => {
    const li = strip(
      [
        frame(1, 'done', { done: 1 }),
        frame(2, 'now', { current: true }),
        frame(3, 'wait'),
        frame(4, 'bad'),
        frame(5, 'unneeded', { kind: 'extra' }),
      ],
      { nowText: 'идёт 20 мин из 1 ч 30 мин', spans: [span('stage-1', 3900)] },
    );
    expect(li.map((x) => x.dataset.state)).toEqual(['done', 'now', 'wait', 'bad', 'unneeded']);
    // Номер — только цифры (значок — в CSS по data-state), подписи — словами.
    expect(li.map((x) => x.querySelector('.film-num')?.textContent)).toEqual([
      '01',
      '02',
      '03',
      '04',
      '05',
    ]);
    expect(within(li[0]!).getByTestId('frame-small')).toHaveTextContent('готово · 1 ч 05 мин');
    expect(within(li[1]!).getByTestId('frame-small')).toHaveTextContent(
      'идёт 20 мин из 1 ч 30 мин',
    );
    expect(li[1]).toHaveAttribute('aria-current', 'step');
    expect(within(li[2]!).getByTestId('frame-small')).toHaveTextContent('ждёт');
    expect(within(li[3]!).getByTestId('frame-small')).toHaveTextContent('ошибка');
    expect(within(li[4]!).getByTestId('frame-small')).toHaveTextContent('не понадобился');
    // Готовое видно и на телефоне: подпись готового не прячется, ждущего — прячется.
    expect(within(li[0]!).getByTestId('frame-small')).not.toHaveClass('hidden');
    expect(within(li[2]!).getByTestId('frame-small')).toHaveClass('hidden');
  });

  it('плёнка: до идущего кадра — пройдена, дальше — впереди; у последнего её нет', () => {
    const li = strip([
      frame(1, 'done'),
      frame(2, 'unneeded', { kind: 'extra' }),
      frame(3, 'now', { current: true }),
      frame(4, 'wait'),
      frame(5, 'wait'),
    ]);
    expect(li.map((x) => x.dataset.link)).toEqual([
      'passed',
      'passed',
      'ahead',
      'ahead',
      undefined,
    ]);
  });

  it('готовый кадр без пролётов — просто «готово»; пропущенный — «не в этом прогоне»', () => {
    const li = strip([frame(1, 'skip'), frame(2, 'done'), frame(3, 'now', { current: true })]);
    expect(within(li[0]!).getByTestId('frame-small')).toHaveTextContent('не в этом прогоне');
    expect(within(li[1]!).getByTestId('frame-small')).toHaveTextContent(/^готово$/);
    expect(within(li[2]!).getByTestId('frame-small')).toHaveTextContent(/^идёт$/);
    expect(li.map((x) => x.dataset.link)).toEqual(['passed', 'passed', undefined]);
  });

  it('добор с запасными: «готово» + сколько запасных не понадобилось; «возможен добор»', () => {
    const li = strip([
      frame(1, 'done', { kind: 'extra', done: 2, total: 4, spare: 2 }),
      frame(2, 'done', { kind: 'extra', done: 2, total: 4, more: true }),
    ]);
    expect(within(li[0]!).getByTestId('frame-small')).toHaveTextContent(/^готово$/);
    expect(within(li[0]!).getByTestId('frame-spare')).toHaveTextContent(
      '2 запасных шага не понадобились',
    );
    expect(li[0]).not.toHaveTextContent('из 4 шагов');
    expect(within(li[1]!).getByTestId('frame-small')).toHaveTextContent('готово, возможен добор');
    expect(within(li[1]!).queryByTestId('frame-spare')).not.toBeInTheDocument();
    expect(spareText(1)).toBe('1 запасной шаг не понадобился');
    expect(spareText(6)).toBe('6 запасных шагов не понадобились');
  });

  it('батч вернулся за добором: «добор · идёт N мин», первый проход — в подсказке', async () => {
    const user = userEvent.setup();
    const li = strip(
      [
        frame(1, 'now', {
          kind: 'footage',
          current: true,
          returned: true,
          done: 1,
          total: 2,
          stages: ['footage-indexer', 'thin-pool-supplement'],
        }),
        frame(2, 'done'),
      ],
      { nowText: 'идёт 12 мин', spans: [span('footage-indexer', 1500)] },
    );
    expect(li[0]).toHaveAttribute('data-returned', 'true');
    const small = within(li[0]!).getByTestId('frame-small');
    expect(small).toHaveTextContent('добор · идёт 12 мин');
    expect(within(li[0]!).getByTestId('frame-first')).toHaveTextContent('первый проход готов');
    await user.tab();
    expect(small).toHaveFocus();
    const tip = await screen.findByRole('tooltip');
    expect(tip).toHaveTextContent('только когда основного не хватило');
    expect(tip).toHaveTextContent('Первый проход шёл 25 мин');
  });

  it('упала и остановлена: своё слово, а не «идёт N из …»', () => {
    const li = strip(
      [frame(1, 'bad', { current: true }), frame(2, 'stopped'), frame(3, 'unreached')],
      { nowText: 'идёт 2 ч' },
    );
    expect(within(li[0]!).getByTestId('frame-small')).toHaveTextContent('ошибка');
    expect(within(li[1]!).getByTestId('frame-small')).toHaveTextContent('остановлено');
    expect(within(li[2]!).getByTestId('frame-small')).toHaveTextContent('не дошёл');
    expect(screen.getByTestId('film-strip')).not.toHaveTextContent('идёт');
  });

  it('упавший батч: плёнка пройдена только между законченными кадрами, у недошедших нет итогов', () => {
    const li = strip(
      [
        frame(1, 'done', { kind: 'trends' }),
        frame(2, 'bad', { kind: 'footage' }),
        frame(3, 'unreached', { kind: 'research' }),
        frame(4, 'unreached', { kind: 'extra' }),
        frame(5, 'bad', { kind: 'accept' }),
      ],
      {
        summaries: {
          trends: ['нашёл 6 тем'],
          footage: ['футажа хватает: 1 из 2'],
          research: ['написал 2 сценария'],
        },
      },
    );
    // В упавший кадр, из него и в недошедшие — плёнка не пройдена.
    expect(li.map((x) => x.dataset.link)).toEqual(['ahead', 'ahead', 'ahead', 'ahead', undefined]);
    expect(within(li[0]!).getByTestId('frame-summary')).toHaveTextContent('нашёл 6 тем');
    expect(within(li[1]!).getByTestId('frame-summary')).toHaveTextContent('футажа хватает');
    expect(within(li[2]!).queryByTestId('frame-summary')).not.toBeInTheDocument();
  });

  it('итог вида — у последнего запускавшегося кадра: ждущий повтор вида итог не забирает', () => {
    const li = strip(
      [
        frame(1, 'done', { kind: 'scripts' }),
        frame(2, 'now', { kind: 'extra', current: true }),
        frame(3, 'wait', { kind: 'scripts' }),
      ],
      { summaries: { scripts: ['проверку прошли 2 из 2'] } },
    );
    expect(within(li[0]!).getByTestId('frame-summary')).toHaveTextContent('проверку прошли');
    expect(within(li[2]!).queryByTestId('frame-summary')).not.toBeInTheDocument();
    expect(li.map((x) => x.dataset.link)).toEqual(['passed', 'ahead', undefined]);
  });

  it('пропущенный раунд добора после судьи итог «Добора» не забирает (CC-0150)', () => {
    const li = strip(
      [
        frame(1, 'done', { kind: 'extra' }),
        frame(2, 'done', { kind: 'judge' }),
        frame(3, 'unneeded', { kind: 'extra', judge: true, title: 'Добор после судьи' }),
        frame(4, 'now', { kind: 'accept', current: true }),
      ],
      { summaries: { extra: ['2 темы на замену'] } },
    );
    expect(within(li[0]!).getByTestId('frame-summary')).toHaveTextContent('2 темы на замену');
    expect(within(li[2]!).queryByTestId('frame-summary')).not.toBeInTheDocument();
  });

  it('прошедший раунд добора после судьи итог «Добора» берёт: он последний запускавшийся', () => {
    const ran = strip(
      [frame(1, 'done', { kind: 'extra' }), frame(2, 'done', { kind: 'extra', judge: true })],
      { summaries: { extra: ['2 темы на замену'] } },
    );
    expect(within(ran[1]!).getByTestId('frame-summary')).toHaveTextContent('2 темы на замену');
  });

  it('идёт добор после судьи: подсказка про отказ судьи кадра, без «первого прохода»', async () => {
    const user = userEvent.setup();
    const li = strip([
      frame(1, 'done', { kind: 'judge' }),
      frame(2, 'now', {
        kind: 'extra',
        judge: true,
        current: true,
        returned: true,
        done: 2,
        total: 7,
      }),
    ]);
    expect(within(li[1]!).getByTestId('frame-small')).toHaveTextContent('добор · идёт');
    expect(within(li[1]!).queryByTestId('frame-first')).not.toBeInTheDocument();
    await user.tab();
    const tip = await screen.findByRole('tooltip');
    expect(tip).toHaveTextContent('только когда судья кадра отказал роликам');
  });

  it('«первый проход готов» и запасные шаги — во второй колонке, под подписью (телефон)', () => {
    const li = strip([
      frame(1, 'now', { kind: 'extra', current: true, returned: true, done: 1, total: 2 }),
      frame(2, 'done', { kind: 'extra', done: 2, total: 4, spare: 2 }),
    ]);
    expect(within(li[0]!).getByTestId('frame-first')).toHaveClass('col-start-2');
    expect(within(li[1]!).getByTestId('frame-spare')).toHaveClass('col-start-2');
  });
});

describe('кинолента: проверке кадров нечего проверять (CC-0111)', () => {
  it('один готовый кадр «нечего проверять» — не пропуск и не ошибка', () => {
    const [judge] = strip([
      frame(7, 'done', {
        kind: 'judge',
        title: 'Проверка кадров',
        stages: ['frame-judge-empty', 'frame-judge'],
        done: 2,
        total: 2,
        empty: true,
      }),
    ]);
    expect(judge).toHaveAttribute('data-state', 'done');
    expect(judge).toHaveAttribute('data-empty', 'true');
    expect(within(judge!).getByTestId('frame-small')).toHaveTextContent('нечего проверять');
    expect(judge).not.toHaveTextContent(/frame-judge|пропущ|ошибка/);
  });
});
