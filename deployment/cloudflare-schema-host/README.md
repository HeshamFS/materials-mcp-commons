# Cloudflare schema host

This isolated deployment boundary serves the checked-in schema sources at their canonical identifiers without copying or rewriting them. The Worker maps

`/materials-mcp/{exact-version}/{resource}`

to the matching file under [`../../schemas`](../../schemas), rejects aliases and unexpected paths, and adds immutable caching, CORS, and schema media-type headers.

The custom domain is `schemas.autonomouslab.io`. Cloudflare manages its DNS record and certificate when the Worker is deployed. The main `autonomouslab.io` site is outside this deployment's route and is not changed.

The public hostname is not considered operational merely because this configuration exists. Live status requires body-digest, header, negative-route, TLS, and apex-isolation verification. The complete acceptance checklist is in [`../../docs/schema-hosting.md`](../../docs/schema-hosting.md).

## Verify and deploy

From this directory:

```text
npm ci
npx wrangler types --include-runtime false
npm run typecheck
npm run check
npm run deploy
```

The first four commands install/check locally; `npm run deploy` is an external production change. Run deployment only with the domain owner's authenticated Cloudflare account. After deployment, compare every hosted exact-version resource with [`../../schemas/0.1.0/schema-index.json`](../../schemas/0.1.0/schema-index.json) and verify `Content-Type`, cache, CORS, allowed methods, unknown paths, encoded delimiters and traversal, and the unaffected apex site.

Wrangler is pinned in `package-lock.json`; update it deliberately and repeat local plus live verification before deployment.
