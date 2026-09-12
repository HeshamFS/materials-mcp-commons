const CANONICAL_PREFIX = "/materials-mcp/";
const EXACT_VERSION = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;
const PLUGIN_NAME = /^[a-z][a-z0-9-]*$/;
const SCHEMA_RESOURCE = /^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*\.schema\.json$/;

/**
 * Map one exact canonical schema path to the identically named staged asset.
 * Asset existence remains authoritative; syntactically valid unknown paths get
 * a 404 from the static-assets binding.
 *
 * @param {string} pathname
 * @returns {string | null}
 */
export function canonicalResource(pathname) {
  if (pathname.includes("%") || !pathname.startsWith(CANONICAL_PREFIX)) {
    return null;
  }

  const parts = pathname.split("/");
  const coreResource =
    parts.length === 4 &&
    parts[0] === "" &&
    parts[1] === "materials-mcp" &&
    EXACT_VERSION.test(parts[2]) &&
    (SCHEMA_RESOURCE.test(parts[3]) || parts[3] === "schema-index.json");
  const pluginResource =
    parts.length === 6 &&
    parts[0] === "" &&
    parts[1] === "materials-mcp" &&
    parts[2] === "plugins" &&
    PLUGIN_NAME.test(parts[3]) &&
    EXACT_VERSION.test(parts[4]) &&
    SCHEMA_RESOURCE.test(parts[5]);

  return coreResource || pluginResource ? pathname : null;
}
