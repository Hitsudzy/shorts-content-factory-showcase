// «проверено N с назад» под рукой у экрана: ответ сказал `age_s` на свой момент, хук
// прибавляет, сколько прошло с ответа, и раз в несколько секунд обновляет текст.
import { useEffect, useState } from 'react';

import { freshnessText, type Freshness } from '@/api/freshness';

const TICK_MS = 5_000;

export function useFreshness(f: Freshness | null | undefined, receivedAt: number): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(t);
  }, []);
  return freshnessText(f, receivedAt ? (now - receivedAt) / 1000 : 0);
}
