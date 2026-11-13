// Просмотр мема (CC-0025): картинка крупно (GIF играет, у вырезанного — «целиком / вырезка»),
// описание, метки, откуда мем (ссылка — в новой вкладке), заметки фабрики и отметки: «оставить»,
// «убрать», «можно вырезать» и своя заметка. Отметки — черновик центра; в фабрику они уходят по
// «Сохранить отметки». Кто и когда ставил отметку из центра — под «подробнее».
import { useId, useState } from 'react';

import { nbDashes } from '@/api/humanText';
import type { MemeEntry, SavedMark } from '@/api/memes';
import { NO_REASON_TEXT } from '@/api/reasonRu';
import { useWrites } from '@/api/writes';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';
import { inputBase } from '@/pages/channels/styles';

import { cutOf, stateOf, type Mark } from './draft';
import { checker } from './Grid';
import { clipText, memeName, STATE } from './format';
import { afterDash } from './jobs';

export const KEYS_TIP =
  'Клавиши: → и ← — следующий и предыдущий мем, K — оставить, D — убрать (и сразу к следующему), C — можно вырезать, Esc — закрыть просмотр.';

const VIA: Record<string, string> = { center: 'из центра', desk: 'на столе в терминале' };

export function Viewer({
  entry,
  mark,
  saved,
  changed,
  position,
  onVerdict,
  onCut,
  onNote,
  onPrev,
  onNext,
  onClose,
  onTag,
}: {
  entry: MemeEntry;
  mark: Mark | undefined;
  /** Отметка, как она сохранена в фабрике (с «кто и когда»). */
  saved: SavedMark | undefined;
  changed: boolean;
  position: string | null;
  onVerdict: (v: 'keep' | 'drop') => void;
  onCut: () => void;
  onNote: (text: string) => void;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
  onClose: () => void;
  onTag: (tag: string) => void;
}) {
  const ids = { note: useId(), title: useId() };
  const writes = useWrites();
  const [showCut, setShowCut] = useState(false);
  const state = stateOf(entry, mark);
  const s = STATE[state];
  const cut = cutOf(entry, mark);
  const cutChanged = !entry.gif && cut !== entry.cutout;
  const clip = clipText(entry.clip);
  const media = showCut && entry.urls.cut ? entry.urls.cut : entry.urls.file;
  const when = dateTimeMsk(saved?.marked_at);
  return (
    <section
      aria-labelledby={ids.title}
      data-testid="meme-viewer"
      data-id={entry.id}
      className="grid min-w-0 gap-3 rounded-lg border bg-card p-3 sm:p-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="eyebrow">
            Мем{position ? ` · ${position}` : ''}
            {entry.gif ? ' · гифка' : ''}
          </div>
          <h2
            id={ids.title}
            className="mt-0.5 text-[17px] font-semibold text-balance [overflow-wrap:anywhere]"
          >
            {memeName(entry.id)}
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            onClick={onPrev ?? undefined}
            disabled={!onPrev}
            aria-label="Предыдущий мем"
            data-testid="meme-prev"
          >
            ←
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={onNext ?? undefined}
            disabled={!onNext}
            aria-label="Следующий мем"
            data-testid="meme-next"
          >
            →
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} data-testid="meme-close">
            Закрыть
          </Button>
        </div>
      </div>

      <div
        className={cn(
          'grid max-h-[min(60vh,420px)] min-h-40 place-items-center overflow-hidden rounded-sm bg-muted',
          showCut && checker,
        )}
      >
        <img
          key={media}
          src={media}
          alt={entry.description ?? memeName(entry.id)}
          data-testid="meme-media"
          className="max-h-[min(60vh,420px)] max-w-full object-contain"
        />
      </div>
      {entry.urls.cut ? (
        <div className="flex gap-1.5" role="group" aria-label="Что показать">
          <Button
            size="sm"
            variant={showCut ? 'ghost' : 'outline'}
            aria-pressed={!showCut}
            onClick={() => setShowCut(false)}
          >
            Целиком
          </Button>
          <Button
            size="sm"
            variant={showCut ? 'outline' : 'ghost'}
            aria-pressed={showCut}
            onClick={() => setShowCut(true)}
            data-testid="meme-show-cut"
          >
            Вырезка
          </Button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={s.tone} tip={s.tip}>
          {s.label}
        </StatusBadge>
        {changed ? (
          <span className="text-xs text-primary-text" data-testid="viewer-unsaved">
            не сохранено
          </span>
        ) : null}
      </div>

      <div className="grid gap-2" data-testid="meme-marks">
        <div className="flex flex-wrap gap-2">
          <WriteButton
            size="sm"
            variant={mark?.v === 'keep' ? 'default' : 'outline'}
            aria-pressed={mark?.v === 'keep'}
            onClick={() => onVerdict('keep')}
            data-testid="mark-keep"
            tip={mark?.v === 'keep' ? 'Ещё раз — снять решение' : 'Оставить мем в библиотеке (K)'}
          >
            Оставить
          </WriteButton>
          <WriteButton
            size="sm"
            variant={mark?.v === 'drop' ? 'destructive' : 'outline'}
            aria-pressed={mark?.v === 'drop'}
            onClick={() => onVerdict('drop')}
            data-testid="mark-drop"
            className={cn(mark?.v === 'drop' && 'border-danger bg-danger text-white')}
            tip={mark?.v === 'drop' ? 'Ещё раз — снять решение' : 'Убрать мем из библиотеки (D)'}
          >
            Убрать
          </WriteButton>
          <WriteButton
            size="sm"
            variant="outline"
            role="switch"
            aria-checked={cut}
            onClick={onCut}
            data-testid="mark-cut"
            why={entry.gif ? 'Гифка идёт только целиком — вырезать её нельзя' : undefined}
            tip="Можно ли вырезать мем по контуру и ставить без фона (C)"
          >
            <span
              aria-hidden
              className={cn(
                'grid size-3.5 place-items-center rounded-[3px] border text-[10px] leading-none',
                cut && 'border-primary bg-primary text-primary-foreground',
              )}
            >
              {cut ? '✓' : ''}
            </span>
            Можно вырезать
          </WriteButton>
        </div>
        {cutChanged ? (
          <p className="m-0 text-xs text-muted-foreground" data-testid="cut-will-change">
            {cut
              ? 'Станет «можно вырезать», когда вы примените разбор.'
              : 'Перестанет быть «можно вырезать», когда вы примените разбор; готовая вырезка удалится.'}
          </p>
        ) : null}
        {entry.cut_refused ? (
          <div className="grid gap-0.5 text-xs" data-testid="cut-refused">
            <span className="text-warning">
              Вырезка не прошла проверку фабрики — мем пойдёт в ролик целиком.
            </span>
            <span className="[overflow-wrap:anywhere]" data-testid="cut-refused-why">
              Причина:{' '}
              {/[а-яё]/i.test(entry.cut_refused)
                ? nbDashes(afterDash(entry.cut_refused))
                : NO_REASON_TEXT}
            </span>
            <More className="mt-0">
              <span>{entry.cut_refused}</span>
              {entry.cut_refused_en ? <span>{entry.cut_refused_en}</span> : null}
            </More>
          </div>
        ) : null}
        <label htmlFor={ids.note} className="grid gap-1">
          <span className="text-xs text-muted-foreground">Ваша заметка</span>
          <textarea
            id={ids.note}
            data-testid="mark-note"
            rows={2}
            value={mark?.note ?? ''}
            readOnly={!writes.allowed}
            onChange={(e) => onNote(e.target.value)}
            placeholder="Например: где этот мем к месту"
            className={cn(inputBase, 'h-auto min-h-14 py-2')}
          />
        </label>
      </div>

      <div className="grid gap-2 text-[13px]">
        {entry.description ? (
          <p className="m-0 leading-[1.45]" data-testid="meme-description">
            {entry.description}
          </p>
        ) : null}
        {entry.tags?.length ? (
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Метки">
            {entry.tags.map((t) => (
              <li key={t}>
                <Tip content="Показать мемы с этой меткой">
                  <button
                    type="button"
                    onClick={() => onTag(t)}
                    className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground hover:border-muted-foreground"
                  >
                    {t}
                  </button>
                </Tip>
              </li>
            ))}
          </ul>
        ) : null}
        {entry.source_url ? (
          <p className="m-0 text-xs">
            <a
              href={entry.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-text underline underline-offset-4"
              data-testid="meme-source"
            >
              {entry.gif ? 'Видео, из которого гифка' : 'Откуда мем'}
            </a>
            {clip ? <span className="text-muted-foreground"> · {clip}</span> : null}
          </p>
        ) : null}
        {entry.notes ? (
          <p className="m-0 text-xs text-muted-foreground" data-testid="meme-notes">
            Заметка фабрики: {entry.notes}
          </p>
        ) : null}
        <p className="m-0 hidden text-[11px] text-muted-foreground sm:block">{KEYS_TIP}</p>
      </div>

      <More>
        <span>мем: {entry.id}</span>
        <span>файл: {entry.file}</span>
        {entry.cut_file ? <span>вырезка: {entry.cut_file}</span> : null}
        {entry.review ? <span>review: {entry.review}</span> : null}
        {saved?.marked_by || saved?.marked_at || saved?.via ? (
          <span data-testid="marked-by">
            отметку поставил: {saved.marked_by ?? '—'}
            {saved.via ? ` ${VIA[saved.via] ?? `(${saved.via})`}` : ''}
            {when ? `, ${when}` : ''}
          </span>
        ) : null}
        {entry.clip ? <span>clip: {JSON.stringify(entry.clip)}</span> : null}
        {entry.cutout_asset ? (
          <span>cutout_asset: {JSON.stringify(entry.cutout_asset)}</span>
        ) : null}
      </More>
    </section>
  );
}
