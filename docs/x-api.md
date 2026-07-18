# Add the X API as an explicit source

The template uses Grok Build by default. Add the X API only when you need a
feature or response contract that the built-in X tools do not provide.

Keep these boundaries:

- select the provider in configuration for each query
- store X API credentials separately from Grok and Git credentials
- set a request and spending limit
- normalize API responses to the same Markdown contract under `raw/x/`
- use the same candidate branch and trusted publisher
- fail the run when the selected provider fails
- never switch providers automatically

Automatic fallback can hide outages and create an unexpected API bill. It can
also produce different bytes for an existing raw path, which the publisher will
correctly reject as a collision.

This repository does not include an X API client. Add one as a separate adapter
and test it offline with recorded, redacted fixtures.
