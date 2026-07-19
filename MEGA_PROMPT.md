# Agent setup prompt

Copy everything below into a capable coding agent that can use a terminal.

---

Set up `X API-free with Grok Build` end to end.

The goal is to run scheduled, read-only X monitoring on a Hetzner VPS. Use Grok
Build's built-in X tools as the default retrieval path. Store accepted Markdown
in the destination GitHub repository's `main` branch under `raw/x/`.

Perform the setup for me. Do not merely describe the commands. Pause only when
I must complete an authentication or billing step, or when a required value
cannot be discovered safely.

Start by resolving these values:

1. the destination GitHub repository, or permission to create a private one
   from `sergedoub/x-api-free-with-grok-build`
2. the existing Hetzner server, or permission to create one
3. the local path to the Linux Grok Build binary
4. the X queries and account handles to monitor
5. the schedule and timezone

Do not ask for secrets in chat. Use existing authenticated CLIs, device login or
the platform's secret input where possible. Creating a Hetzner server starts
billing, so obtain permission immediately before doing that if no server exists.

## Non-negotiable rules

- inspect before changing anything
- replace every angle-bracket placeholder with a verified value before running
  a command
- do not install below another application's home directory
- create and use the separate `xreader-worker`, `xreader-grok` and
  `xreader-submit` system users
- keep Grok authentication separate from the GitHub deploy key
- scope the deploy key to one repository and allow writes
- keep post content, checkouts and Grok session files in `/run/x-grok-reader`
- confirm `/run` is tmpfs before enabling the service
- open no ports for this worker; SSH access is enough for setup
- do not grant access to Tailscale, Docker, other services or other users' homes
- use only the trusted publisher workflow from `main`
- allow candidate branches to add files only below `raw/x/`
- reject changes, deletions, symlinks and same-path different-content collisions
- treat identical content as successful deduplication
- never execute code from a candidate branch
- do not add an automatic X API fallback
- if an X API source is requested, keep it as an explicit provider with a
  separate credential and spending boundary
- stop instead of weakening a security boundary

Use the repository's existing scripts rather than reimplementing them.

## 1. Verify prerequisites

Verify the authenticated GitHub and Hetzner CLIs, SSH access and the Grok Build
binary before making changes:

```bash
gh auth status
hcloud context active
ssh -V
<path-to-linux-grok> --version
```

The destination host must provide Ubuntu 24.04 or a compatible systemd
distribution, Python 3.11 or later, Git and OpenSSH. No runtime Python packages
are required.

## 2. Create or verify the destination repository

If the destination repository does not exist, create it from the template. Use
a private repository when the collected posts should be private:

```bash
gh repo create <owner>/<repo> \
  --private \
  --template sergedoub/x-api-free-with-grok-build \
  --clone
cd <repo>
```

If it already exists, inspect its remote, visibility and default branch before
continuing. Work from the destination checkout, not the public template.

Configure `config/queries.toml`. Enable at least one query, then verify and
publish that configuration:

```bash
python3 -m unittest discover -v
git add config/queries.toml
git commit -m "config: add X monitors"
git push origin main
gh variable set X_READER_ENABLED --body true --repo <owner>/<repo>
```

The repository variable activates the publisher in repositories created from
the template. Leave it unset in the public template repository.

## 3. Prepare the Hetzner server

Prefer an existing suitable server. If none exists and permission was granted,
create one:

```bash
hcloud server create \
  --name <server-name> \
  --type cx23 \
  --image ubuntu-24.04 \
  --location nbg1 \
  --ssh-key <ssh-key-name>
hcloud server describe <server-name>
```

Verify SSH access. Do not open an inbound port for the reader.

## 4. Copy and install the worker

Install or download the Linux Grok Build binary using the current official
instructions at <https://docs.x.ai/build/overview>. Confirm that the binary runs
before copying it.

From the destination repository checkout, run:

```bash
chmod +x <path-to-linux-grok>
<path-to-linux-grok> --version

rsync -az --delete \
  --exclude .git \
  ./ root@<server-ip>:/tmp/x-grok-reader/
scp <path-to-linux-grok> root@<server-ip>:/tmp/grok

ssh -t root@<server-ip> \
  "cd /tmp/x-grok-reader && ./scripts/install.sh /tmp/x-grok-reader /tmp/grok git@github.com:<owner>/<repo>.git"
```

