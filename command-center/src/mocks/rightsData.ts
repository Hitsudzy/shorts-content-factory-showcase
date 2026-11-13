// The demo data of a channel's lists (rights holders, footage origin) - everything here is made up.
// `mocks/rights.ts` serves it (`GET /api/channels/{c}/rights-holders`, `…/footage-origin`).
import { REEL, SCIENCE, TECH } from './publish';

export const RIGHTS_CHANNELS = [REEL, TECH, SCIENCE] as const;

/** `channels/<ch>/rights-holder-blacklist.json`: an advisory list - it informs, it never blocks. */
export const RIGHTS_HOLDERS: Record<string, Record<string, unknown> | null> = {
  [REEL]: {
    channel: REEL,
    last_updated: '2026-10-11',
    entries: [
      { rights_holder: 'Example Studios', risk_level: 'high', evidence: 'curated', reason: 'curated' },
      { rights_holder: 'Acme Pictures', risk_level: 'high', evidence: 'curated', reason: 'curated' },
      { rights_holder: 'Sample Records', risk_level: 'medium', evidence: 'heuristic' },
    ],
  },
  [TECH]: {
    channel: TECH,
    last_updated: '2026-09-29',
    entries: [
      { rights_holder: 'Acme Pictures', risk_level: 'high', evidence: 'curated', reason: 'curated' },
      { rights_holder: 'Sample Devices', risk_level: 'medium', evidence: 'heuristic' },
    ],
  },
  [SCIENCE]: null,
};

/**
 * `channels/<ch>/footage-origin.json`: Reel has only official channels, Science has sources,
 * licences, a credit line and caveats (CC-0130); Tech has an error in the file. The `name` field is
 * not the factory's (unknown to the editor, it goes back as it was).
 */
export const FOOTAGE_ORIGIN: Record<string, Record<string, unknown> | null> = {
  [REEL]: {
    _what: "Official channels of the rights holders: the trend hunter counts their videos as official",
    official_channels: [
      {
        pattern: 'example studios',
        what: 'film studio',
        seen_as: 'Example Studios; Example Studios UK',
        owners: ['example_studios'],
        channels: [
          {
            id: 'UCexampleStudiosMain0000',
            title: 'Example Studios',
            resolved_by: 'videos.list on a video of the batch',
          },
          { id: 'UCexampleStudiosUK000000', title: 'Example Studios UK', resolved_by: 'by @handle' },
        ],
      },
      {
        pattern: 'acme pictures',
        what: 'film studio',
        seen_as: 'Acme Pictures',
        channels: [
          { id: 'UCacmePicturesMain000000', title: 'Acme Pictures', resolved_by: 'by @handle' },
        ],
      },
    ],
  },
  [TECH]: {
    licences: {
      accepted: [
        {
          id: 'youtube_upload',
          name: 'Standard YouTube licence',
          attribution: 'none',
          matches: ['Standard YouTube License'],
          share_alike: false,
        },
      ],
      refused: [],
    },
    attribution: { where: 'description' },
    footage_origins: [
      {
        id: 'press_kits',
        who: 'Manufacturers press kits',
        name: 'Manufacturers press kits',
        licence: 'press_kit',
        terms_url: 'http://example.invalid/press',
        found_by: [{ how: 'search', works_now: false }],
        attribution: { credit: "the manufacturer's press kit", where: 'description', on_screen: false },
      },
    ],
    official_channels: [],
  },
  [SCIENCE]: {
    _what: 'Where the channel takes footage from: sources, their licences and the credit line',
    checked_on: '2026-10-10',
    licences: {
      accepted: [
        {
          id: 'public_domain',
          name: 'Public domain',
          what: 'Works of a government agency - no copyright',
          attribution: 'requested',
          share_alike: false,
          matches: ['public domain'],
        },
        {
          id: 'cc_by',
          name: 'Creative Commons BY',
          what: 'CC BY, any version: credit the author, link the licence',
          attribution: 'required',
          share_alike: false,
          license_url: 'https://creativecommons.org/licenses/by/4.0/',
          matches: ['cc by', 'cc-by'],
        },
        {
          id: 'youtube_upload',
          name: 'Standard YouTube licence',
          what: "A university's or lab's video on their own channel",
          attribution: 'none',
          share_alike: false,
          matches: ['youtube upload'],
        },
      ],
      refused: [
        { id: 'noncommercial', what: 'Creative Commons with a ban on commercial use', tokens: ['nc'] },
        { id: 'noderivatives', what: 'Creative Commons without the right to adapt', tokens: ['nd'] },
      ],
    },
    attribution: { where: 'description', template: 'Footage: {credit}' },
    footage_origins: [
      {
        id: 'space_agency',
        who: 'Example Space Agency',
        name: 'Example Space Agency media library',
        found_by: [
          { how: 'youtube_channels', ref: 'official_channels pattern `example space`', works_now: true },
          {
            how: 'archive_api',
            endpoint: 'https://media.example.invalid/search?media_type=video&q={q}',
            works_now: false,
          },
        ],
        licence: 'public_domain',
        terms_url: 'https://media.example.invalid/terms',
        quote: 'generally not subject to copyright',
        attribution: {
          required: false,
          requested: true,
          credit: 'Example Space Agency',
          where: 'description',
          on_screen: false,
        },
        caveats: [
          "The agency's emblem is not public domain: it does not go on a cover or in credits.",
          'People shown - without a hint that the agency endorses the video.',
        ],
      },
      {
        id: 'observatory',
        who: 'Example Observatory',
        name: 'Example Observatory',
        found_by: [{ how: 'archive_page', works_now: true }],
        licence: 'cc_by',
        terms_url: 'https://observatory.example.invalid/copyright',
        attribution: {
          required: true,
          requested: false,
          credit: 'Example Observatory / A. Author',
          where: 'description+on_screen',
          on_screen: true,
        },
        caveats: ['The credit is both on screen and in the description, with a link to the licence.'],
      },
    ],
    official_channels: [
      {
        pattern: 'example space agency',
        what: 'a space agency',
        origin: 'space_agency',
        owners: ['example_space_agency'],
        seen_as: 'Example Space Agency; Example Space Science',
        channels: [
          {
            id: 'UCexampleSpaceAgency0000',
            title: 'Example Space Agency',
            handle: '@ExampleSpaceAgency',
            resolved_by: "the channel page @ExampleSpaceAgency: its canonical address names this id",
          },
          {
            id: 'UCexampleSpaceScience000',
            title: 'Example Space Science',
            handle: '@ExampleSpaceScience',
            resolved_by: 'the channel page @ExampleSpaceScience',
          },
        ],
      },
    ],
  },
};

export const FOOTAGE_ERRORS: Record<string, string[]> = {
  [TECH]: [
    "footage_origins[0] (press_kits): licence 'press_kit' is neither an accepted licence nor 'per_file'",
    'footage_origins[0] (press_kits): no https `terms_url` - the page its licence was read on',
  ],
};
