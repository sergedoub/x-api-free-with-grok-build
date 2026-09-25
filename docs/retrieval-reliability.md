# Reliable headless retrieval

The Python reader supports keyword searches, semantic searches, and exact post/thread retrieval. It returns model-produced results from Grok Build's hosted X search, not raw X API responses. The reader never switches to a metered API or generic-web fallback.

## Read a post or search

Run these commands from the repository on a machine with an authenticated Grok Build installation. Production deployments should use the installed `xreader-grok-search-as-user` helper to preserve account isolation.

```sh
python3 -m x_grok_reader.grok_search \
  --operation thread --query https://x.com/example/status/2102575431857909815 \
  --limit 1

python3 -m x_grok_reader.grok_search \
  --query 'from:example -is:retweet' --mode Latest \
  --lookback-days 7 --limit 5

python3 -m x_grok_reader.grok_search \
  --operation semantic --query 'an explanation of parallel agent audits' --limit 5
```

Replace example handles/IDs with the target's real URL. Thread mode verifies the URL author as well as the requested ID. It retains the exact requested post before applying `--limit`, even when Grok returns a parent first. Other authors' surrounding replies can still be included. A response missing the requested post is an error.

Keyword mode remains the default. `--lookback-days` defaults to zero, preserving existing archival queries. A positive value adds `since:` that many days ago and an exclusive `until:` tomorrow UTC to simple, otherwise unbounded Latest queries. Explicit date/ID bounds and Boolean/grouped expressions are not rewritten. Semantic mode uses the supplied description; its ranking is not controlled by `--mode`.

Configured ingestion supports the same post operations:

```toml
[[queries]]
name = "recent-example"
query = "from:example -is:retweet"
operation = "keyword" # default; also semantic or thread
mode = "Latest"
limit = 5
lookback_days = 7     # default 0; keyword only
expected_handle = "example"
enabled = true
```

Account discovery (`x_user_search`) remains available through the direct Grok example in the README; profiles are not post records and are not ingested by this pipeline.

## Validation and compatibility

The reader validates every returned row before truncation. Required fields must be nonempty strings. Dates must have a timezone and agree with the snowflake ID within one second; offsets are normalized to UTC. Conflicting duplicate IDs, malformed rows, wrong authors, and out-of-window records fail the run. Latest keyword results are sorted before limiting; Top and semantic ordering are preserved.

Simple positive `from:`, `since:YYYY-MM-DD`, and `until:YYYY-MM-DD` constraints are checked locally. Complex query expressions and other date syntaxes remain backend-mediated; their full semantics are not reimplemented here. An explicit `--expected-handle` is enforced even for a complex query. Unlike the old reader, an unexpected author now fails rather than being silently discarded. Thread mode applies this author constraint to the requested post only.

Pre-snowflake posts are not supported by the ID/date consistency check. Internal consistency does not prove that the model reproduced the source accurately. Article bodies may appear in `text`, but completeness and embedded-media fidelity are not independently verified.

Known concatenated-JSON output can recover only when preliminary objects are empty or identical to the final result. Conflicting placeholders, prose, truncated JSON, explicit null structured output, and other upstream errors fail closed. There is no automatic retry or syntax repair.

The CLI retains its top-level `posts` array and adds a `retrieval` metadata object. Existing `search()` callers still receive `list[RetrievedPost]`. Metadata includes original/effective queries, elapsed time, recovery status, model/request IDs, usage and provider-reported cost. Cost telemetry is not proof of an additional charge. An empty search result is marked `empty_inconclusive`; absence is not proof that no posts exist.

## Traces, deadlines and credentials

`--trace-dir /path/to/private/traces` creates a unique directory per call with mode 0700 and files with mode 0600. It retains request parameters, raw stdout/stderr, normalized output, timing, errors and partial timeout output. It does not read authentication files or dump the environment. Traces can contain retrieved content and provider metadata; they are opt-in and never part of the published Markdown. Keep the directory outside the temporary Grok runtime if it must survive cleanup. `debug-runs/` is ignored by Git.

The default Grok deadline is 180 seconds; `--timeout-seconds` accepts 1–3600. On expiry, the process supervisor sends TERM to the isolated Grok process group, waits up to five seconds, then kills remaining descendants. The server helper forwards interruption and removes its own temporary runtime. Login and search share a bounded 30-second credential lock, covering the temporary copy and refresh write. The installer checks for `flock` and Grok's `--tools` option.

## Interface evidence

A restricted headless audit on 25 September 2026 used Grok Build 0.2.103 and received responses from grok-4.7-build. Its reported keyword, semantic, user, and thread operation names matched the earlier implementation. These capabilities now have an [official X Search reference](https://docs.x.ai/developers/tools/x-search).

That reference describes the metered API. Its parameters are not automatically CLI switches; this project continues through Grok Build. The client allowlist is `--tools x_search`. Model-reported internal operation parameters are not a stable, independently exported schema, and prompts cannot prove the exact number of backend calls.

The [official headless guide](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/14-headless-mode.md) documents streaming output. The audit exposed text, thought, and terminal events, but no raw hosted X call events. Schema-constrained JSON remains the normal output.

## Tests

`python3 -m unittest discover -v` runs offline with synthetic records and fake Grok processes. Coverage includes malformed/recovered envelopes, timestamp/author/date checks, exact-post retention, ordering, CLI compatibility, trace permissions, child-process deadlines and partial output. Linux CI additionally runs the installed shell wrapper in temporary directories to verify concurrent credential refreshes and cleanup. No tests require real Grok/X credentials or perform network calls.
