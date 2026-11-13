// Подставные кандидаты в банк мемов (CC-0115 → CC-0103, `GET /api/memes/{c}/candidates`): у Tech
// свой банк и список шаблонов Imgflip, ждущих «да» (проходят по растяжке, не проходят, без
// данных; часть уже лежит в банке Reel — копия без скачивания); у банка по умолчанию списка нет.
// Импорты — относительные (общий для Vitest, Playwright и тренировки).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

type Row = [
  id: string,
  name: string,
  w: number | null,
  h: number | null,
  stretch: number | null,
  status: S['MemeCandidate']['status'],
  reel?: string,
];

const ROWS: Row[] = [
  ['this-is-fine', 'This Is Fine', 580, 282, 1.86, 'ready'],
  ['drake', 'Drake Hotline Bling', 1200, 1200, 0.9, 'ready', 'drake-hotline-bling'],
  [
    'distracted-boyfriend',
    'Distracted Boyfriend',
    1200,
    800,
    0.9,
    'in_bank',
    'distracted-boyfriend',
  ],
  ['two-buttons', 'Two Buttons', 600, 908, 1.8, 'not_downloaded'],
  ['change-my-mind', 'Change My Mind', 482, 361, 2.24, 'not_downloaded'],
  ['surprised-pikachu', 'Surprised Pikachu', 1893, 1893, 0.57, 'not_downloaded'],
  ['stonks', 'Stonks', 300, 220, 3.6, 'not_downloaded'],
  ['hide-the-pain', 'Hide the Pain Harold', 480, 601, 2.53, 'not_downloaded'],
  ['galaxy-brain', 'Expanding Brain', null, null, null, 'not_downloaded'],
];

const CEILING = 2.25;

function candidate([id, name, w, h, stretch, status, reel]: Row): S['MemeCandidate'] {
  const pass = stretch == null ? null : stretch <= CEILING;
  return {
    id,
    name,
    imgflip_id: String(100000 + id.length),
    url: `https://i.imgflip.com/${id}.jpg`,
    width: w,
    height: h,
    stretch,
    passes_ceiling: pass,
    bytes: w && h ? Math.round(w * h * 0.12) : null,
    blank_band: 'top caption band',
    intents: ['deadpan', 'frustration'],
    use: 'a launch is on fire and the statement says everything works',
    in_reel_bank: reel ?? null,
    stretch_now: stretch,
    group: pass == null ? 'unknown' : pass ? 'pass' : 'fail',
    copy_from: null,
    status,
    bank_file:
      status === 'ready' || status === 'in_bank'
        ? `shared/inserts/memes-example-tech/${id}.jpg`
        : null,
  };
}

export function candidatesReply(
  channel: string,
  ownBank: boolean,
  accepted: readonly string[] = [],
): S['MemeCandidates'] {
  const bank = ownBank ? `shared/inserts/memes-${channel}/` : 'shared/inserts/memes/';
  if (!ownBank)
    return {
      channel,
      bank,
      default_bank: true,
      path: `${bank}candidates.json`,
      fingerprint: null,
      missing: 'У банка нет списка кандидатов (candidates.json) — предлагать нечего.',
      candidates: [],
      tail: [],
      problems: [],
      counts: { pass: 0, fail: 0, unknown: 0 },
      download: { files: 0, bytes: 0 },
      copy: { files: 0, bytes: 0 },
      accept: {
        available: false,
        reason: 'Списка кандидатов нет.',
        ready: [],
        other_bank: [],
      },
    };
  const candidates = ROWS.map(candidate).map((c) =>
    c.id && accepted.includes(c.id) ? { ...c, status: 'in_bank' as const } : c,
  );
  const count = (g: string) => candidates.filter((c) => c.group === g).length;
  const ready = candidates.filter((c) => c.status === 'ready').map((c) => c.id!);
  return {
    channel,
    bank,
    default_bank: false,
    path: `${bank}candidates.json`,
    fingerprint: 'f00d'.repeat(16),
    missing: null,
    listed: '2026-10-12',
    source: { name: 'Imgflip', template_list: 'https://api.imgflip.com/get_memes' },
    summary: { candidates: candidates.length },
    schema_note: 'CF-0393: the templates proposed for the bank',
    fit_box: [1080, 1219],
    ceiling: CEILING,
    candidates,
    tail: [],
    problems: ["galaxy-brain: no template data (width/height) - passes_ceiling can't be checked"],
    counts: { pass: count('pass'), fail: count('fail'), unknown: count('unknown') },
    download: { files: 3, bytes: 412_000 },
    copy: { files: 2, bytes: 389_385 },
    copy_channel: 'example-film',
    copy_error: null,
    accept: {
      available: true,
      reason: null,
      fingerprint: 'sha256:0123456789abcdef',
      counts: {
        total: candidates.length,
        ready: ready.length,
        in_bank: 1,
        not_downloaded: candidates.length - ready.length - 1,
        outside_bank: 0,
      },
      ready,
      other_bank: [],
    },
  };
}
