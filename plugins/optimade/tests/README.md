# Tests

Positive tests, examples, demonstrations, and evidence use real,
provenance-traceable OPTIMADE responses or live supported providers. Generated
inputs are permitted only under `negative_generated/` for rejection, boundary,
fuzz, and security tests. A fake provider or mocked positive response cannot
establish progress.

One live negative pagination test obtains an authentic first provider page and
then deliberately repeats those exact bytes at a new offset. The repeated page
is rejection evidence only; its altered transport behavior is not counted as a
successful provider response.

Run the offline suite with `pytest -m "not live"`. Live evidence is deliberately
double-gated and requires both `MATERIALS_MCP_LIVE=1` and `pytest -m live`; a
scheduled workflow sets both explicitly so a skipped run cannot be mistaken for
provider evidence.
