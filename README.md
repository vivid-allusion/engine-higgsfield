# engine-higgsfield

Engine wrapper for **Higgsfield** — images and video through one asynchronous
request lifecycle. Uniform interface that the Image and Video Generators call
instead of talking to the provider directly.

**83 endpoints, catalogued from Higgsfield's own documentation on 2026-11-04:
17 image and 66 video.** Their OpenAPI file lists six models and their own docs
call it supplementary, so the per-model pages are the source. Every entry is
`experimental` — no call has been proved yet, and a documentation-derived
catalogue promises nothing until one is.

## The interface

```python
from engine_higgsfield import Engine, InputFile

engine = Engine(profile, output_dir, api_key=None, on_progress=None)
results = engine.run([InputFile(path=..., prompt=...)])
```

`Engine.__init__` is pure. `run()` returns one result per input file, or one per
saved asset, and never raises for a per-file failure — `EngineError` is reserved
for pre-flight (missing endpoint, bad concurrency, missing key).

## The key

Higgsfield uses a **two-part credential**, not a single token:

```
export HIGGSFIELD_API_KEY="<api_key_id>:<api_key_secret>"
```

The Engine sends `Authorization: Key <that value>`. The credential is never
logged, never written to a file, and never returned in an error message.

## How a run works

1. submit to the model's **own path** — the catalogue carries `api_path` per
   entry, because Higgsfield has no single generation endpoint;
2. the response carries a `request_id` and the **status URL to poll** — the
   Engine uses that URL rather than constructing one;
3. terminal states are `completed`, `failed`, `nsfw`, `canceled`; `nsfw` is
   reported as a moderation rejection, not a transport failure;
4. outputs arrive as `images[]`, `video`, `audio`/`audios`, depending on the
   model — an empty result is an error, never an empty success.

## The catalogue

Rebuild it from the provider's pages when their docs change:

```
python scripts/build_catalogue.py --out engine_higgsfield/endpoints
```

It walks the image and video index, reads each workflow page's endpoint and
input schema, and reports everything it refused to guess — nested sub-fields,
structured inputs, training and reference workflows. Nothing is invented,
including prices: `[pricing]` says "unset" until a human fills it from the
provider's page.

## Tests

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Two suites run together: this engine's own tests, and the shared conformance
suite that every engine in the fleet must pass.

## Scope

Image and video only today. Higgsfield also serves audio; its endpoints are in
the catalogue's siblings once the Audio Generator exists (`SCOPE.md`).
