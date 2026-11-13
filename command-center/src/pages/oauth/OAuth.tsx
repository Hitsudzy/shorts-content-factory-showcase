// «Токены, OAuth и данные API» (CC-0029, API — CC-0028, договор 0.28.0): токен YouTube без
// значения (состояние, срок, разрешения, команда входа — вход ваш), отзыв доступа (сухой прогон и
// «Отозвать доступ…» — план и «да», CC-0087) и данные API: что хранится по каналам, что удалит
// авто-прогон и «Удалить по сроку…», удаление по вашей просьбе — план и «да».
import { ApiData } from './ApiData';
import { Revoke } from './Revoke';
import { Token } from './Token';

export function OAuth() {
  return (
    <>
      <div>
        <div className="eyebrow">Токен YouTube, разрешения, данные из YouTube API</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Токены, OAuth и данные API
        </h1>
      </div>
      <div className="grid items-start gap-gap lg:grid-cols-2">
        <Token />
        <Revoke />
      </div>
      <ApiData />
    </>
  );
}
