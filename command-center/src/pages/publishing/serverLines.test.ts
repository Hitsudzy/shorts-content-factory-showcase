// Строки фабрики словами (CC-0180): `STUDIO`, `HORIZON`, `STALE` — русским текстом по приставке,
// неизвестная приставка — как есть; отказы плана не повторяются над правками.
import { moveRefusalText } from './moveWords';
import { headWhy, lineKind, lineWords, ownRefusals } from './serverLines';
import { skipReasonText } from './stashWords';

describe('lineWords', () => {
  it('снятие: «Ограниченный доступ», центр Studio не проверяет', () => {
    const w = lineWords(
      "STUDIO s (id): in Studio it must be taken off its schedule - «Ограниченный доступ», no publication date - by a human or the center on the user's word; this tool writes the journal and the копилка only (CF-0918)",
    );
    expect(w.kind).toBe('studio');
    expect(w.text).toContain('Ограниченный доступ');
    expect(w.text).toContain('не проверяет');
    expect(w.text).not.toMatch(/[A-Z]{4}/);
  });

  it('возврат из запаса: день из строки и «новой загрузки нет»; без дня — его новый слот', () => {
    const on = lineWords(
      "STUDIO s (id) comes back from the копилка: in Studio set «Отложенная публикация» on 2026-10-14 01:00 МСК (it stands at «Ограниченный доступ») - a human or the center on the user's word; no new upload (CF-0918)",
    );
    expect(on.text).toContain('2026-10-14 01:00 МСК');
    expect(on.text).toContain('новой загрузки нет');
    const slot = lineWords(
      'STUDIO s (id) comes back from the копилка: in Studio set «Отложенная публикация» on its slot (it stands at «Ограниченный доступ») - no new upload (CF-0918)',
    );
    expect(slot.text).toContain('его новый слот');
  });

  it('перенос ролика в Studio: что там должно стоять', () => {
    const w = lineWords(
      "STUDIO s (id) is in Studio: the date there is set by a human or the center on the user's word - this tool writes the journal only (it must read 2026-10-15 01:00 МСК in Studio)",
    );
    expect(w.text).toContain('2026-10-15 01:00 МСК');
    expect(lineWords('STUDIO s (id): something new').text).toContain('дату там ставите вы');
  });

  it('горизонт и устаревшая новость', () => {
    const h = lineWords(
      "HORIZON s: 2026-10-20 01:00 МСК is past the channel's horizon (3 дн., до 2026-10-13 МСК; CF-0918) - the day is the user's, written as named",
    );
    expect(h.kind).toBe('horizon');
    expect(h.text).toContain('3 дн., до 13.10');
    expect(lineWords('HORIZON s: a changed sentence').text).toContain('дальше горизонта');
    const s = lineWords(
      'STALE s: новость устарела (25 дн., CF-0741) - ставится, потому что названа руками (CF-0918)',
    );
    expect(s.kind).toBe('stale');
    expect(s.text).toContain('25 дн.');
    expect(s.text).not.toContain('CF-');
  });

  it('другая приставка — как есть', () => {
    expect(lineKind('WINDOW s: late')).toBe('other');
    expect(lineWords('WINDOW s: late').text).toBe('WINDOW s: late');
    expect(lineKind('STUDIOUS line')).toBe('other');
  });
});

describe('отказы и причины', () => {
  it('сообщение фабрики по-русски, слова по коду, запасной текст на неизвестный код', () => {
    expect(moveRefusalText({ code: 'in_reserve', message: 'Уже в запасе.' })).toBe('Уже в запасе.');
    expect(moveRefusalText({ code: 'reserve_taken', message: 'reserve is taken' })).toContain(
      'занято',
    );
    expect(moveRefusalText({ code: 'not_in_studio', message: '' })).toContain(
      'Ролика нет в Studio',
    );
    expect(moveRefusalText({ code: 'brand_new', message: 'nope' })).toContain('Фабрика отказала');
  });

  it('причины пропуска: все известные коды и запасной текст', () => {
    for (const code of [
      'stale_news',
      'beyond_horizon',
      'no_card',
      'card_building',
      'card_not_ready',
      'note_differs',
    ])
      expect(skipReasonText(code, 'english')).toMatch(/[а-я]/i);
    expect(skipReasonText('no_card', 'Своими словами.')).toBe('Своими словами.');
    expect(skipReasonText('brand_new')).toContain('ждёт в копилке');
    // Сообщение фабрики про устаревшую новость называет force — на виду слова центра.
    expect(skipReasonText('stale_news', 'Новость устарела - авто-раскладкой с force.')).toBe(
      'Новость устарела, можно поставить вручную.',
    );
  });

  it('`refusals` плана с отказами правок: над правками только свои, `why` не повторяется', () => {
    const atItem = { code: 'in_reserve', slug: 'a', message: 'Снят.', line: '' };
    const own = { code: 'batch_open', slug: null, message: 'Идёт батч.', line: '' };
    const items = [{ slug: 'a', refusals: [atItem] }];
    expect(ownRefusals({ refusals: [atItem, own], items })).toEqual([own]);
    expect(headWhy({ why: 'Снят.', refusals: [atItem], items })).toBeNull();
    expect(headWhy({ why: 'Идёт батч.', refusals: [own], items: [] })).toBeNull();
    expect(headWhy({ why: 'Разложить можно 1 из 2', refusals: [], items })).toBe(
      'Разложить можно 1 из 2',
    );
  });
});
