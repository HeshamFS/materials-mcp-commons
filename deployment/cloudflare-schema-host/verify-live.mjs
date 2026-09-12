import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const deploymentRoot = dirname(fileURLToPath(import.meta.url));
const publicRoot = resolve(deploymentRoot, "../..");
const schemaOrigin = "https://schemas.autonomouslab.io";
const apexUrl = "https://autonomouslab.io/";

function fail(message) {
  throw new Error(message);
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function argumentsFrom(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--capture-apex") {
      values.set(key, true);
      continue;
    }
    const value = argv[index + 1];
    if (!key.startsWith("--") || value === undefined || value.startsWith("--")) {
      fail(`Invalid argument at ${key}`);
    }
    values.set(key, value);
    index += 1;
  }
  return values;
}

async function json(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function fetchBytes(url, options = {}) {
  const response = await fetch(url, { redirect: "follow", ...options });
  return { response, bytes: Buffer.from(await response.arrayBuffer()) };
}

function requireHeader(response, name, predicate) {
  const value = response.headers.get(name);
  if (value === null || !predicate(value)) {
    fail(`${response.url} has invalid ${name}: ${value}`);
  }
}

async function verifyResource(pathname, source, expectedSha256, mediaType) {
  const sourceBytes = await readFile(source);
  if (sha256(sourceBytes) !== expectedSha256) {
    fail(`Committed source digest differs for ${source}`);
  }
  const { response, bytes } = await fetchBytes(`${schemaOrigin}${pathname}`);
  if (response.status !== 200 || sha256(bytes) !== expectedSha256 || !bytes.equals(sourceBytes)) {
    fail(`Live body differs for ${pathname}`);
  }
  requireHeader(response, "content-type", (value) => value.startsWith(mediaType));
  requireHeader(
    response,
    "cache-control",
    (value) => value.includes("max-age=31536000") && value.includes("immutable"),
  );
  requireHeader(response, "access-control-allow-origin", (value) => value === "*");
  requireHeader(response, "cross-origin-resource-policy", (value) => value === "cross-origin");
  requireHeader(response, "x-content-type-options", (value) => value === "nosniff");
}

async function verifyCore(version) {
  const root = join(publicRoot, "schemas", version);
  const indexPath = join(root, "schema-index.json");
  const index = await json(indexPath);
  const indexBytes = await readFile(indexPath);
  await verifyResource(
    `/materials-mcp/${version}/schema-index.json`,
    indexPath,
    sha256(indexBytes),
    "application/json",
  );
  for (const resource of index.resources) {
    await verifyResource(
      `/materials-mcp/${version}/${resource.path}`,
      join(root, resource.path),
      resource.sha256,
      resource.media_type,
    );
  }
  return index.resources.length + 1;
}

async function verifyPlugin() {
  const pluginRoot = join(publicRoot, "plugins", "optimade");
  const manifest = await json(
    join(pluginRoot, "src", "materials_mcp_optimade", "declarative", "manifest.json"),
  );
  for (const resource of manifest.schema_resources) {
    const filename = resource.path.slice("schemas/".length);
    await verifyResource(
      `/materials-mcp/plugins/optimade/0.1.0/${filename}`,
      join(pluginRoot, "schemas", "0.1.0", filename),
      resource.sha256,
      resource.media_type,
    );
  }
  return manifest.schema_resources.length;
}

async function verifyMethods() {
  const paths = [
    "/materials-mcp/0.2.0/common.schema.json",
    "/materials-mcp/plugins/optimade/0.1.0/search-result.schema.json",
  ];
  for (const pathname of paths) {
    const head = await fetch(`${schemaOrigin}${pathname}`, { method: "HEAD", redirect: "manual" });
    if (head.status !== 200 || (await head.arrayBuffer()).byteLength !== 0) {
      fail(`HEAD failed for ${pathname}`);
    }
    const options = await fetch(`${schemaOrigin}${pathname}`, {
      method: "OPTIONS",
      redirect: "manual",
    });
    if (options.status !== 204 || options.headers.get("allow") !== "GET, HEAD, OPTIONS") {
      fail(`OPTIONS failed for ${pathname}`);
    }
  }
  const post = await fetch(`${schemaOrigin}${paths[1]}`, { method: "POST", redirect: "manual" });
  if (post.status !== 405 || post.headers.get("allow") !== "GET, HEAD, OPTIONS") {
    fail("Unsupported-method rejection failed");
  }
}

async function verifyNegativePaths() {
  const paths = [
    "/",
    "/materials-mcp/latest/common.schema.json",
    "/materials-mcp/0.3.0/common.schema.json",
    "/materials-mcp/0.2.0/unknown.schema.json",
    "/materials-mcp/0.2.0/common.schema.json/extra",
    "/materials-mcp/0.2.0/%252e%252e%252fcommon.schema.json",
    "/materials-mcp/0.2.0/%2fcommon.schema.json",
    "/materials-mcp/plugins/optimade/latest/search-result.schema.json",
    "/materials-mcp/plugins/optimade/0.1.0/manifest.json",
    "/materials-mcp/plugins/unknown/0.1.0/search-result.schema.json",
  ];
  for (const pathname of paths) {
    const response = await fetch(`${schemaOrigin}${pathname}`, { redirect: "manual" });
    if (response.status !== 404) {
      fail(`Negative path returned ${response.status}: ${pathname}`);
    }
  }
  return paths.length;
}

async function apexObservation() {
  const { response, bytes } = await fetchBytes(apexUrl);
  if (response.status !== 200) {
    fail(`Apex returned ${response.status}`);
  }
  return { status: response.status, sha256: sha256(bytes), final_url: response.url };
}

async function emit(document, output) {
  const rendered = `${JSON.stringify(document, null, 2)}\n`;
  if (typeof output === "string") {
    await writeFile(output, rendered, "utf8");
  } else {
    process.stdout.write(rendered);
  }
}

const args = argumentsFrom(process.argv.slice(2));
const output = args.get("--output");
if (args.has("--capture-apex")) {
  await emit({ observed_at: new Date().toISOString(), apex: await apexObservation() }, output);
} else {
  const commit = args.get("--commit");
  const expectedApexSha256 = args.get("--apex-sha256");
  if (typeof commit !== "string" || !/^[a-f0-9]{40}$/.test(commit)) {
    fail("--commit must be a complete lowercase Git commit");
  }
  if (typeof expectedApexSha256 !== "string" || !/^[a-f0-9]{64}$/.test(expectedApexSha256)) {
    fail("--apex-sha256 must be a lowercase SHA-256 digest captured before deployment");
  }
  const coreCounts = await Promise.all([verifyCore("0.1.0"), verifyCore("0.2.0")]);
  const pluginCount = await verifyPlugin();
  await verifyMethods();
  const negativePaths = await verifyNegativePaths();
  const apex = await apexObservation();
  if (apex.sha256 !== expectedApexSha256) {
    fail("Apex body changed across schema-host deployment");
  }
  await emit(
    {
      report_version: 1,
      observed_at: new Date().toISOString(),
      deployment_commit: commit,
      schema_origin: schemaOrigin,
      core_resources: coreCounts.reduce((total, count) => total + count, 0),
      plugin_resources: pluginCount,
      negative_paths: negativePaths,
      methods: ["GET", "HEAD", "OPTIONS", "POST-rejected"],
      apex,
      result: "pass",
    },
    output,
  );
}
