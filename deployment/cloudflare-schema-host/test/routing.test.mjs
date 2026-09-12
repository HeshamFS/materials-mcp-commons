import assert from "node:assert/strict";
import test from "node:test";

import { canonicalResource } from "../routing.js";

test("accepts exact core and plugin schema paths without rewriting", () => {
  const accepted = [
    "/materials-mcp/0.1.0/schema-index.json",
    "/materials-mcp/0.2.0/result-bundle.schema.json",
    "/materials-mcp/plugins/optimade/0.1.0/search-result.schema.json",
    "/materials-mcp/plugins/optimade/0.1.0/record-identity.extension.schema.json",
  ];
  for (const pathname of accepted) {
    assert.equal(canonicalResource(pathname), pathname);
  }
});

test("rejects aliases, traversal spellings, malformed versions, and extra segments", () => {
  const rejected = [
    "/",
    "/materials-mcp/latest/result-bundle.schema.json",
    "/materials-mcp/0.2/result-bundle.schema.json",
    "/materials-mcp/0.2.0/../result-bundle.schema.json",
    "/materials-mcp/0.2.0/%2e%2e%2fresult-bundle.schema.json",
    "/materials-mcp/0.2.0/result-bundle.schema.json/extra",
    "/materials-mcp/plugins/optimade/latest/search-result.schema.json",
    "/materials-mcp/plugins/optimade/0.1.0/manifest.json",
    "/materials-mcp/plugins/optimade/0.1.0/schema-index.json",
    "/materials-mcp/plugins/optimade/0.1.0/search_result.schema.json",
  ];
  for (const pathname of rejected) {
    assert.equal(canonicalResource(pathname), null);
  }
});
