// «Уведомления и напоминания» (CC-0027, API — CC-0026, договор 0.27.0): напоминания (очередь
// фабрики и «поставить напоминание» — план и «да»), каналы уведомлений (сухая проверка: что
// включено и что уходит с машины) и журнал уведомлений с фильтром по виду и каналу. Отменить
// напоминание из центра пока нельзя — ждёт фабрики (CC-0081).
import { Check } from './Check';
import { Journal } from './Journal';
import { Reminders } from './Reminders';

export function Notify() {
  return (
    <>
      <div>
        <div className="eyebrow">Журнал, напоминания, каналы доставки</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Уведомления и напоминания
        </h1>
      </div>
      <div className="grid items-start gap-gap lg:grid-cols-2">
        <Reminders />
        <Check />
      </div>
      <Journal />
    </>
  );
}
