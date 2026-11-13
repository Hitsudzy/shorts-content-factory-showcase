// CC-0170: сцены флага чувствительности словами — «сцены s2, s3», «вся тема», ничего для null.
import { scenesText, shortScene } from './sensitivityScenes';

const T = 'lf-2026-10-21-006';

describe('shortScene: id сцены без префикса темы (как flagged_short у API)', () => {
  it('снимает префикс темы', () => {
    expect(shortScene(`${T}-s2`, T)).toBe('s2');
  });
  it('чужой префикс и голый префикс — как есть', () => {
    expect(shortScene('other-s2', T)).toBe('other-s2');
    expect(shortScene(`${T}-`, T)).toBe(`${T}-`);
  });
  it('без темы — хвост «-s2», если он есть', () => {
    expect(shortScene(`${T}-s3`, null)).toBe('s3');
    expect(shortScene('sc2', null)).toBe('sc2');
  });
});

describe('scenesText', () => {
  it('null и undefined — ничего', () => {
    expect(scenesText(null, T)).toBeNull();
    expect(scenesText(undefined, T)).toBeNull();
  });
  it('whole_topic и пустой список — «вся тема»', () => {
    expect(scenesText('whole_topic', T)).toBe('вся тема');
    expect(scenesText([], T)).toBe('вся тема');
  });
  it('одна сцена — «сцена s2», несколько — «сцены s2, s3»', () => {
    expect(scenesText([`${T}-s2`], T)).toBe('сцена s2');
    expect(scenesText([`${T}-s2`, `${T}-s3`], T)).toBe('сцены s2, s3');
  });
});
