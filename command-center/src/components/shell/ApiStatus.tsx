import { CONTRACT } from '@/api/contract.gen';
import { useHealth, useVersion } from '@/api/hooks';
import { StatusPill, type Tone } from '@/components/common/Status';
import { STALE_TIP } from '@/pages/versions/apiProcessText';

/** Связь с API фабрики — пилюля в шапке. Номера контракта — на главной, под «подробнее». */
export function ApiStatus({ className }: { className?: string }) {
  const health = useHealth();
  // CC-0155: процесс API отстал от кода фабрики — тот же тон «внимание», что у другого договора.
  const stale = useVersion().data?.stale === true;

  let tone: Tone = 'idle';
  let text = 'Проверяю связь…';
  let tip = 'Центр спрашивает API фабрики, жив ли он';
  if (health.isSuccess) {
    // Сервер отдаёт info.version своего контракта; центр собран под CONTRACT.version.
    if (health.data.api === CONTRACT.version) {
      tone = 'ok';
      text = 'Фабрика на связи';
      tip = 'API фабрики отвечает, договор API тот же, под который собран центр';
      if (stale) {
        tone = 'warn';
        text = 'API на старом коде';
        tip = STALE_TIP;
      }
    } else {
      tone = 'warn';
      text = 'Другой договор API';
      tip =
        'API фабрики отвечает, но по другой версии договора, чем собран центр: часть экранов может не работать. Пересоберите центр';
    }
  } else if (health.isError) {
    tone = 'danger';
    text = 'Нет связи с фабрикой';
    tip = 'API фабрики не отвечает. Данные на экранах могут быть устаревшими';
  }

  return (
    <StatusPill tone={tone} tip={tip} data-testid="api-status" className={className}>
      {text}
    </StatusPill>
  );
}
