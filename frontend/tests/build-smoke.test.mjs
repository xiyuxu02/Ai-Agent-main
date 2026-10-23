import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendDirectory = fileURLToPath(new URL("..", import.meta.url));
const distributionDirectory = path.join(frontendDirectory, "dist");

test("the production bundle contains a mount point and referenced assets", async () => {
  const indexPath = path.join(distributionDirectory, "index.html");
  const indexHtml = await readFile(indexPath, "utf8");

  assert.match(indexHtml, /<div id="root"><\/div>/);

  const assetPaths = [...indexHtml.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)]
    .map((match) => match[1]);

  assert.ok(assetPaths.length > 0, "the bundle should reference at least one asset");

  await Promise.all(
    assetPaths.map((assetPath) =>
      access(path.join(distributionDirectory, assetPath.replace(/^\//, ""))),
    ),
  );
});