The installer must create the three system users, verify `/run` is tmpfs,
install the hardened oneshot service and print a public deploy key.

## 5. Install the repository deploy key

Read the generated public key without exposing the private key:

```bash
ssh root@<server-ip> \
  "cat /var/lib/xreader-submit/.ssh/id_ed25519.pub" \
  > /tmp/xreader-deploy-key.pub

gh repo deploy-key add /tmp/xreader-deploy-key.pub \
  --repo <owner>/<repo> \
  --title "Hetzner X reader" \
  --allow-write
```

Confirm the key is attached only to the destination repository.

## 6. Authenticate Grok Build

Run device login in an interactive SSH session:

```bash
ssh -t root@<server-ip> \
  "sudo -u xreader-grok /usr/local/libexec/xreader-grok-login"
```

Ask me to open the displayed URL and complete authentication. Continue only
after the helper confirms success. Authentication must be stored under
`/var/lib/xreader-grok`, readable only by `xreader-grok`.

## 7. Test retrieval and one complete publication

Run one search directly and inspect its structured JSON result. It must use the
configured Grok retrieval path, return the requested schema and contain no
invented fallback data.

Then run the service manually:

```bash
ssh root@<server-ip> "systemctl start x-grok-reader.service"
ssh root@<server-ip> "systemctl status x-grok-reader.service --no-pager"
ssh root@<server-ip> "cat /var/lib/xreader-worker/health.json"
```

The candidate publisher checks every five minutes, but scheduled GitHub Actions
runs can be late. Dispatch it manually during setup if needed:

```bash
gh workflow run publish-ingest-candidate.yml --repo <owner>/<repo> --ref main
gh run watch --repo <owner>/<repo> --exit-status
```

Verify all of the following:

1. the candidate contains only new Markdown below `raw/x/`
2. matching files and SHA-256 hashes are present on `main`
3. the candidate branch is gone after publication
4. the complete offline test suite passes
5. `/run/x-grok-reader` contains no post, checkout or Grok session content after
   the run

Use these checks:

```bash
git pull --ff-only
python3 -m unittest discover -v
find raw/x -type f -name '*.md' -print

ssh root@<server-ip> \
  "find /run/x-grok-reader -mindepth 1 -print; systemctl list-timers x-grok-reader.timer"
```

The remote `find` command must print no runtime content.

## 8. Enable the timer

Enable the timer only after every end-to-end check passes:

```bash
ssh root@<server-ip> \
  "systemctl enable --now x-grok-reader.timer && systemctl list-timers x-grok-reader.timer"
```

The default timer runs every four hours with a random delay of up to ten
minutes. To change it, edit `systemd/x-grok-reader.timer`, reinstall and repeat
the manual end-to-end test before enabling it.

## Runtime paths to verify

| Path | Purpose |
| --- | --- |
| `config/queries.toml` | versioned query configuration |
| `/etc/x-grok-reader/queries.toml` | installed query configuration |
| `/var/lib/xreader-grok/auth.json` | Grok authentication; readable by `xreader-grok` |
| `/var/lib/xreader-submit/.ssh/id_ed25519` | repository deploy key; readable by `xreader-submit` |
| `/run/x-grok-reader` | tmpfs runtime content, temporary checkouts and session homes |
| `/var/lib/xreader-worker/health.json` | last-run health record |
| `raw/x/<query>/` | accepted Markdown in the destination repository |

## Compatibility and optional X API source

If a command or flag differs in the installed Grok Build version, inspect the
local CLI help and adapt the setup. Record the compatibility change in the
destination repository.

Before adding a metered X API source, read `docs/x-api.md`. Keep the provider
explicit and never fall back to the X API when Grok Build fails.

## Completion report

Finish with a concise report containing:

- the server and repository used
- the installed Grok Build version
- the enabled queries and timer schedule
- the candidate and `main` commit IDs from the test run
- one redacted raw Markdown example
- the health JSON
- proof that no runtime content remains on the VPS
- any manual action still required

Do not claim completion until retrieval, trusted publication, hash matching,
runtime cleanup and the enabled timer have all been verified.

---
