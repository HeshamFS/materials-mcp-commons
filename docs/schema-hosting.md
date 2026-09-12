# Canonical schema hosting

Materials MCP Profile schemas use permanent, exact-version identifiers under:

`https://schemas.autonomouslab.io/materials-mcp/`

A canonical resource URL has this form:

`https://schemas.autonomouslab.io/materials-mcp/{profile-version}/{resource-name}.schema.json`

A plugin-owned schema uses the separate exact-version form:

`https://schemas.autonomouslab.io/materials-mcp/plugins/{plugin}/{schema-version}/{resource-name}.schema.json`

For example:

`https://schemas.autonomouslab.io/materials-mcp/0.1.0/result-bundle.schema.json`

The core 0.1.0 inventory is:

`https://schemas.autonomouslab.io/materials-mcp/0.1.0/schema-index.json`

There is no mutable `latest` route. Canonical root identifiers contain no query string or fragment.

## Source of truth and integrity

Each checked-in exact-version directory is an authoring source. The published
[0.1.0 directory](../schemas/0.1.0/README.md) and
[schema index](../schemas/0.1.0/schema-index.json) remain immutable. The
[0.2.0 successor](../schemas/0.2.0/README.md) has its own index. Plugin schemas
are checksummed by their embedded declarative manifest; their authored and
embedded copies must match exactly. Source presence never establishes hosted
publication: the current support/evidence record must also identify a clean
deployment commit and passing live parity checks.

The host is a byte-preserving distribution boundary. Deployment must not generate, transform, or rewrite schema content. Once an exact-version resource is publicly distributed, changing its bytes or meaning requires a new profile version rather than an overwrite.

Network availability is not part of validation correctness. Consumers pre-register supported schemas locally and fail closed on missing references or extension schemas.

## Cloudflare deployment boundary

The repository includes a dedicated Worker deployment under [`deployment/cloudflare-schema-host/`](../deployment/cloudflare-schema-host/README.md). It:

- routes only exact core and plugin schema paths beneath `/materials-mcp/`;
- stages only core-indexed and plugin-manifest-checksummed resources into a
  dedicated ignored asset directory;
- rejects aliases, encoded delimiters and traversal, extra path segments, and unknown resources;
- allows `GET`, `HEAD`, and `OPTIONS`, returning `405` with an `Allow` header for other methods;
- serves schemas as `application/schema+json` and the index as `application/json`;
- applies one-year immutable caching to successful exact-version resources;
- enables cross-origin reads and `nosniff`; and
- uses a custom domain scoped to `schemas.autonomouslab.io`, leaving the apex site outside the route.

The public hostname is considered operational only after a live deployment passes the verification checklist below. Repository configuration alone is not evidence that DNS, TLS, routing, or content parity is working.

## Local verification

From `deployment/cloudflare-schema-host/`:

```console
npm ci
npx wrangler types --include-runtime false
npm run test
npm run prepare-assets
npm run typecheck
npm run check
```

`npm run check` performs a Wrangler dry run. It does not deploy.

For a local HTTP check:

```console
npx wrangler dev --local
```

Request a canonical exact-version path from the printed local origin, then verify missing, alias, encoded-delimiter, traversal, and unsupported-method paths as well.

Cloudflare normalizes percent-encoding of RFC 3986 unreserved characters before the Worker handles a request. An equivalent spelling such as an encoded ASCII letter or full stop can therefore resolve to the same resource. This does not change the canonical `$id`. Encoded path delimiters, traversal, backslashes, extra segments, and double-encoded traversal must still fail closed.

## Deployment and live acceptance

Deployment requires the domain owner's authenticated Cloudflare account:

```console
npm run deploy
```

After deployment:

1. fetch every core resource listed in each deployed `schema-index.json` and
   every plugin resource listed in its checksum-bound declarative manifest;
2. require HTTP 200 and the declared media type;
3. compare each response body SHA-256 with the index and checked-in source;
4. verify immutable cache, CORS, cross-origin-resource, and `nosniff` headers;
5. verify `HEAD` and `OPTIONS`;
6. verify unknown versions/resources, `latest`, encoded delimiters/traversal, and extra segments return 404, while recording any edge normalization of unreserved characters;
7. verify unsupported methods return 405 with the allowed methods; and
8. verify the existing apex site remains reachable and unchanged.

If any body differs from its pinned digest, the hosted resource must not be used as release evidence. Roll back the deployment behavior or publish a corrected new profile version; never silently replace an already published exact-version schema.
