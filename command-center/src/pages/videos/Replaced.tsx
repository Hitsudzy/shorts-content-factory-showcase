// Ролик, заменённый принятой пересборкой (CC-0088): у первой версии нет строки журнала —
// отказ оформили пересборкой, — а пересборку вы приняли и, бывает, уже залили. Экран говорит
// это прямо: «Заменён пересборкой … — принят, залит …» со ссылкой на пересборку; вердикт первой
// версии не предлагается (он — под «Всё равно дать вердикт этой версии», с предупреждением).
import { Link } from 'react-router';

import { useReplacementUpload } from '@/api/replacementUpload';
import type { Replacement } from '@/api/videos';
import { More } from '@/components/common/More';
import { dateTimeMsk } from '@/pages/batches/format';
import { batchIdIso } from '@/pages/batches/going';

import { shortDay } from './format';

const whenOf = (batchId: string) => dateTimeMsk(batchIdIso(batchId)) ?? batchId;

/** Ссылка на ролик на YouTube по номеру (номер — то, что пишет журнал загрузок). */
const shortsUrl = (id: string) => `https://youtube.com/shorts/${encodeURIComponent(id)}`;

export function ReplacedNotice({
  replacement,
  channel,
  to,
}: {
  replacement: Replacement;
  channel: string | null | undefined;
  /** Куда ведёт «пересборкой …»: версия ролика в пересборке. */
  to: { search: string };
}) {
  const up = useReplacementUpload(channel, replacement);
  const a = replacement.video.acceptance;
  return (
    <div
      data-testid="replaced"
      data-rebuild={replacement.batch}
      data-video-id={up.upload?.videoId}
      className="grid gap-1.5 rounded-sm border border-[color-mix(in_srgb,var(--success)_40%,var(--border))] bg-[color-mix(in_srgb,var(--success)_7%,var(--card))] p-3 text-[13px]"
    >
      <p className="m-0" data-testid="replaced-line">
        <strong className="font-semibold">
          Заменён{' '}
          <Link
            to={to}
            data-testid="replaced-link"
            className="text-primary-text underline underline-offset-4"
          >
            пересборкой {whenOf(replacement.batch_id)}
          </Link>
        </strong>{' '}
        — принят
        {up.upload ? (
          <>
            , залит{' '}
            <a
              href={shortsUrl(up.upload.videoId)}
              target="_blank"
              rel="noreferrer"
              data-testid="replaced-upload"
              className="font-mono text-primary-text underline underline-offset-4"
            >
              {up.upload.videoId}
            </a>{' '}
            (публикация {shortDay(up.upload.day)})
          </>
        ) : null}
        .
      </p>
      <p className="m-0 text-muted-foreground">
        Вердикта у этой версии нет — её заменила пересборка, и её вы уже приняли
        {up.upload
          ? ' и залили в Studio'
          : up.pending
            ? ''
            : up.failed
              ? '; ленту публикации не прочитать — залита ли она, здесь не сказать'
              : '; в ленте публикации её загрузки пока не видно'}
        . Решения эта версия не ждёт.
      </p>
      <More className="mt-0">
        <span>пересборка: {replacement.batch}</span>
        {a ? <span>запись пересборки: {a.entry_id}</span> : null}
        {up.upload ? <span>журнал загрузок: uploads.json:{up.upload.videoId}</span> : null}
      </More>
    </div>
  );
}
