import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const deploymentRoot = dirname(fileURLToPath(import.meta.url));
const publicRoot = resolve(deploymentRoot, "../..");
const assetRoot = join(deploymentRoot, ".schema-host-assets");
const canonicalOrigin = "https://schemas.autonomouslab.io";
const profileVersions = ["0.1.0", "0.2.0"];
const plugin = {
  name: "optimade",
  schemaVersion: "0.1.0",
  root: join(publicRoot, "plugins", "optimade"),
};

function fail(message) {
  throw new Error(message);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function json(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function copyVerified(source, destination, expectedSha256) {
  const bytes = await readFile(source);
  const actualSha256 = sha256(bytes);
  if (actualSha256 !== expectedSha256) {
    fail(`SHA-256 mismatch for ${source}`);
  }
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, bytes, { flag: "wx" });
}

async function stageProfile(version) {
  const sourceRoot = join(publicRoot, "schemas", version);
  const indexPath = join(sourceRoot, "schema-index.json");
  const index = await json(indexPath);
  const expectedBase = `${canonicalOrigin}/materials-mcp/${version}/`;
  if (index.profile_version !== version || index.canonical_base !== expectedBase) {
    fail(`Profile ${version} index identity is inconsistent`);
  }
  if (!Array.isArray(index.resources)) {
    fail(`Profile ${version} index has no resource array`);
  }

  const destinationRoot = join(assetRoot, "materials-mcp", version);
  const indexBytes = await readFile(indexPath);
  await mkdir(destinationRoot, { recursive: true });
  await writeFile(join(destinationRoot, "schema-index.json"), indexBytes, { flag: "wx" });
  for (const resource of index.resources) {
    if (
      typeof resource.path !== "string" ||
      resource.path.includes("/") ||
      resource.path.includes("\\") ||
      resource.schema_id !== `${expectedBase}${resource.path}` ||
      resource.media_type !== "application/schema+json" ||
      typeof resource.sha256 !== "string"
    ) {
      fail(`Profile ${version} contains an invalid indexed resource`);
    }
    await copyVerified(
      join(sourceRoot, resource.path),
      join(destinationRoot, resource.path),
      resource.sha256,
    );
  }
  return index.resources.length + 1;
}

async function stagePlugin() {
  const manifestPath = join(
    plugin.root,
    "src",
    "materials_mcp_optimade",
    "declarative",
    "manifest.json",
  );
  const manifest = await json(manifestPath);
  const expectedPluginId = `${canonicalOrigin}/materials-mcp/plugins/${plugin.name}`;
  const expectedBase = `${expectedPluginId}/${plugin.schemaVersion}/`;
  if (
    manifest.plugin_id !== expectedPluginId ||
    manifest.profile_version !== "0.2.0" ||
    !Array.isArray(manifest.schema_resources)
  ) {
    fail("Plugin manifest identity or core-profile dependency is inconsistent");
  }

  const destinationRoot = join(
    assetRoot,
    "materials-mcp",
    "plugins",
    plugin.name,
    plugin.schemaVersion,
  );
  for (const resource of manifest.schema_resources) {
    if (
      typeof resource.path !== "string" ||
      !resource.path.startsWith("schemas/") ||
      resource.path.slice("schemas/".length).includes("/") ||
      resource.schema_id !== `${expectedBase}${resource.path.slice("schemas/".length)}` ||
      resource.media_type !== "application/schema+json" ||
      typeof resource.sha256 !== "string"
    ) {
      fail("Plugin manifest contains an invalid schema resource");
    }
    const filename = resource.path.slice("schemas/".length);
    const source = join(plugin.root, "schemas", plugin.schemaVersion, filename);
    const embedded = join(
      plugin.root,
      "src",
      "materials_mcp_optimade",
      "declarative",
      resource.path,
    );
    const [sourceBytes, embeddedBytes] = await Promise.all([readFile(source), readFile(embedded)]);
    if (!sourceBytes.equals(embeddedBytes)) {
      fail(`Plugin source and embedded schema differ for ${filename}`);
    }
    await copyVerified(source, join(destinationRoot, filename), resource.sha256);
  }
  return manifest.schema_resources.length;
}

if (resolve(assetRoot) !== resolve(deploymentRoot, ".schema-host-assets")) {
  fail("Refusing to stage outside the dedicated deployment asset directory");
}
await rm(assetRoot, { recursive: true, force: true });
const profileCounts = await Promise.all(profileVersions.map(stageProfile));
const pluginCount = await stagePlugin();
console.log(
  `Prepared ${profileCounts.reduce((total, count) => total + count, 0)} core and ${pluginCount} plugin schema assets.`,
);
