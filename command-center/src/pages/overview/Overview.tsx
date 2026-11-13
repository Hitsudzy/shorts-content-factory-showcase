import { resetTheme } from '@/app/theme';
import { ConfirmAction } from '@/components/common/ConfirmAction';
import { Button } from '@/components/ui/button';
import { TourInvite } from '@/tour/TourButtons';

import { BatchCard } from './BatchCard';
import { ChannelsCard } from './ChannelsCard';
import { AgentsCard, FactoryCard } from './LiveCards';
import { AttentionStrip, SoonGrid } from './SoonCards';

/**
 * Главная — обзор по макету «Кинозал»: версия фабрики, связь, пины агентов, сборка центра,
 * каналы, идущий батч, ролики и вопросы, что ждут вас, и ближайшие публикации — всё живое, из API.
 */
export function Overview() {
  return (
    <>
      <h1 className="sr-only">Главная</h1>
      <TourInvite />
      <AttentionStrip />
      <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 md:grid-cols-3">
        <FactoryCard />
        <AgentsCard className="md:col-span-2" />
      </div>
      <BatchCard />
      <SoonGrid channels={<ChannelsCard />} />
      <footer className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 pt-1 pb-2 text-center text-xs text-muted-foreground">
        <span>Тема центра запоминается в этом браузере.</span>
        <ConfirmAction
          trigger={
            <Button variant="link" size="sm" className="h-auto px-0">
              Сбросить вид
            </Button>
          }
          title="Сбросить вид центра?"
          description="Тема вернётся к тёмной. Это касается только этого браузера; данные фабрики не меняются."
          confirmLabel="Сбросить"
          onConfirm={resetTheme}
        />
      </footer>
    </>
  );
}
