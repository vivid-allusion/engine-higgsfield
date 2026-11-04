"""The four answers the conformance suite needs from Higgsfield.

Everything here is test scaffolding. The one Higgsfield-specific fact that
matters: a submission returns a `request_id` and the absolute status URL to
poll, and the output field depends on whether the model makes images or video.
"""

from __future__ import annotations

from engine_conformance import Behaviours, Call, Connector, Provider


class HiggsfieldConnector(Connector):
    package = "engine_higgsfield"

    entries = {
        "text_to_image": "IMG-Models/higgsfield-ai-soul-standard.toml",
        "image_to_video": "VID-Models/alibaba-happy-horse-image-to-video.toml",
    }

    provider_modules = ()

    def install(self, monkeypatch, behaviours: Behaviours) -> Provider:
        provider = Provider()
        state = {"submit": list(behaviours.submit_errors), "polls": 0, "video": False}

        class FakeClient:
            def request_json(self, method, path, payload=None, *, headers=None, params=None):
                if method == "POST":
                    provider.calls.append(Call(kind="submit", payload=payload, path=path))
                    state["video"] = "video" in path.lower()
                    if behaviours.submit_error is not None:
                        raise behaviours.submit_error
                    if state["submit"]:
                        raise state["submit"].pop(0)
                    return {
                        "request_id": "req-1",
                        "status": "queued",
                        "status_url": "https://api.higgsfield.ai/requests/req-1/status",
                    }

                provider.calls.append(Call(kind="poll", path=path))
                if behaviours.poll_error is not None:
                    raise behaviours.poll_error
                # The suite speaks a provider-neutral vocabulary; Higgsfield's is
                # queued / in_progress / completed / failed / nsfw / canceled.
                vocabulary = {
                    "running": "in_progress",
                    "succeeded": "completed",
                    "queued": "queued",
                    "failed": "failed",
                }
                statuses = behaviours.poll_statuses
                index = min(state["polls"], len(statuses) - 1)
                state["polls"] += 1
                status = vocabulary.get(statuses[index], statuses[index])
                record = {"request_id": "req-1", "status": status}
                if status == "completed":
                    urls = list(behaviours.result_urls)
                    if state["video"]:
                        record["video"] = {"url": urls[0]} if urls else None
                    else:
                        record["images"] = [{"url": url} for url in urls]
                return record

            def download(self, url):
                provider.downloads.append(url)
                provider.calls.append(Call(kind="download", url=url))
                if behaviours.download_error is not None:
                    raise behaviours.download_error
                return behaviours.result_bytes

        fake = FakeClient()
        monkeypatch.setattr(self.engine_class(), "_client", lambda _self: fake)
        return provider
