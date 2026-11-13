// CC-0144: собранный центр объявляет иконку, и сервер отдаёт каждый её файл.
import { expect, test } from './fixtures';

const ICONS = [
  { selector: 'link[rel="icon"][type="image/svg+xml"]', type: 'image/svg+xml' },
  { selector: 'link[rel="icon"][type="image/png"]', type: 'image/png' },
  { selector: 'link[rel="icon"][href$=".ico"]', type: 'image/' },
  { selector: 'link[rel="apple-touch-icon"]', type: 'image/png' },
];

test('иконка центра: ссылки в <head> и файлы отдаются', async ({ page, request }) => {
  await page.goto('/');
  for (const { selector, type } of ICONS) {
    const link = page.locator(selector);
    await expect(link).toHaveCount(1);
    const href = await link.evaluate((el) => (el as HTMLLinkElement).href);
    const r = await request.get(href);
    expect(r.status(), href).toBe(200);
    expect(r.headers()['content-type'], href).toContain(type);
    expect((await r.body()).length, href).toBeGreaterThan(100);
  }
});
