import type { Area } from '@/app/areas';
import { Soon } from '@/components/common/States';

/** Заглушка раздела, которого ещё нет: таб остаётся на месте, навигация не меняется. */
export function Placeholder({ area }: { area: Area }) {
  return (
    <Soon page version={area.soon ?? '—'} title={area.title}>
      {area.tip}. Раздел появится в версии {area.soon} центра. Пока он недоступен, таб остаётся на
      месте, чтобы навигация не менялась.
    </Soon>
  );
}
