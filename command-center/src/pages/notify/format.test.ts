// CC-0170: вид уведомления hold_released — подпись по-русски, как у соседних видов.
import { KINDS } from '@/mocks/notifyData';

import { eventBody, KIND, kindLabel } from './format';

describe('виды уведомлений', () => {
  it('hold_released — «холд снят», с пояснением', () => {
    expect(kindLabel('hold_released')).toBe('холд снят');
    expect(KIND.hold_released?.tip).toMatch(/сцене, которой нет в ролике/);
  });
  it('у каждого вида журнала фабрики есть подпись', () => {
    expect(KINDS.filter((k) => !KIND[k])).toEqual([]);
  });
});

describe('CC-0188: приёмка, «залито в Studio», локальный upload, текст для Telegram', () => {
  it('accepted и uploaded — подписи с пояснением', () => {
    expect(kindLabel('accepted')).toBe('Приёмка');
    expect(KIND.accepted?.tip).toMatch(/приёмки батча/);
    expect(kindLabel('uploaded')).toBe('Залито в Studio');
    expect(KIND.uploaded?.tip).toMatch(/дат/);
  });
  it('upload — только на этой машине, в Telegram не уходит', () => {
    expect(kindLabel('upload')).toBe('файл для Studio');
    expect(KIND.upload?.tip).toMatch(/только на этой машине/);
    expect(KIND.upload?.tip).toMatch(/в Telegram не уходит/);
  });
  it('body — только непустая строка', () => {
    expect(eventBody({ body: 'а\nб' })).toBe('а\nб');
    expect(eventBody({})).toBeNull();
    expect(eventBody({ body: null })).toBeNull();
    expect(eventBody({ body: 42 })).toBeNull();
    expect(eventBody({ body: ['а', 'б'] })).toBeNull();
    expect(eventBody({ body: { text: 'а' } })).toBeNull();
    expect(eventBody({ body: '  \n ' })).toBeNull();
  });
});
