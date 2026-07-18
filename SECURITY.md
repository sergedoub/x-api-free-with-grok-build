# Security policy

## Report a vulnerability

Do not open a public issue for a vulnerability that could expose credentials or
private X content. Use GitHub's private vulnerability reporting for this
repository.

## Security assumptions

The template assumes:

- the VPS host and root account are trusted
- the GitHub repository is the durable source of truth
- candidate branches are untrusted input
- Grok output is untrusted data
- collected X content may be private even when this template is public

Do not commit Grok authentication, deploy keys, X API credentials, query files
containing secrets or collected raw content to this public template.
