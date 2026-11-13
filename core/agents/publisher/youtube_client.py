#!/usr/bin/env python3
"""CF-0421: the thin adapter between the Publisher and the YouTube Data API v3.

Everything that touches `googleapiclient` is in `YouTubeClient`, and it is
deliberately thin - three calls, no decisions: which channel the token belongs
to, and a resumable `videos.insert` request. The decisions (retry or stop,
what the response must contain) live in `run_resumable()`, which takes any
object with `next_chunk()` - so the tests drive it with a stand-in request and
never import Google at all.

Quota (checked against developers.google.com/youtube/v3 on 2026-09-29): since
2026-06-01 `videos.insert` has a bucket of its own - 1 unit per call, 100
uploads a day - separate from the Trend Hunter's search; `channels.list` costs
1 unit of the common bucket. A quota refusal is a 403 and is never retried.
"""
import time

CHUNK_BYTES = 8 * 1024 * 1024           # a multiple of 256 KiB, as resumable upload requires
MAX_RETRIES = 8
RETRIABLE_STATUS = {500, 502, 503, 504}
SHORTS_URL = "https://youtube.com/shorts/{}"


class UploadError(Exception):
    pass


def http_status(exc):
    """The HTTP status of a googleapiclient HttpError (or anything shaped like
    one: `exc.resp.status`), else None."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def is_retriable(exc):
    """A 5xx or a dropped connection is retried; a 4xx (bad metadata, quota,
    revoked grant) never is - repeating it only burns the day's quota."""
    status = http_status(exc)
    if status is not None:
        return status in RETRIABLE_STATUS
    names = {c.__name__ for c in type(exc).__mro__}
    return bool(names & {"HttpLib2Error", "ConnectionError", "TimeoutError",
                         "IncompleteRead", "BrokenPipeError"})


def run_resumable(request, sleep=time.sleep, max_retries=MAX_RETRIES, on_progress=None):
    """Drive a resumable upload to the end: `request.next_chunk()` until it
    returns a response. A retriable failure waits 2, 4, 8 ... (≤ 64) seconds and
    resumes from where the server says the upload stopped (the client library
    keeps that position); `max_retries` failures in a row stop the upload. The
    response must carry the new video's `id`."""
    response = None
    failures = 0
    while response is None:
        try:
            status, response = request.next_chunk()
        except Exception as e:                                  # noqa: BLE001
            if not is_retriable(e):
                code = http_status(e)
                raise UploadError(f"upload refused{f' (HTTP {code})' if code else ''}: {e}") from e
            failures += 1
            if failures > max_retries:
                raise UploadError(f"upload failed after {max_retries} retries: {e}") from e
            sleep(min(2 ** failures, 64))
            continue
        failures = 0
        if status is not None and on_progress is not None:
            try:
                on_progress(float(status.progress()))
            except Exception:                                   # noqa: BLE001
                pass
    if not isinstance(response, dict) or not response.get("id"):
        raise UploadError(f"the API answered without a video id: {response!r}")
    return response


class YouTubeClient:
    """The only place that calls Google. Built from OAuth credentials
    (`publisher_auth.load_credentials`)."""

    def __init__(self, credentials, build=None, media_upload=None):
        if build is None or media_upload is None:
            try:
                from googleapiclient.discovery import build as _build           # noqa: PLC0415
                from googleapiclient.http import MediaFileUpload as _media      # noqa: PLC0415
            except ImportError as e:
                raise UploadError(f"google-api-python-client is not installed ({e.name}) - "
                                  f"install it into agents/publisher/.venv") from e
            build = build or _build
            media_upload = media_upload or _media
        self._media_upload = media_upload
        self._yt = build("youtube", "v3", credentials=credentials, cache_discovery=False)

    def my_channel_ids(self):
        """Ids of the channels the token speaks for (`channels.list mine=true`)."""
        resp = self._yt.channels().list(part="id", mine=True).execute()
        return [item.get("id") for item in (resp or {}).get("items", []) if item.get("id")]

    def video_statuses(self, video_ids):
        """CF-0618: `videos.list part=status` for up to 50 ids per call ->
        {video_id: status dict}; an id YouTube does not return (deleted, or
        not visible to this token) is absent. 1 quota unit per call."""
        ids = list(dict.fromkeys(v for v in video_ids if v))
        found = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            resp = self._yt.videos().list(part="status", id=",".join(chunk),
                                          maxResults=50).execute()
            for item in (resp or {}).get("items", []):
                if item.get("id"):
                    found[item["id"]] = item.get("status") or {}
        return found

    def insert_request(self, video_path, body, chunksize=CHUNK_BYTES):
        """A resumable `videos.insert` request, not yet sent - `run_resumable`
        sends it."""
        media = self._media_upload(str(video_path), mimetype="video/mp4",
                                   chunksize=chunksize, resumable=True)
        return self._yt.videos().insert(part=",".join(sorted(body)), body=body,
                                        media_body=media)
