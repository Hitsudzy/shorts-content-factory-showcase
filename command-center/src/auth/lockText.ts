// Подписи блокировки входа (CC-0037): после нескольких неверных паролей сервер ждёт `retry_after`.

/** «4:05» — сколько ждать до следующей попытки. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** «Слишком много попыток. Попробуйте через N мин» — N округляется вверх, минимум 1;
 * «через», число и «мин» — через неразрывные пробелы, чтобы не разъезжались по строкам. */
export function lockedText(seconds: number): string {
  return `Слишком много попыток. Попробуйте через\u00a0${Math.max(1, Math.ceil(seconds / 60))}\u00a0мин`;
}
