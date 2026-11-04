"""The Higgsfield request lifecycle: submit, poll the status URL, collect.

Higgsfield does not have one fixed status address. A submission returns::

    {"status": "queued", "request_id": "...", "status_url": "https://.../status",
     "cancel_url": "..."}

and the status URL in that response is the documented way to poll. Every model
posts to its own path (``/higgsfield-ai/soul/standard``,
``/kling-video/v2.5-turbo/pro/text-to-video``), which is why the catalogue
carries ``api_path`` per entry.

States: queued, in_progress (live); completed, failed, nsfw, canceled
(terminal). ``nsfw`` is a content rejection by their moderation, not a
transport failure, and it is reported as such.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .transport import ProviderError

RequestFn = Callable[..., dict]
EmitFn = Callable[[str], None]

LIVE_STATES = frozenset({"queued", "in_progress"})
SUCCESS_STATE = "completed"


def is_terminal(status: object) -> bool:
    return str(status or "") not in LIVE_STATES


def submit(
    request: RequestFn,
    path: str,
    body: dict,
    *,
    headers: dict[str, str] | None = None,
    emit: EmitFn = lambda _msg: None,
    prefix: str = "",
) -> dict:
    """Submit one generation request and return its acceptance record."""
    record = request("POST", path, body, headers=headers)
    if not isinstance(record, dict) or not record.get("request_id"):
        raise ProviderError(200, "Higgsfield accepted the request but returned no request_id")
    emit(f"{prefix} 🧾 Request {record['request_id']} accepted ({record.get('status') or 'queued'})")
    return record


def await_job(
    request: RequestFn,
    job: dict,
    *,
    poll_interval: float,
    timeout: float,
    emit: EmitFn = lambda _msg: None,
    prefix: str = "",
) -> dict:
    """Poll the request's own status URL until it reaches a terminal state."""
    request_id = str(job.get("request_id") or "")
    status_url = str(job.get("status_url") or "")
    if not status_url:
        status_url = f"/requests/{request_id}/status"

    started = time.monotonic()
    last_status = str(job.get("status") or "")
    while True:
        if timeout and time.monotonic() - started > timeout:
            raise ProviderError(
                0,
                f"Request {request_id} did not finish within {timeout:.0f}s — it keeps "
                f"running at Higgsfield; collect it later with the status URL",
            )
        if poll_interval:
            time.sleep(poll_interval)
        record = request("GET", status_url)
        if not isinstance(record, dict):
            raise ProviderError(200, f"Higgsfield returned no record for request {request_id}")
        status = str(record.get("status") or "")
        if status != last_status:
            last_status = status
            emit(f"{prefix} ⏳ Request {status}")
        if not is_terminal(status):
            continue
        if status != SUCCESS_STATE:
            raise ProviderError(200, _failure_message(record))
        emit(f"{prefix} ✅ Request completed")
        return record


def output_urls(record: dict) -> list[str]:
    """Result URLs from a completed request.

    The field depends on the model's output type: ``images[]`` for image
    models, ``video`` for video, ``audio``/``audios`` for audio. Missing or
    empty means the request finished with nothing, which the Engine reports as
    an error rather than an empty success.
    """
    urls: list[str] = []
    images = record.get("images")
    if isinstance(images, list):
        urls.extend(
            str(item["url"])
            for item in images
            if isinstance(item, dict) and item.get("url")
        )
    for key in ("video", "audio"):
        value = record.get(key)
        if isinstance(value, dict) and value.get("url"):
            urls.append(str(value["url"]))
    audios = record.get("audios")
    if isinstance(audios, list):
        urls.extend(
            str(item["url"])
            for item in audios
            if isinstance(item, dict) and item.get("url") and str(item["url"]) not in urls
        )
    return urls


def _failure_message(record: dict) -> str:
    status = str(record.get("status") or "failed")
    detail = str(record.get("error") or "").strip()
    request_id = str(record.get("request_id") or "")
    text = f"Request {request_id} ended as {status}"
    if detail:
        text += f" — {detail}"
    if status == "nsfw":
        text += " (rejected by Higgsfield's content moderation)"
    return text
