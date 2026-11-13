// Вход в тур «Обучение»: кнопка в шапке (рядом с «Попросить оператора») и строка на главной
// при первом входе.
import { Card } from '@/components/common/Card';
import { CapIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

import { showInvite } from './progress';
import { useTour } from './useTour';

/** Кнопка в шапке: открывает оглавление тура. На телефоне — одна иконка. */
export function TourButton() {
  const tour = useTour();
  if (!tour) return null;
  return (
    <Tip content="Короткий тур по центру: где что лежит и как этим пользоваться">
      <Button
        aria-label="Обучение"
        data-testid="tour-open"
        data-tour="tour-button"
        onClick={tour.openMenu}
      >
        <CapIcon className="size-[17px]" />
        <span className="hidden md:inline">Обучение</span>
      </Button>
    </Tip>
  );
}

/** Строка на главной: пока тур не начинали и её не убрали. */
export function TourInvite() {
  const tour = useTour();
  if (!tour || !showInvite(tour.progress)) return null;
  return (
    <Card
      aria-labelledby="tour-invite-title"
      data-testid="tour-invite"
      className="flex flex-wrap items-center gap-x-4 gap-y-3 py-3.5"
    >
      <CapIcon className="size-6 shrink-0 text-primary-text" />
      <div className="min-w-0 flex-1">
        <h2 id="tour-invite-title" className="m-0 text-[15px] font-semibold">
          Пройдите короткое обучение
        </h2>
        <p className="m-0 text-[13px] text-muted-foreground">
          Несколько минут: центр покажет, где что лежит и как этим пользоваться. Само обучение
          ничего не нажимает и в фабрике ничего не меняет.
        </p>
      </div>
      <div className="flex w-full flex-wrap gap-2 sm:w-auto">
        <Button
          variant="default"
          className="flex-1 sm:flex-none"
          data-testid="tour-invite-start"
          onClick={() => tour.start(0)}
        >
          Начать обучение
        </Button>
        <Button
          variant="ghost"
          className="flex-1 sm:flex-none"
          data-testid="tour-invite-dismiss"
          onClick={tour.dismissInvite}
        >
          Не сейчас
        </Button>
      </div>
    </Card>
  );
}
