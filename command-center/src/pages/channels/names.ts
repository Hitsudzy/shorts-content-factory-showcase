// Имена каналов для человека — без кода формы, их берёт и главная.

export const channelName = (c: { id: string; display_name: string | null }) =>
  c.display_name ?? c.id;

/** «1 канал», «3 канала», «5 каналов». */
export function channelsCount(n: number): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return `${n} канал`;
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return `${n} канала`;
  return `${n} каналов`;
}
