// @vitest-environment node
// CC-0144: иконка центра — ссылки в index.html, файлы в public/ и сборка ICO.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  buildIco,
  ICO_SIZES,
  PNG_OUTPUTS,
  PUBLIC_DIR,
  pngSize,
  readIco,
  SOURCE_OF,
  SOURCES,
} from './favicon.ts';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const pub = (name: string) => readFileSync(resolve(PUBLIC_DIR, name));

/** Заголовок PNG нужного размера — для ICO хватает сигнатуры и IHDR. */
function fakePng(size: number): Buffer {
  const b = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(b, 0);
  b.write('IHDR', 12, 'ascii');
  b.writeUInt32BE(size, 16);
  b.writeUInt32BE(size, 20);
  return b;
}

describe('сборка ICO', () => {
  it('каталог указывает на каждую PNG с её размером', () => {
    const pngs = [16, 32, 256].map(fakePng);
    const ico = buildIco(pngs);
    expect(ico.readUInt16LE(2)).toBe(1);
    expect(ico.readUInt16LE(4)).toBe(3);
    expect(ico.readUInt8(6 + 16 * 2)).toBe(0); // 256 записывается нулём
    const back = readIco(ico);
    expect(back.map((x) => x.size)).toEqual([16, 32, 256]);
    back.forEach((x, i) => expect(x.png.equals(pngs[i])).toBe(true));
  });

  it('не PNG и больше 256 px — ошибка', () => {
    expect(() => buildIco([Buffer.from('nope')])).toThrow('не PNG');
    expect(() => buildIco([fakePng(512)])).toThrow('256');
  });
});

describe('иконка центра', () => {
  it('index.html ссылается на SVG, запасные PNG/ICO и apple-touch-icon — от корня', () => {
    const html = readFileSync(resolve(ROOT, 'index.html'), 'utf8');
    expect(html).toContain('<link rel="icon" type="image/svg+xml" href="/favicon.svg" />');
    expect(html).toContain('href="/favicon-32.png"');
    expect(html).toContain('href="/favicon.ico"');
    expect(html).toContain('<link rel="apple-touch-icon" href="/apple-touch-icon.png" />');
    for (const href of html.matchAll(
      /<link rel="(?:icon|apple-touch-icon)"[^>]*href="\/([^"]+)"/g,
    )) {
      expect(existsSync(resolve(PUBLIC_DIR, href[1])), href[1]).toBe(true);
    }
  });

  it.each(Object.values(SOURCES))('%s нарисован путями (без шрифта): белая V, жёлтая G', (file) => {
    const svg = pub(file).toString('utf8');
    const css = readFileSync(resolve(ROOT, 'src/index.css'), 'utf8');
    const primary = /--primary:\s*(#[0-9a-f]{6});/i.exec(css)![1];
    expect(svg).toMatch(/^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" viewBox="0 0 64 64">/);
    expect(svg).not.toContain('<text');
    expect(svg).toContain('fill="#ffffff"');
    expect(svg).toContain(`stroke="${primary}"`);
    // В XML-комментарии «--» запрещено — с ним браузер не откроет файл вовсе.
    for (const c of svg.matchAll(/<!--([\s\S]*?)-->/g)) expect(c[1]).not.toContain('--');
  });

  it('упрощённый рисунок — только для 16 px, остальное из основного', () => {
    expect(SOURCE_OF).toEqual({ 16: 'small' });
  });

  it('растровые файлы нужных размеров, ICO — 16/32/48', () => {
    for (const [name, size] of Object.entries(PNG_OUTPUTS)) {
      expect(pngSize(pub(name)), name).toEqual({ width: size, height: size });
    }
    const icons = readIco(pub('favicon.ico'));
    expect(icons.map((x) => x.size)).toEqual([...ICO_SIZES]);
    for (const { size, png } of icons) expect(pngSize(png)).toEqual({ width: size, height: size });
  });
});
