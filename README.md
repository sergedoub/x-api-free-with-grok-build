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

Use either route:

- follow the copy-paste walkthrough in [`SETUP.md`](SETUP.md)
- give [`MEGA_PROMPT.md`](MEGA_PROMPT.md) to a capable coding agent



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

Each command prints the Grok CLI JSON envelope, including `text`, `sessionId`,
and usage. The scheduled worker uses
[`x_grok_reader/grok_search.py`](x_grok_reader/grok_search.py) to request and
validate a stable `posts` array for automation. The included scheduled adapter
uses `x_keyword_search`; the other three commands document the bundled tools
available for extending the reader.

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

Provider identity is not written into the document, so downstream consumers can
treat the files as ordinary source records rather than Grok-specific objects.

## Set it up

Use either route:

- follow the copy-paste walkthrough in [`SETUP.md`](SETUP.md)
- give [`MEGA_PROMPT.md`](MEGA_PROMPT.md) to a capable coding agent

Both routes install the same files and require the same end-to-end checks.

Create a private repository from the template if the collected posts should be
private, then enable at least one query:

```bash
gh repo create <owner>/<repo> \
  --private \
  --template sergedoub/x-api-free-with-grok-build \
  --clone
cd <repo>

# Edit config/queries.toml, then verify the checkout.
python3 -m unittest discover -v
gh variable set X_READER_ENABLED --body true --repo <owner>/<repo>
```

On an Ubuntu 24.04 Hetzner VPS, copy this checkout and the current Linux Grok
Build binary, then run:

```bash
sudo ./scripts/install.sh \
  /tmp/x-grok-reader \
  /tmp/grok \
  git@github.com:<owner>/<repo>.git

sudo -u xreader-grok /usr/local/libexec/xreader-grok-login
systemctl start x-grok-reader.service
cat /var/lib/xreader-worker/health.json
```

The installer prints a deploy key. Add that public key, with write access, to
only the destination repository. Run one complete manual retrieval and
publication before enabling the timer:

```bash
systemctl enable --now x-grok-reader.timer
systemctl list-timers x-grok-reader.timer
```

The default timer runs every four hours with up to ten minutes of randomized
delay. GitHub checks pending candidate branches every five minutes, although
scheduled Actions runs can be late.

The important setup and runtime paths are:

| Path | Purpose |
| --- | --- |
| `config/queries.toml` | versioned query configuration |
| `/etc/x-grok-reader/queries.toml` | installed query configuration |
| `/var/lib/xreader-grok/auth.json` | Grok device authentication; readable by `xreader-grok` |
| `/var/lib/xreader-submit/.ssh/id_ed25519` | repository deploy key; readable by `xreader-submit` |
| `/run/x-grok-reader` | tmpfs runtime content, temporary checkouts, and session homes |
| `/var/lib/xreader-worker/health.json` | last-run health record |
| `raw/x/<query>/` | accepted Markdown in the destination repository |

No runtime Python packages are required. The host needs Python 3.11 or later,
Git, OpenSSH, systemd, a Linux Grok Build binary, eligible authenticated Grok
access, and a repository-scoped write deploy key.

## The security boundary

The design assumes the VPS root account and the destination repository are
trusted. Grok output and candidate branches are untrusted input.

The installer creates three Linux system users with separate jobs:

- `xreader-worker` orchestrates a run
- `xreader-grok` owns the Grok authentication file and performs retrieval
- `xreader-submit` owns the repository deploy key and submits candidates

Post content, temporary checkouts, Grok homes, and session files exist only
under `/run/x-grok-reader`. The installer refuses to proceed unless `/run` is a
`tmpfs`, and the worker removes its per-run directory when the run ends.

The systemd service is a hardened oneshot worker, not a server. It has no
listener (`SocketBindDeny=any`), uses `ProtectSystem=strict` and
`ProtectHome=true`, restricts writable paths and address families, and denies
private, link-local, and Tailscale address ranges.

The normal submit path never writes directly to `main`. The
repository-scoped deploy key is write-enabled, so the trust model still assumes
the VPS root account and installed submitter code are not compromised. The
submit helper uses that key only to propose additions on a branch named
`ingest/hetzner/<run-id>`. The publisher then:

1. starts only on a schedule or manual dispatch using workflow code from the
   trusted `main` branch;
2. never executes candidate-provided code;
3. accepts only new, regular, UTF-8 Markdown files matching
   `raw/x/<query>/YYYY-MM-DD__<post-id>.md`;
4. rejects modifications, deletions, symlinks, malformed or oversized files,
   and same-path/different-content collisions;
5. deduplicates identical files, publishes accepted additions to `main`, and
   deletes the candidate branch.

The VPS reports publication only after the candidate branch disappears and the
SHA-256 hashes of the files on `main` match its submission.

## Limitations

The tools used here are read-only. This project does not post, like, follow,
send messages, or manage an X account. A Grok Build failure never triggers an X API
fallback.

This project is not affiliated with X, xAI, Grok, GitHub, or Hetzner.

## Licence

MIT. See [`LICENSE`](LICENSE).
