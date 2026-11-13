// The demo lists of a channel (CC-0022 of the factory), read only: the advisory rights-holder list
// of a channel and its footage origin. Shared by Vitest (MSW, src/mocks/handlers.ts), Playwright
// (tests/e2e/fixtures.ts) and the training mode (src/training/demo.ts). The data is ./rightsData.
// The state is the backend's fields: a test can break any read (`refuse`) before opening. Writing
// the footage origin goes through ./channelLists. Imports are relative.
import type { components } from '../api/schema.gen';
import { createListWrites, routeListWrites, type ListWrites } from './channelLists';
import { FOOTAGE_ERRORS, FOOTAGE_ORIGIN, RIGHTS_CHANNELS, RIGHTS_HOLDERS } from './rightsData';

type S = components['schemas'];
type Code = S['RightsProblem']['code'] | S['WritesProblem']['code'];

export type RightsReply<T> =
  | { status: 200; body: T }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: Code; details: string[] } };

/** A read a test can break (`state.refuse`). */
export type RightsPart = 'rights-holders' | 'footage-origin';

const REFUSAL: Record<RightsPart, { code: Code; message: string; detail: string }> = {
  'rights-holders': {
    code: 'rights_holders_unreadable',
    message: "The channel's rights-holder list cannot be read.",
    detail: 'JSONDecodeError: rights-holder-blacklist.json: Expecting value: line 1 column 1',
  },
  'footage-origin': {
    code: 'footage_origin_unreadable',
    message: "The channel's footage-origin file cannot be read.",
    detail: 'JSONDecodeError: footage-origin.json: Expecting value: line 1 column 1',
  },
};

const ok = <T>(body: T): RightsReply<T> => ({ status: 200, body });
const problem = (
  status: 404 | 409 | 422 | 500,
  code: Code,
  message: string,
  details: string[] = [],
): RightsReply<never> => ({ status, body: { message, code, details } });

const deep = <T>(x: T): T => structuredClone(x);
/** A stand-in sha256 of a list (64 hex; no node:crypto in the mocks) - changes with the content. */
function standInSha(doc: unknown): string {
  const text = JSON.stringify(doc);
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, '0').repeat(8);
}

export function createRightsBackend() {
  const state = {
    channels: [...RIGHTS_CHANNELS] as string[],
    rightsHolders: deep(RIGHTS_HOLDERS),
    footage: deep(FOOTAGE_ORIGIN),
    footageErrors: deep(FOOTAGE_ERRORS),
    /** More lines of the factory's check when the footage origin is written (CC-0130): channel -> lines. */
    footageRefuse: {} as Record<string, string[]>,
    /** Broken reads: part -> refusal 409 (`factory_broken` - 500). */
    refuse: {} as Partial<Record<RightsPart, true | 'factory_broken'>>,
    /** Every GET: the path with the query. */
    calls: [] as string[],
  };

  const known = (c: string) => state.channels.includes(c);
  const unknown = (c: string) =>
    problem(404, 'unknown_channel', `There is no channel ${c} among the factory's channels.`, [
      `channel_ids.resolve_channel: ${c}`,
    ]);
  const refused = (part: RightsPart): RightsReply<never> | null => {
    const r = state.refuse[part];
    if (!r) return null;
    if (r === 'factory_broken')
      return problem(500, 'factory_broken', "The factory does not answer: its code did not load.", [
        'ImportError: agents/compliance-checker/scripts/rights_holder_info.py',
      ]);
    const f = REFUSAL[part];
    return problem(409, f.code, f.message, [f.detail]);
  };

  // CC-0115 step 3: editing the footage origin (./channelLists).
  const lists: ListWrites = createListWrites({
    read: (c, list) => {
      const doc = state.footage[c];
      return list === 'footage-origin'
        ? { doc: doc ?? null, sha: doc ? standInSha(doc) : null }
        : { doc: null, sha: null };
    },
    write: (c, _list, doc) => {
      state.footage[c] = doc as (typeof state.footage)[string];
    },
    errors: (c, list) => (list === 'footage-origin' ? (state.footageRefuse[c] ?? []) : []),
  });

  return {
    state,
    lists,
    rightsHolders(c: string): RightsReply<S['ChannelRightsHolders']> {
      if (!known(c)) return unknown(c);
      const r = refused('rights-holders');
      if (r) return r;
      const doc = state.rightsHolders[c] ?? null;
      const path = `channels/${c}/rights-holder-blacklist.json`;
      return ok({
        channel: c,
        path,
        doc,
        missing: doc ? null : `${c}: missing ${path}`,
        sha256: doc ? standInSha(doc) : null,
      });
    },
    footageOrigin(c: string): RightsReply<S['ChannelFootageOrigin']> {
      if (!known(c)) return unknown(c);
      const r = refused('footage-origin');
      if (r) return r;
      const doc = state.footage[c] ?? null;
      const path = `channels/${c}/footage-origin.json`;
      return ok({
        channel: c,
        path,
        doc,
        missing: doc ? null : `${c}: missing ${path}`,
        errors: doc ? (state.footageErrors[c] ?? []) : [],
        sha256: doc ? standInSha(doc) : null,
      });
    },
  };
}

export type RightsBackend = ReturnType<typeof createRightsBackend>;

/** The answer to a request to this API, or `null` if the request is not for it (or not a GET). */
export function routeRights(
  backend: RightsBackend,
  method: string,
  url: URL,
  body: unknown = null,
): RightsReply<unknown> | null {
  const p = url.pathname;
  const list = routeListWrites(backend.lists, ['footage-origin'], method, url, body);
  if (list) return list as RightsReply<unknown>;
  const ch = p.match(/\/api\/channels\/([^/]+)\/(rights-holders|footage-origin)$/);
  if (!ch) return null;
  if (method !== 'GET') return null;
  backend.state.calls.push(p + url.search);
  const c = decodeURIComponent(ch[1]!);
  return ch[2] === 'rights-holders' ? backend.rightsHolders(c) : backend.footageOrigin(c);
}
