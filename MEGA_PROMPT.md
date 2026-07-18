# Agent setup prompt

Copy everything below into a capable coding agent that can use a terminal.

---

Set up the `X reads from Grok on Hetzner` template end to end.

Your goal is to run scheduled, read-only X monitoring on a Hetzner VPS. Use Grok
Build's built-in X tools as the default retrieval path. Store accepted Markdown
in the private GitHub repository's `main` branch under `raw/x/`.

Start by asking me for any value you cannot discover safely:

1. the GitHub repository created from `sergedoub/x-reads-from-grok-hetzner`
2. the existing Hetzner server name or permission to create one
3. the local path to the Linux Grok Build binary
4. the X queries and account handles I want to monitor
5. the schedule and timezone

Do not ask for secrets in chat. Use existing authenticated CLIs, device login or
the platform's secret input where possible.

Follow these rules:

- inspect before changing anything
- do not install below another application's home directory
- create and use the separate `xreader-worker`, `xreader-grok` and
  `xreader-submit` system users
- keep Grok authentication separate from the GitHub deploy key
- scope the deploy key to one repository and allow writes
- keep post content, checkouts and Grok session files in `/run/x-grok-reader`
- confirm `/run` is tmpfs before enabling the service
- open no ports for this worker
- do not grant access to Tailscale, Docker, other services or other users' homes
- use only the trusted publisher workflow from `main`
- allow candidate branches to add files only below `raw/x/`
- reject changes, deletions, symlinks and same-path different-content collisions
- treat identical content as successful deduplication
- never execute code from a candidate branch
- do not add an automatic X API fallback
- if I choose an X API source, make it an explicit query provider with a separate
  credential and spending boundary

Use the repository's existing scripts rather than reimplementing them. Read
`SETUP.md`, then:

1. verify `gh`, `hcloud`, SSH and Grok Build prerequisites
2. confirm the target repository is private if the collected posts are private
3. configure `config/queries.toml`
4. run the offline tests
5. copy the template and Grok binary to the VPS
6. run `scripts/install.sh` with the exact target repository SSH URL
7. set the repository variable `X_READER_ENABLED=true`
8. add the printed public key as a write-enabled deploy key on only that repo
9. complete Grok device authentication as `xreader-grok`
10. run one search directly and show its structured JSON result
11. run the systemd service manually
12. dispatch the trusted publisher workflow if the schedule has not picked up
    the candidate
13. verify matching hashes on `main`
14. verify the candidate branch is gone after publication
15. verify `python3 -m unittest discover -v` passes
16. verify `/run/x-grok-reader` contains no post content after the run
17. enable the timer only after every check passes

Finish with a concise report containing:

- the server and repository used
- the installed Grok Build version
- the enabled queries and timer schedule
- the candidate and `main` commit IDs from the test run
- one redacted raw Markdown example
- the health JSON
- proof that no runtime content remains on the VPS
- any manual action still required

Stop instead of weakening a security boundary. If a command or flag differs in
the installed Grok Build version, inspect the local CLI help and adapt the
template. Record the compatibility change in the repository.

---
