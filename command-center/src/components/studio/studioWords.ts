// Слова «Прочитать Studio» (CC-0120): возраст последнего чтения и тон итога сессии.
import type { StudioReadResult } from '@/api/studioRead';
import type { Tone } from '@/components/common/Status';

/** «последнее чтение 30 ч назад»; null — ни разу не читали. */
export function ageText(age: number | null | undefined): string {
  if (age == null) return 'Studio ещё ни разу не читали';
  if (age < 1) return 'последнее чтение меньше часа назад';
  if (age < 48) return `последнее чтение ${Math.round(age)} ч назад`;
  return `последнее чтение ${Math.round(age / 24)} дн назад`;
}

/** Тон итога: прочитано — спокойно, расширение и вход — сделать руками, ошибка — тревожно. */
export function outcomeTone(code: StudioReadResult['code']): Tone {
  if (code === 'read') return 'ok';
  if (code === 'error') return 'danger';
  if (code === 'running') return 'live';
  return 'warn';
}
