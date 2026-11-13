// Имена каналов для экрана «Батчи»: API расписания говорит id, человеку — название.
import { useChannels } from '@/api/channels';
import { humanDashes } from '@/api/humanText';

import { batchesInText } from './going';

/** Имена каналов для человека по их id (из списка каналов); пока не пришёл — сам id. */
export function useChannelNames(): (id: string | null | undefined) => string {
  const list = useChannels();
  return (id) => {
    if (!id) return '—';
    const c = list.data?.find((x) => x.id === id || x.former_ids.includes(id));
    return c?.display_name ?? id;
  };
}

type Named = { id: string; former_ids: readonly string[]; display_name?: string | null };

/**
 * Текст фабрики для человека: id каналов («канал example-film есть», «example-film: лента на
 * 3 дн.») — их названиями, батчи («example-film 2026-10-09T2305Z») — каналом и временем по МСК.
 * Только целые слова: в путях и именах файлов id не трогаем.
 */
export function channelsInText(text: string, channels: readonly Named[]): string {
  const name = (id: string) =>
    channels.find((c) => c.id === id || c.former_ids.includes(id))?.display_name || id;
  let out = batchesInText(text, name);
  for (const c of channels) {
    for (const id of [c.id, ...c.former_ids]) {
      if (!id || !c.display_name || id === c.display_name) continue;
      const safe = id.replace(/[.*+?^$()|[\]\\{}]/g, '\\$&');
      const re = new RegExp(`(?<![\\w./-])${safe}(?![\\w/-]|\\.\\w)`, 'g');
      out = out.replace(re, c.display_name);
    }
  }
  return out;
}

/**
 * Строка фабрики для экрана: `channelsInText` по списку каналов (пока список не пришёл — как
 * есть, батчи — уже) и « - » — тире (CC-0131: общий проход для всех строк фабрики на экране).
 */
export function useChannelText(): (text: string) => string {
  const list = useChannels();
  return (text) => humanDashes(channelsInText(text, list.data ?? []));
}
