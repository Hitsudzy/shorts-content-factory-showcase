// Лицо канала: аватар и метка состояния. Лёгкий модуль без кода формы (jsonc-parser) —
// его берёт и главная (карточка «Каналы»), и экран каналов.
import type { ChannelSummary } from '@/api/channels';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';

// Цвета аватаров — из макета «Кинозал» (`.ava`, `.ava.tech`, `.ava.sci`).
const AVA: Record<string, string> = {
  'example-film': 'bg-[#280e14] border-[#654126]',
  'example-tech': 'bg-[#0c213c] border-[#32588b]',
  'example-science': 'bg-[#092319] border-[#7c855d]',
};

export function Avatar({ id, name, className }: { id: string; name: string; className?: string }) {
  const letter =
    name
      .replace(/^Example/i, '')
      .charAt(0)
      .toUpperCase() || name.charAt(0);
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-[34px] shrink-0 place-items-center rounded-full border font-display text-[13px] text-white',
        AVA[id] ?? 'border-border bg-muted',
        className,
      )}
    >
      {letter}
    </span>
  );
}

/** Состояние канала одной меткой: сломан, идёт батч, конвейера нет, в работе. */
export function ChannelState({
  c,
}: {
  c: Pick<ChannelSummary, 'error' | 'locked' | 'no_pipeline'>;
}) {
  if (c.error)
    return (
      <StatusBadge tone="danger" tip="Конфиг канала не читается — фабрика не сможет с ним работать">
        конфиг сломан
      </StatusBadge>
    );
  if (c.locked)
    return (
      <StatusBadge tone="live" tip="Сейчас идёт батч канала; пока он не закончится, правка закрыта">
        идёт батч
      </StatusBadge>
    );
  if (c.no_pipeline)
    return (
      <StatusBadge tone="idle" tip={`Канал оформлен, но ${c.no_pipeline}`}>
        готовится
      </StatusBadge>
    );
  return (
    <StatusBadge tone="ok" tip="У канала есть конвейер: фабрика делает для него батчи">
      в работе
    </StatusBadge>
  );
}
