// План в окне записи уже не годен: «да» получило отказ и подтверждение сгорело. Ставит
// `WriteAction` (./Writes), читают `PlanHead` и виды плана — чтобы не обещать исхода.
import { createContext, useContext } from 'react';

export const PlanFailed = createContext(false);

/** В окне `WriteAction`: «да» получило отказ, план сгорел — вид плана не обещает исхода. */
export const usePlanFailed = () => useContext(PlanFailed);
