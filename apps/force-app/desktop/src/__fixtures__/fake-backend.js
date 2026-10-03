// Minimal HTTP fixture standing in for the real recorder backend in sidecar tests.
// Args: <port> [--delay=<ms>] [--chatty=<bytes>] [--hang-after=<ms>]
//   delay:      how long /health returns 503 before flipping to 200
//   chatty:     bytes written to stdout per request, synchronously, as uvicorn's access log is:
//               once nobody drains the pipe, that write blocks the whole server (#106)
//   hang-after: block the event loop for good after this long, as a wedged backend would
const fs = require('node:fs');
const http = require('node:http');

const port = Number(process.argv[2]);
const arg = (name) => {
  const a = process.argv.find((x) => x.startsWith(`--${name}=`));
  return a ? Number(a.split('=')[1]) : 0;
};
const delayMs = arg('delay');
const chattyBytes = arg('chatty');
const hangAfterMs = arg('hang-after');
const startedAt = Date.now();
const line = chattyBytes ? Buffer.alloc(chattyBytes, 'x') : null;

const server = http.createServer((req, res) => {
  if (line) fs.writeSync(1, line);
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

if (hangAfterMs) {
  setTimeout(() => {
    for (;;) {
      /* wedged */
    }
  }, hangAfterMs);
}
