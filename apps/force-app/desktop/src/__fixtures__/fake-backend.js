// Minimal HTTP fixture standing in for the real recorder backend in sidecar tests.
// Args: <port> [--delay=<ms>]  (delay: how long /health returns 503 before flipping to 200)
const http = require('node:http');

const port = Number(process.argv[2]);
const delayArg = process.argv.find((a) => a.startsWith('--delay='));
const delayMs = delayArg ? Number(delayArg.split('=')[1]) : 0;
const startedAt = Date.now();

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    if (Date.now() - startedAt < delayMs) {
      res.writeHead(503).end();
      return;
    }
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ ok: true }));
    return;
  }
  res.writeHead(404).end();
});
server.listen(port);
