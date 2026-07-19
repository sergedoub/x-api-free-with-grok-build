# Set up the reader

These commands create a private content repository from the public template,
install the worker on an existing Hetzner VPS and prove one complete run.

Replace every value in angle brackets before running a command.

## Create the repository

Run this on your computer:

```bash
gh repo create <owner>/<repo> \
  --private \
  --template sergedoub/x-api-free-with-grok-build \
  --clone
cd <repo>
```

Edit `config/queries.toml`. Enable at least one query, then run the tests:

```bash
python3 -m unittest discover -v
git add config/queries.toml
git commit -m "config: add X monitors"
git push origin main
gh variable set X_READER_ENABLED --body true --repo <owner>/<repo>
```

The repository variable activates the publisher in repositories created from
the template. The public template repository leaves it unset.

## Prepare a Hetzner server

Use an existing Ubuntu 24.04 server or create one. Creating a server starts
billing on your Hetzner account.

```bash
hcloud server create \
  --name <server-name> \
  --type cx23 \
  --image ubuntu-24.04 \
  --location nbg1 \
  --ssh-key <ssh-key-name>
hcloud server describe <server-name>
```

Do not open an inbound port for the reader. SSH access is enough for setup.

## Copy and install the worker

Install or download the Linux Grok Build binary using the current
[official Grok Build instructions](https://docs.x.ai/build/overview). Confirm it
runs before copying it.

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

The installer prints a deploy key. Save it locally and add it only to the new
repository:

```bash
ssh root@<server-ip> \
  "cat /var/lib/xreader-submit/.ssh/id_ed25519.pub" \
  > /tmp/xreader-deploy-key.pub

gh repo deploy-key add /tmp/xreader-deploy-key.pub \
  --repo <owner>/<repo> \
  --title "Hetzner X reader" \
  --allow-write
```

## Authenticate Grok Build

Run the device login in an interactive SSH session:

```bash
ssh -t root@<server-ip> \
  "sudo -u xreader-grok /usr/local/libexec/xreader-grok-login"
```

Open the displayed URL and complete authentication. The helper stores only the
Grok authentication file in `/var/lib/xreader-grok`.

## Test one complete run

Run the service manually:

```bash
ssh root@<server-ip> "systemctl start x-grok-reader.service"
ssh root@<server-ip> "systemctl status x-grok-reader.service --no-pager"
ssh root@<server-ip> "cat /var/lib/xreader-worker/health.json"
```

The candidate publisher runs every 5 minutes, but GitHub schedules can be late.
Dispatch it manually during setup if needed:

```bash
gh workflow run publish-ingest-candidate.yml --repo <owner>/<repo> --ref main
gh run watch --repo <owner>/<repo> --exit-status
```

Confirm the accepted files are on `main` and the runtime is empty:

```bash
git pull --ff-only
find raw/x -type f -name '*.md' -print

ssh root@<server-ip> \
  "find /run/x-grok-reader -mindepth 1 -print; systemctl list-timers x-grok-reader.timer"
```

The `find` command on the VPS must print no post, checkout or session files.

## Enable the timer

Enable the timer only after the complete test succeeds:

```bash
ssh root@<server-ip> \
  "systemctl enable --now x-grok-reader.timer && systemctl list-timers x-grok-reader.timer"
```

The default timer runs every 4 hours with a random delay of up to 10 minutes.
Edit `systemd/x-grok-reader.timer`, reinstall and test again to change it.

## Add an X API source

Read [`docs/x-api.md`](docs/x-api.md) before adding a metered source. Keep the
provider explicit. Do not fall back to the X API when Grok fails.
