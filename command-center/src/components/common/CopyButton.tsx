// «Скопировать»: значение — в буфер обмена, подтверждение — тостом и словом на самой кнопке.
// Обычная кнопка: доступна с клавиатуры (Tab, Enter/пробел). Буфер недоступен (не HTTPS и не
// localhost, запрет браузера) — запасной путь через выделение; не вышло и так — тост об этом.
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { copyText } from '@/lib/clipboard';

import { CheckIcon, CopyIcon } from './icons';
import { Tip } from './Tip';
import { useToast } from './useToast';

export function CopyButton({
  value,
  what,
  tip,
  'data-testid': testId,
}: {
  value: string;
  /** Что копируется — для тоста и подписи кнопки: «Название», «Теги». */
  what: string;
  tip?: string;
  'data-testid'?: string;
}) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return undefined;
    const t = setTimeout(() => setDone(false), 1500);
    return () => clearTimeout(t);
  }, [done]);
  const button = (
    <Button
      size="sm"
      variant="ghost"
      aria-label={`Скопировать: ${what}`}
      data-testid={testId}
      data-copied={done ? '1' : undefined}
      onClick={() => {
        void copyText(value).then((ok) => {
          if (ok) {
            setDone(true);
            toast(`Скопировано: ${what}`);
          } else {
            toast(`Не скопировалось: ${what}. Выделите текст и скопируйте вручную`, 'danger');
          }
        });
      }}
    >
      {done ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
      <span>{done ? 'Скопировано' : 'Скопировать'}</span>
    </Button>
  );
  return <Tip content={tip ?? `Скопировать «${what}» в буфер обмена`}>{button}</Tip>;
}
