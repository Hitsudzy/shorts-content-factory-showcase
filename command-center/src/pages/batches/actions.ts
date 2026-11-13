// Слова и числа действий экрана «Батчи» (CC-0052): отсчёт жизни токена подтверждения, строка
// `kill -9` из ответа фабрики (только текстом — выполнять её центр не предлагает), имена
// проверок запуска для человека.

/** Секунд до конца жизни токена (не меньше 0); null — срока нет. */
export function secondsLeft(deadline: number | null, now: number): number | null {
  if (deadline == null) return null;
  return Math.max(0, Math.ceil((deadline - now) / 1000));
}

/** «1:54», «0:07» — отсчёт на кнопке подтверждения. */
export function countdownText(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

/**
 * Команда `kill -9 -<pgid>` из строки фабрики: фабрика сама SIGKILL не шлёт и отдаёт её
 * человеку. null — команды в строке нет.
 */
export function killLine(reason: string | null | undefined): string | null {
  const m = reason?.match(/kill -9 -?\d+/);
  return m ? m[0] : null;
}

/**
 * Отказ остановки своими словами (CC-0131): «… pid N не умер за 30 с после SIGTERM … SIGKILL не
 * послан - решить руками: kill -9 -N» → по-русски, без pid и сигналов. Строка фабрики — под
 * «Подробнее», команда — отдельным полем (`KillCommand`). null — строка не такая.
 */
export function stopReasonText(reason: string | null | undefined): string | null {
  const m = /не умер за (\d+) с после SIGTERM/.exec(reason ?? '');
  if (!m) return null;
  const who = /^\s*шаг\s/i.test(reason ?? '') ? 'Шаг' : 'Исполнитель';
  return `${who} не остановился за ${m[1]} с после просьбы завершиться. Принудительно фабрика его не останавливает — решите вручную, команда ниже.`;
}

/** Проверки `launch_check` фабрики — по-русски (строка `line` фабрики — рядом, как есть). */
export const GUARD_LABEL: Record<string, string> = {
  channel: 'Канал',
  run_plan: 'План прогона',
  open: 'Открытые батчи',
  today: 'Батч сегодня',
  pause: 'Пауза',
};

export const guardLabel = (name: string) => GUARD_LABEL[name] ?? name;

/**
 * Подпись «да» с отсчётом жизни токена: «Запустить · 1:54»; `word` называет отсчёт словами:
 * «Разложить · план ещё 1:54» (это не время публикации).
 */
export function confirmText(
  label: string,
  flow: { plan: { ok: boolean } | null; left: number | null },
  word?: string,
): string {
  if (!flow.plan?.ok || flow.left == null) return label;
  return `${label} · ${word ? `${word} ` : ''}${countdownText(flow.left)}`;
}

/**
 * Что с батчем можно сделать по его статусу (окончательно решает проверка фабрики). `gone` —
 * исполнитель батча не отвечает (CC-0094): остановить нечего, только продолжить.
 */
export function controlsOf(b: { status?: string | null; fresh?: boolean | null }, gone = false) {
  const s = b.status ?? '';
  const stale = b.fresh === false;
  const running = s === 'running' || s === '' || s === 'new';
  return {
    stop: running && !gone,
    resume: ['stopped', 'halted', 'paused', 'failed'].includes(s) || (running && (stale || gone)),
  };
}

/**
 * Строка ответа продолжения для человека (договор 0.52+: `ResumePlan`/`ResumeResult` несут
 * `code` и `message`). `message` — по-русски из кода; у `refused` (фабрика без кода) он общий,
 * тогда — строка фабрики `reason`, в ней суть отказа.
 */
export function resumeText(r: { code?: string | null; message?: string | null; reason: string }) {
  return r.message && r.code !== 'refused' ? r.message : r.reason;
}
