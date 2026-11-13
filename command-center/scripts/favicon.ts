// CC-0144: растровые иконки центра — `npm run favicon`. Два рисунка: основной `public/favicon.svg`
// (его же берёт вкладка браузера) и упрощённый `public/favicon-16.svg` для самых мелких растров —
// без разрывов, буквы просто наложены, чтобы на 16 px не слипались в пятно; какой размер из какого
// рисунка — `SOURCE_OF` ниже. SVG рисует Chromium из Playwright (он уже стоит для e2e),
// `favicon.ico` собирается здесь же из PNG 16/32/48 (ICO с PNG внутри — так понимают все браузеры
// с Vista/IE9), без новых зависимостей.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PUBLIC_DIR = fileURLToPath(new URL('../public/', import.meta.url));

/** Что собирается из SVG: файл в `public/` → сторона в пикселях. */
export const PNG_OUTPUTS = { 'favicon-32.png': 32, 'apple-touch-icon.png': 180 } as const;
export const ICO_SIZES = [16, 32, 48] as const;

/** Рисунки в `public/`: основной и упрощённый для мелких растров. */
export const SOURCES = { main: 'favicon.svg', small: 'favicon-16.svg' } as const;
/** Из какого рисунка растр стороны N px; чего нет в списке — из основного. */
export const SOURCE_OF: Partial<Record<number, keyof typeof SOURCES>> = { 16: 'small' };

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Ширина и высота PNG из его IHDR; не PNG — ошибка. */
export function pngSize(png: Buffer): { width: number; height: number } {
  if (png.length < 24 || !png.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error('не PNG');
  }
  return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
}

/** ICO из готовых PNG: заголовок, каталог по 16 байт на картинку, затем сами PNG подряд. */
export function buildIco(pngs: Buffer[]): Buffer {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // зарезервировано
  header.writeUInt16LE(1, 2); // 1 — иконка
  header.writeUInt16LE(pngs.length, 4);
  let offset = 6 + 16 * pngs.length;
  const entries = pngs.map((png) => {
    const { width, height } = pngSize(png);
    if (width > 256 || height > 256) throw new Error(`в ICO не больше 256 px: ${width}×${height}`);
    const e = Buffer.alloc(16);
    e.writeUInt8(width === 256 ? 0 : width, 0);
    e.writeUInt8(height === 256 ? 0 : height, 1);
    e.writeUInt8(0, 2); // палитры нет
    e.writeUInt8(0, 3);
    e.writeUInt16LE(1, 4); // плоскостей
    e.writeUInt16LE(32, 6); // бит на пиксель
    e.writeUInt32LE(png.length, 8);
    e.writeUInt32LE(offset, 12);
    offset += png.length;
    return e;
  });
  return Buffer.concat([header, ...entries, ...pngs]);
}

/** Картинки из ICO: размер из каталога и PNG по смещению (для проверки собранного файла). */
export function readIco(ico: Buffer): { size: number; png: Buffer }[] {
  if (ico.readUInt16LE(0) !== 0 || ico.readUInt16LE(2) !== 1) throw new Error('не ICO');
  const count = ico.readUInt16LE(4);
  return Array.from({ length: count }, (_, i) => {
    const at = 6 + 16 * i;
    const size = ico.readUInt8(at) || 256;
    const length = ico.readUInt32LE(at + 8);
    const offset = ico.readUInt32LE(at + 12);
    return { size, png: ico.subarray(offset, offset + length) };
  });
}

/** SVG → PNG стороной `size` с прозрачными углами (скруглённая подложка). */
async function render(svg: string, sizes: number[]): Promise<Map<number, Buffer>> {
  const { chromium } = await import('@playwright/test');
  const browser = await chromium.launch();
  try {
    const out = new Map<number, Buffer>();
    const src = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
    for (const size of sizes) {
      const page = await browser.newPage({
        viewport: { width: size, height: size },
        deviceScaleFactor: 1,
      });
      await page.setContent(
        `<style>html,body{margin:0;background:transparent}img{display:block}</style>` +
          `<img src="${src}" width="${size}" height="${size}">`,
      );
      await page.locator('img').evaluate((img: HTMLImageElement) => img.decode());
      out.set(size, await page.screenshot({ omitBackground: true }));
      await page.close();
    }
    return out;
  } finally {
    await browser.close();
  }
}

async function main() {
  const sizes = [...new Set<number>([...Object.values(PNG_OUTPUTS), ...ICO_SIZES])];
  const pngs = new Map<number, Buffer>();
  for (const [key, file] of Object.entries(SOURCES)) {
    const svg = await readFile(resolve(PUBLIC_DIR, file), 'utf8');
    const mine = sizes.filter((s) => (SOURCE_OF[s] ?? 'main') === key);
    for (const [size, png] of await render(svg, mine)) pngs.set(size, png);
  }
  for (const [name, size] of Object.entries(PNG_OUTPUTS)) {
    await writeFile(resolve(PUBLIC_DIR, name), pngs.get(size)!);
  }
  await writeFile(resolve(PUBLIC_DIR, 'favicon.ico'), buildIco(ICO_SIZES.map((s) => pngs.get(s)!)));
  console.log(
    `public/: ${Object.keys(PNG_OUTPUTS).join(', ')}, favicon.ico (${ICO_SIZES.join('/')})`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e: unknown) => {
    console.error(e);
    process.exit(1);
  });
}
