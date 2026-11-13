// A channel's lists, read only: the rights-holder list (`GET /api/channels/{channel}/rights-holders`,
// advisory: it informs the compliance verdict, it never changes it) and the footage origin
// (`…/footage-origin`). Refusals are `RightsProblem {message, code, details}`, parsed by
// `takeBatch` (./batchProblem). Writing the lists is ./channelLists.
import { useQuery } from '@tanstack/react-query';

import { BatchError, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type ChannelRightsHolders = Schemas['ChannelRightsHolders'];
export type ChannelFootageOrigin = Schemas['ChannelFootageOrigin'];
export type RightsProblem = Schemas['RightsProblem'];

/** The code of a refusal of this API, if the error is its refusal (`RightsProblem`). */
export function rightsCode(e: unknown): RightsProblem['code'] | null {
  return e instanceof BatchError
    ? ((e.problem?.code as RightsProblem['code'] | undefined) ?? null)
    : null;
}

const path = (channel: string) => ({ path: { channel } });

export async function getRightsHolders(
  channel: string,
  signal?: AbortSignal,
): Promise<ChannelRightsHolders> {
  return takeBatch(
    await api.GET('/api/channels/{channel}/rights-holders', { params: path(channel), signal }),
  );
}

export async function getFootageOrigin(
  channel: string,
  signal?: AbortSignal,
): Promise<ChannelFootageOrigin> {
  return takeBatch(
    await api.GET('/api/channels/{channel}/footage-origin', { params: path(channel), signal }),
  );
}

export const rightsKeys = {
  all: ['api', 'rights'] as const,
  holders: (c: string) => ['api', 'rights', 'holders', c] as const,
  footage: (c: string) => ['api', 'rights', 'footage', c] as const,
};

/** A 4xx refusal (no such channel, an unreadable file) is not cured by a retry; network and 5xx - up to three times. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** The lists change rarely: re-read every 5 minutes and on return to the tab. */
const slow = { refetchInterval: 300_000, refetchIntervalInBackground: false, retry } as const;

export function useRightsHolders(channel: string | null) {
  return useQuery({
    queryKey: rightsKeys.holders(channel ?? ''),
    queryFn: ({ signal }) => getRightsHolders(channel!, signal),
    enabled: !!channel,
    ...slow,
  });
}

export function useFootageOrigin(channel: string | null) {
  return useQuery({
    queryKey: rightsKeys.footage(channel ?? ''),
    queryFn: ({ signal }) => getFootageOrigin(channel!, signal),
    enabled: !!channel,
    ...slow,
  });
}
