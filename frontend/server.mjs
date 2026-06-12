import { createReadStream, existsSync } from "node:fs";
import { stat } from "node:fs/promises";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const distDir = path.join(__dirname, "dist");
const port = Number(process.env.PORT || 3000);
const ingestApiUrl = new URL(process.env.INGEST_API_URL || "http://localhost:8000");

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

const sendStatic = async (req, res) => {
  const requestUrl = new URL(req.url || "/", "http://localhost");
  const normalizedPath = path
    .normalize(decodeURIComponent(requestUrl.pathname))
    .replace(/^(\.\.[/\\])+/, "");
  let filePath = path.join(distDir, normalizedPath === "/" ? "index.html" : normalizedPath);

  if (!filePath.startsWith(distDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  if (!existsSync(filePath) || !(await stat(filePath)).isFile()) {
    filePath = path.join(distDir, "index.html");
  }

  const ext = path.extname(filePath);
  res.writeHead(200, {
    "Content-Type": contentTypes[ext] || "application/octet-stream",
  });
  createReadStream(filePath).pipe(res);
};

const proxyApi = (req, res) => {
  const requestUrl = new URL(req.url || "/", ingestApiUrl);
  const options = {
    hostname: ingestApiUrl.hostname,
    port: ingestApiUrl.port || (ingestApiUrl.protocol === "https:" ? 443 : 80),
    path: `${requestUrl.pathname}${requestUrl.search}`,
    protocol: ingestApiUrl.protocol,
    method: req.method,
    headers: {
      ...req.headers,
      host: ingestApiUrl.host,
    },
  };

  const requestClient = ingestApiUrl.protocol === "https:" ? https : http;
  const proxyRequest = requestClient.request(options, (proxyResponse) => {
    res.writeHead(proxyResponse.statusCode || 502, proxyResponse.headers);
    proxyResponse.pipe(res);
  });

  proxyRequest.on("error", (error) => {
    res.writeHead(502, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: `Failed to reach ingest API: ${error.message}` }));
  });

  req.pipe(proxyRequest);
};

const server = http.createServer((req, res) => {
  if ((req.url || "").startsWith("/api/")) {
    proxyApi(req, res);
    return;
  }

  sendStatic(req, res).catch((error) => {
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: error.message }));
  });
});

server.listen(port, "0.0.0.0", () => {
  console.log(`Frontend serving on :${port}, proxying /api to ${ingestApiUrl.href}`);
});
