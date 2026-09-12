# Cloudflare schema host

This isolated deployment boundary serves the checked-in core and plugin schema
sources at their canonical identifiers without rewriting their bytes. The
Worker maps

`/materials-mcp/{exact-version}/{resource}`

and

`/materials-mcp/plugins/{plugin}/{exact-version}/{resource}`

to a dedicated generated asset tree. `prepare-assets.mjs` copies only resources
listed in the core schema indexes and the checksum-bound plugin manifest,
verifies every digest, and requires the authored and embedded plugin schemas to
be byte-identical. The Worker rejects aliases and unexpected paths and adds
immutable caching, CORS, and schema media-type headers.

The custom domain is `schemas.autonomouslab.io`. Cloudflare manages its DNS record and certificate when the Worker is deployed. The main `autonomouslab.io` site is outside this deployment's route and is not changed.

The public hostname is not considered operational merely because this configuration exists. Live status requires body-digest, header, negative-route, TLS, and apex-isolation verification. The complete acceptance checklist is in [`../../docs/schema-hosting.md`](../../docs/schema-hosting.md).

## Verify and deploy

From this directory:

```text
npm ci
npx wrangler types --include-runtime false
npm run test
npm run prepare-assets
npm run typecheck
npm run check
npm run deploy
```

All commands except `npm run deploy` install, stage, or check locally;
`npm run deploy` is an external production change. Run deployment only with the
domain owner's authenticated Cloudflare account and from a clean committed
public archive. After deployment, compare every hosted core resource with its
schema index and every plugin resource with its declarative-manifest checksum;
also verify `Content-Type`, cache, CORS, allowed methods, unknown paths, encoded
delimiters and traversal, and the unaffected apex site. Adding a source
directory does not publish it; each new exact version needs its own clean
deployment and live-parity evidence.

Capture the apex body digest immediately before deployment, then run the
checked live verifier afterward with the full deployment commit and captured
digest. Invoke `node verify-live.mjs` directly so argument forwarding is
identical across npm shell configurations. The accepted invocation shapes are documented in
[`../../docs/schema-hosting.md`](../../docs/schema-hosting.md).

Wrangler is pinned in `package-lock.json`; update it deliberately and repeat local plus live verification before deployment.
