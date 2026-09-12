# Runtime dependencies and licenses

The integration installs from the exact `uv.lock` graph. The checked Windows
CPython 3.12 inventory is generated from installed distribution metadata and is
committed at
[`conformance/dependency-inventory-windows-py312.json`](../conformance/dependency-inventory-windows-py312.json).
Its generator traverses only production requirements, fails when a dependency
is absent, and fails when it cannot derive a bounded license expression.

Release lifecycle evidence builds the engine and integration only from a safe
`git archive HEAD` extraction. This keeps line endings, package members, and
artifact hashes tied to the committed public source instead of an ambient
working-tree representation.

The direct runtime boundary is deliberately small:

- `materials-mcp-commons==0.1.0a13` under Apache-2.0; and
- `optimade==1.5.0` under MIT.

The optional `mcp-host` extra adds `mcp>=2.2,<2.3` for the standalone stdio
server. It is not part of the default runtime graph. Development installs also
carry it so the actual wire contract can be exercised in tests.

The complete checked row records 24 root, direct, and transitive distributions,
their exact installed versions, relationships, license expressions, target
interpreter/platform, and the SHA-256 of the lock that selected them. Regenerate
it only from a fresh environment installed with the checked lock:

```console
uv run --locked python tools/build_dependency_inventory.py \
  --output conformance/dependency-inventory-windows-py312.json
```

License compatibility and vulnerability scanning are separate checks. A clean
known-vulnerability scan is evidence for one lock at one time; it is not a
permanent security claim. Time-bound platform and live-provider observations
are recorded in the checked
[`support matrix`](../conformance/support-matrix.json); release-candidate audit
evidence additionally records its scanner, database date, lock digest, and
result.

The upstream package currently brings `requests` transitively. It is not used as
network authority by this integration: runtime egress is confined to the
project-owned fixed-provider transport.

The upstream OPTIMADE models currently emit a Pydantic 2.11+ deprecation warning
while validating authentic responses. The locked combination passes the support
matrix; the warning is retained as upgrade risk and is not suppressed as though
it were resolved.
