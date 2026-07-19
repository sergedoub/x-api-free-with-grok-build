# Make X API calls for Free from Grok Build

This is a small pipeline for reading and searching public X without
an X Developer API key.

Instead of pay-per-use access to Posts and User content on X we're using Grok Build which has 1st party integration with X API with kind of secret tools calls. 
This pipeline is a small step further and shows how to call Grok Build in non-interactive mode on Hetzner VPS (you can use any). 
Get posts or search for keywords on X and normalize the results to Markdown, deliver them to your GitHub repository.

The repository is the handoff point. What happens next is deliberately open:
build an app, feed an agent, create a search index, import a database, publish a
site, or keep an archive. I personally use it to feed my [LLM-wiki](https://github.com/sergedoub/bowerbird).

There is no separate per-read X API bill on this path. It is not literally free:
you still need eligible Grok access and a paid VPS, and Grok usage counts against
the allowance for that access.

## Tools 
### `x_thread_fetch`: fetch a known post and its thread
### `x_keyword_search`: use X search operators
### `x_semantic_search`: find a post by meaning
### `x_user_search`: resolve an account to a user ID

This is a best-effort reader, not a drop-in X API. Retrieval is model-driven and
therefore nondeterministic. Grok can miss a result, return a different result on
another run, or fail to satisfy the structured-output schema. The worker treats
malformed output as a failed run; it does not invent records or silently fall
back to a metered API.



## Set it up

Give [`MEGA_PROMPT.md`](MEGA_PROMPT.md) to a capable coding agent. It contains
the complete setup, security and end-to-end verification workflow.

## A real result, through all four X tools

The commands below were verified with Grok Build 0.2.102 on 18 July 2026 against
this real Elon Musk post:

<https://x.com/elonmusk/status/2078289996323148076>

Grok returned post ID `2078289996323148076`, author `@elonmusk`, and creation
time `Sat, 18 Jul 2026 01:25:22 GMT`. The post begins: “Our 2T model, which is
better than our 1.5T in every way, will finish initial training next week.”


Set the shared headless safety flags once in Bash:

```bash
GROK_X_FLAGS=(
  --always-approve
  --sandbox strict
  --output-format json
  --no-memory
  --no-subagents
  --no-plan
  --max-turns 4
  --disable-web-search
  --deny 'Bash(*)'
  --deny 'Edit(*)'
  --deny 'Read(*)'
  --deny 'Grep(*)'
  --deny 'WebFetch(*)'
  --deny 'MCPTool(*)'
)
```

### `x_thread_fetch`: fetch a known post and its thread

```bash
grok -p 'Use x_thread_fetch exactly once with post_id 2078289996323148076. Return the exact post ID, author handle, full post text, creation time, and URL. Do not use any other tool or summarize.' \
  "${GROK_X_FLAGS[@]}"
```

This returned post ID `2078289996323148076` from `@elonmusk`.

### `x_keyword_search`: use X search operators

```bash
grok -p 'Use x_keyword_search exactly once in Latest mode with this query: from:elonmusk since:2026-07-18 "Our 2T model" -is:retweet. Return post IDs, author handles, creation times, full text, and URLs. Do not use any other tool or summarize.' \
  "${GROK_X_FLAGS[@]}"
```

This returned the same post ID from `@elonmusk`.

### `x_semantic_search`: find a post by meaning

```bash
grok -p 'Use x_semantic_search exactly once to find the Elon Musk post about a 2T model finishing initial training and possibly exceeding Kimi. Return post IDs, author handles, creation times, full text, and URLs. Do not use any other tool or summarize.' \
  "${GROK_X_FLAGS[@]}"
```

The results included post ID `2078289996323148076` from `@elonmusk`.

### `x_user_search`: resolve an account to a user ID

```bash
grok -p 'Use x_user_search exactly once to find the official Elon Musk account. Return candidate handles and user IDs. Identify the official account from the tool result. Do not use any other tool.' \
  "${GROK_X_FLAGS[@]}"
```

This returned `@elonmusk` with user ID `44196397`. It also returned similarly
named accounts, so keep the selected user ID rather than trusting a display name
alone.


## What lands in GitHub

One post becomes one append-only Markdown file:

```markdown
---
author: "@elonmusk"
created_at: "2026-07-18T01:25:22Z"
query_name: "model-training"
query: "from:elonmusk since:2026-07-18 -is:retweet"
source_url: "https://x.com/elonmusk/status/2078289996323148076"
---

Our 2T model, which is better than our 1.5T in every way, will finish initial
training next week…
```

The stable path is:

```text
raw/x/<query-name>/YYYY-MM-DD__<post-id>.md
```




## Limitations

The tools used here are read-only. This project does not post, like, follow,
send messages, or manage an X account. A Grok Build failure never triggers an X API
fallback.

This project is not affiliated with X, xAI, Grok, GitHub, or Hetzner.

## Licence

MIT. See [`LICENSE`](LICENSE).
