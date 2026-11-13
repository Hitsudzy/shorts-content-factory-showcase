// «Обслуживание и расход» (CC-0033, API — CC-0032 / CC-0104 / CC-0105, договор 0.58.0). Расход:
// токены батча по стадиям и сравнение батча вручную с батчем исполнителя — только чтение. Уборки
// и архивы: пул футажа, журналы батчей и месячный архив — план фабрики и ваше «да» (поле пустое,
// набираете вы). Пока идёт батч, фабрика уборок не делает — план так и скажет.
import { ArchiveCard, JournalsCard, NotHere, PoolCard } from './Cleanups';
import { CompareCard, UsageCard } from './Spend';

export function Maintenance() {
  return (
    <>
      <div>
        <div className="eyebrow">Расход токенов, уборки и архивы</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Обслуживание и расход
        </h1>
      </div>
      <section aria-labelledby="spend-title" className="grid gap-gap">
        <h2 id="spend-title" className="eyebrow m-0">
          Расход
        </h2>
        <div className="grid items-start gap-gap lg:grid-cols-2">
          <UsageCard />
          <CompareCard />
        </div>
      </section>
      <section aria-labelledby="cleanups-title" className="grid gap-gap">
        <h2 id="cleanups-title" className="eyebrow m-0">
          Уборки и архивы
        </h2>
        <PoolCard />
        <div className="grid items-start gap-gap lg:grid-cols-2">
          <JournalsCard />
          <ArchiveCard />
        </div>
        <NotHere />
      </section>
    </>
  );
}
