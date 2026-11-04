"""Higgsfield engine behaviour, with the provider faked.

The catalogue is the provider's own documentation; these tests keep the wire
honest: submit to the model's own path, poll the status URL they hand back,
and report nsfw as a rejection rather than a mystery.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_higgsfield import Engine, EngineError, InputFile  # noqa: E402
from engine_higgsfield.transport import ProviderError  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
SOUL = "higgsfield/higgsfield-ai-soul-standard"
SOUL_PATH = "/higgsfield-ai/soul/standard"


class FakeClient:
    def __init__(self, script, payload=PNG):
        self.script = list(script)
        self.payload = payload
        self.calls = []
        self.downloads = []

    def request_json(self, method, path, payload=None, *, headers=None, params=None):
        self.calls.append({"method": method, "path": path, "payload": payload})
        if not self.script:
            raise AssertionError(f"unexpected extra request: {method} {path}")
        response = self.script.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def download(self, url):
        self.downloads.append(url)
        return self.payload


def queue(status_url="https://api.higgsfield.ai/requests/req-1/status"):
    return {
        "request_id": "req-1",
        "status": "queued",
        "status_url": status_url,
        "cancel_url": "https://api.higgsfield.ai/requests/req-1/cancel",
    }


def completed(url="https://cdn.higgsfield.ai/out.png"):
    return {"request_id": "req-1", "status": "completed", "images": [{"url": url}]}


def make_engine(tmp_path, monkeypatch, client, **profile):
    monkeypatch.setattr(Engine, "_client", lambda self: client)
    base = {
        "platform": "higgsfield",
        "endpoint": SOUL,
        "media_type": "image",
        "parameters": {},
        "poll_interval": 0,
        "timeout_seconds": 0,
        "retry_on_429": 0,
    }
    base.update(profile)
    return Engine(base, tmp_path, api_key="key-id:key-secret")


def an_input(tmp_path, prompt="a quiet alpine lake", refs=()):
    path = tmp_path / "shot.md"
    path.write_text(prompt + "\n")
    return InputFile(path=path, prompt=prompt, reference_urls=list(refs))


def test_a_good_run_submits_to_the_models_own_path_and_saves_the_result(tmp_path, monkeypatch):
    client = FakeClient([queue(), completed()])
    engine = make_engine(tmp_path, monkeypatch, client)
    events = []
    engine._on_progress = events.append

    results = engine.run([an_input(tmp_path)])

    assert [r.status for r in results] == ["ok"]
    assert results[0].path.read_bytes() == PNG
    assert results[0].metadata["api_payload"]["prompt"] == "a quiet alpine lake"
    assert client.calls[0]["method"] == "POST"
    assert client.calls[0]["path"] == SOUL_PATH
    assert client.downloads == ["https://cdn.higgsfield.ai/out.png"]
    assert any(event.message.startswith("[1/1] 🧾") for event in events)


def test_the_status_url_from_the_response_is_the_one_polled(tmp_path, monkeypatch):
    client = FakeClient([queue("https://api.higgsfield.ai/requests/req-1/status"), completed()])
    engine = make_engine(tmp_path, monkeypatch, client)
    engine.run([an_input(tmp_path)])
    assert client.calls[1]["method"] == "GET"
    assert client.calls[1]["path"] == "https://api.higgsfield.ai/requests/req-1/status"


def test_the_prefix_and_suffix_ride_around_the_prompt(tmp_path, monkeypatch):
    client = FakeClient([queue(), completed()])
    engine = make_engine(tmp_path, monkeypatch, client, prompt_prefix="style: ", prompt_suffix=", sharp")
    engine.run([an_input(tmp_path)])
    assert client.calls[0]["payload"]["prompt"] == "style: a quiet alpine lake, sharp"


def test_an_empty_prompt_fails_before_any_call(tmp_path, monkeypatch):
    client = FakeClient([])
    engine = make_engine(tmp_path, monkeypatch, client)
    results = engine.run([an_input(tmp_path, prompt="")])
    assert results[0].status == "error"
    assert "prompt" in results[0].error_msg.lower()
    assert client.calls == []


def test_nsfw_is_a_rejection_not_a_mystery(tmp_path, monkeypatch):
    client = FakeClient([queue(), {"request_id": "req-1", "status": "nsfw"}])
    engine = make_engine(tmp_path, monkeypatch, client)
    results = engine.run([an_input(tmp_path)])
    assert results[0].status == "error"
    assert "moderation" in results[0].error_msg.lower()


def test_a_fatal_error_stops_the_batch(tmp_path, monkeypatch):
    client = FakeClient([ProviderError(401, "unauthorized")])
    engine = make_engine(tmp_path, monkeypatch, client)
    results = engine.run([an_input(tmp_path), an_input(tmp_path)])
    assert len(results) == 1
    assert len(client.calls) == 1


def test_a_missing_key_is_a_preflight_error(tmp_path):
    engine = Engine({"endpoint": SOUL}, tmp_path)
    try:
        engine.run([an_input(tmp_path)])
    except EngineError as exc:
        assert "HIGGSFIELD_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected EngineError")
