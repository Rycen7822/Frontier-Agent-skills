const crypto = require('crypto');
const http = require('http');
const fs = require('fs');
const path = require('path');

// ========== WebSocket Protocol (RFC 6455) ==========

const OPCODES = { CONTINUATION: 0x00, TEXT: 0x01, CLOSE: 0x08, PING: 0x09, PONG: 0x0A };
const WS_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const LIMITS = Object.freeze({ frame: 65536, message: 65536, connectionBuffer: 131072 });

class ProtocolError extends Error {
  constructor(message, closeCode) {
    super(message);
    this.closeCode = closeCode;
  }
}

function computeAcceptKey(clientKey) {
  return crypto.createHash('sha1').update(clientKey + WS_MAGIC).digest('base64');
}

function encodeFrame(opcode, payload) {
  const fin = 0x80;
  const len = payload.length;
  let header;

  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = fin | opcode;
    header[1] = len;
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = fin | opcode;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = fin | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }

  return Buffer.concat([header, payload]);
}

function decodeFrame(buffer) {
  if (buffer.length < 2) return null;

  const firstByte = buffer[0];
  const secondByte = buffer[1];
  const final = (firstByte & 0x80) !== 0;
  const opcode = firstByte & 0x0F;
  const masked = (secondByte & 0x80) !== 0;
  let payloadLen = secondByte & 0x7F;
  let offset = 2;

  if ((firstByte & 0x70) !== 0) throw new ProtocolError('Reserved frame bits are unsupported', 1002);
  if (!masked) throw new ProtocolError('Client frames must be masked', 1002);

  if (payloadLen === 126) {
    if (buffer.length < 4) return null;
    payloadLen = buffer.readUInt16BE(2);
    offset = 4;
  } else if (payloadLen === 127) {
    if (buffer.length < 10) return null;
    const extendedLength = buffer.readBigUInt64BE(2);
    if (extendedLength > BigInt(LIMITS.frame)) {
      throw new ProtocolError('Frame exceeds the payload limit', 1009);
    }
    payloadLen = Number(extendedLength);
    offset = 10;
  }
  if (payloadLen > LIMITS.frame) throw new ProtocolError('Frame exceeds the payload limit', 1009);
  if (opcode >= OPCODES.CLOSE && (!final || payloadLen > 125)) {
    throw new ProtocolError('Invalid control frame', 1002);
  }

  const maskOffset = offset;
  const dataOffset = offset + 4;
  const totalLen = dataOffset + payloadLen;
  if (buffer.length < totalLen) return null;

  const mask = buffer.slice(maskOffset, dataOffset);
  const data = Buffer.alloc(payloadLen);
  for (let i = 0; i < payloadLen; i++) {
    data[i] = buffer[dataOffset + i] ^ mask[i % 4];
  }

  return { final, opcode, payload: data, bytesConsumed: totalLen };
}

function appendConnectionChunk(buffer, chunk) {
  if (buffer.length + chunk.length > LIMITS.connectionBuffer) {
    throw new ProtocolError('Connection buffer exceeds the limit', 1009);
  }
  return Buffer.concat([buffer, chunk]);
}

// ========== Configuration ==========

const PORT = process.env.BRAINSTORM_PORT === undefined ? 0 : Number(process.env.BRAINSTORM_PORT);
const HOST = process.env.BRAINSTORM_HOST || '127.0.0.1';
const URL_HOST = process.env.BRAINSTORM_URL_HOST || (HOST === '127.0.0.1' ? 'localhost' : HOST);
const LISTEN_HOST = HOST === 'localhost' ? '127.0.0.1' : HOST;
const SESSION_DIR = process.env.BRAINSTORM_DIR || '/tmp/brainstorm';
const CONTENT_DIR = path.join(SESSION_DIR, 'content');
const STATE_DIR = path.join(SESSION_DIR, 'state');
const ownerPid = Number(process.env.BRAINSTORM_OWNER_PID);
const allowedHosts = new Set(['127.0.0.1', 'localhost']);

function validateSessionNonce(argv) {
  if (argv.length !== 2 || argv[0] !== '--session-nonce' || !/^[0-9a-f]{64}$/.test(argv[1])) {
    throw new Error('A valid --session-nonce is required');
  }
}

const MIME_TYPES = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml'
};

// ========== Templates and Constants ==========

const WAITING_PAGE = `<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Design Discovery Companion</title>
<style>body { font-family: system-ui, sans-serif; padding: 2rem; max-width: 800px; margin: 0 auto; }
h1 { color: #333; } p { color: #666; }</style>
</head>
<body><h1>Design Discovery Companion</h1>
<p>Waiting for the agent to push a screen...</p></body></html>`;

const frameTemplate = fs.readFileSync(path.join(__dirname, 'frame-template.html'), 'utf-8');
const helperScript = fs.readFileSync(path.join(__dirname, 'helper.js'), 'utf-8');
const helperInjection = '<script>\n' + helperScript + '\n</script>';

// ========== Helper Functions ==========

function isFullDocument(html) {
  const trimmed = html.trimStart().toLowerCase();
  return trimmed.startsWith('<!doctype') || trimmed.startsWith('<html');
}

function wrapInFrame(content) {
  return frameTemplate.replace('<!-- CONTENT -->', content);
}

function getNewestScreen() {
  const files = fs.readdirSync(CONTENT_DIR)
    .filter(f => f.endsWith('.html'))
    .map(f => {
      const fp = path.join(CONTENT_DIR, f);
      return { path: fp, mtime: fs.statSync(fp).mtime.getTime() };
    })
    .sort((a, b) => b.mtime - a.mtime);
  return files.length > 0 ? files[0].path : null;
}

// ========== HTTP Request Handler ==========

function handleRequest(req, res) {
  touchActivity();
  if (req.method === 'GET' && req.url === '/') {
    const screenFile = getNewestScreen();
    let html = screenFile
      ? (raw => isFullDocument(raw) ? raw : wrapInFrame(raw))(fs.readFileSync(screenFile, 'utf-8'))
      : WAITING_PAGE;

    if (html.includes('</body>')) {
      html = html.replace('</body>', helperInjection + '\n</body>');
    } else {
      html += helperInjection;
    }

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(html);
  } else if (req.method === 'GET' && req.url.startsWith('/files/')) {
    const fileName = req.url.slice(7);
    const filePath = path.join(CONTENT_DIR, path.basename(fileName));
    if (!fs.existsSync(filePath)) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(fs.readFileSync(filePath));
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
}

// ========== WebSocket Connection Handling ==========

const clients = new Set();

function handleUpgrade(req, socket) {
  const key = req.headers['sec-websocket-key'];
  if (!key) { socket.destroy(); return; }

  const accept = computeAcceptKey(key);
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n'
  );

  let buffer = Buffer.alloc(0);
  let fragmentedMessage = null;
  let closed = false;
  clients.add(socket);

  function release() {
    buffer = Buffer.alloc(0);
    fragmentedMessage = null;
    clients.delete(socket);
  }

  function closeWithCode(closeCode) {
    if (closed) return;
    closed = true;
    const payload = Buffer.alloc(2);
    payload.writeUInt16BE(closeCode);
    socket.end(encodeFrame(OPCODES.CLOSE, payload), () => socket.destroy());
    release();
  }

  socket.on('data', (chunk) => {
    if (closed) return;
    try {
      buffer = appendConnectionChunk(buffer, chunk);
    } catch (error) {
      closeWithCode(error.closeCode || 1002);
      return;
    }
    while (buffer.length > 0) {
      let result;
      try {
        result = decodeFrame(buffer);
      } catch (error) {
        closeWithCode(error.closeCode || 1002);
        return;
      }
      if (!result) break;
      buffer = buffer.slice(result.bytesConsumed);

      switch (result.opcode) {
        case OPCODES.TEXT: {
          if (fragmentedMessage !== null) {
            closeWithCode(1002);
            return;
          }
          if (result.final) {
            handleMessage(result.payload.toString());
          } else {
            fragmentedMessage = result.payload;
          }
          break;
        }
        case OPCODES.CONTINUATION:
          if (fragmentedMessage === null) {
            closeWithCode(1002);
            return;
          }
          if (fragmentedMessage.length + result.payload.length > LIMITS.message) {
            closeWithCode(1009);
            return;
          }
          fragmentedMessage = Buffer.concat(
            [fragmentedMessage, result.payload],
            fragmentedMessage.length + result.payload.length
          );
          if (result.final) {
            handleMessage(fragmentedMessage.toString());
            fragmentedMessage = null;
          }
          break;
        case OPCODES.CLOSE:
          closeWithCode(1000);
          return;
        case OPCODES.PING:
          socket.write(encodeFrame(OPCODES.PONG, result.payload));
          break;
        case OPCODES.PONG:
          break;
        default: {
          closeWithCode(1003);
          return;
        }
      }
    }
  });

  socket.on('close', release);
  socket.on('error', release);
}

function handleMessage(text) {
  let event;
  try {
    event = JSON.parse(text);
  } catch (e) {
    console.error('Failed to parse WebSocket message:', e.message);
    return;
  }
  touchActivity();
  console.log(JSON.stringify({ source: 'user-event', ...event }));
  if (event.choice) {
    const eventsFile = path.join(STATE_DIR, 'events');
    fs.appendFileSync(eventsFile, JSON.stringify(event) + '\n');
  }
}

function broadcast(msg) {
  const frame = encodeFrame(OPCODES.TEXT, Buffer.from(JSON.stringify(msg)));
  for (const socket of clients) {
    try { socket.write(frame); } catch (e) { clients.delete(socket); }
  }
}

// ========== Activity Tracking ==========

function boundedInterval(name, defaultValue) {
  if (process.env[name] === undefined) return defaultValue;
  const value = Number(process.env[name]);
  if (!Number.isSafeInteger(value) || value <= 0 || value > defaultValue) {
    throw new Error(`${name} must be a positive integer no greater than ${defaultValue}`);
  }
  return value;
}

const IDLE_TIMEOUT_MS = boundedInterval('BRAINSTORM_IDLE_TIMEOUT_MS', 30 * 60 * 1000);
const LIFECYCLE_INTERVAL_MS = boundedInterval('BRAINSTORM_LIFECYCLE_INTERVAL_MS', 60 * 1000);
let lastActivity = Date.now();

function touchActivity() {
  lastActivity = Date.now();
}

// ========== File Watching ==========

const debounceTimers = new Map();

// ========== Server Startup ==========

function startServer() {
  validateSessionNonce(process.argv.slice(2));
  if (!Number.isSafeInteger(PORT) || PORT < 0 || PORT > 65535) {
    throw new Error('BRAINSTORM_PORT must be an integer from 0 through 65535');
  }
  if (!allowedHosts.has(HOST) || !allowedHosts.has(URL_HOST)) {
    throw new Error('Design-discovery accepts loopback hosts only');
  }
  if (!Number.isSafeInteger(ownerPid) || ownerPid <= 1) {
    throw new Error('BRAINSTORM_OWNER_PID must identify a live owner process');
  }
  try {
    process.kill(ownerPid, 0);
  } catch (error) {
    if (error.code !== 'EPERM') throw new Error('BRAINSTORM_OWNER_PID is not live');
  }

  if (!fs.existsSync(CONTENT_DIR)) fs.mkdirSync(CONTENT_DIR, { recursive: true });
  if (!fs.existsSync(STATE_DIR)) fs.mkdirSync(STATE_DIR, { recursive: true });

  // Track known files to distinguish new screens from updates.
  // macOS fs.watch reports 'rename' for both new files and overwrites,
  // so we can't rely on eventType alone.
  const knownFiles = new Set(
    fs.readdirSync(CONTENT_DIR).filter(f => f.endsWith('.html'))
  );

  const server = http.createServer(handleRequest);
  server.on('upgrade', handleUpgrade);

  const watcher = fs.watch(CONTENT_DIR, (eventType, filename) => {
    if (!filename || !filename.endsWith('.html')) return;

    if (debounceTimers.has(filename)) clearTimeout(debounceTimers.get(filename));
    debounceTimers.set(filename, setTimeout(() => {
      debounceTimers.delete(filename);
      const filePath = path.join(CONTENT_DIR, filename);

      if (!fs.existsSync(filePath)) return; // file was deleted
      touchActivity();

      if (!knownFiles.has(filename)) {
        knownFiles.add(filename);
        const eventsFile = path.join(STATE_DIR, 'events');
        if (fs.existsSync(eventsFile)) fs.unlinkSync(eventsFile);
        console.log(JSON.stringify({ type: 'screen-added', file: filePath }));
      } else {
        console.log(JSON.stringify({ type: 'screen-updated', file: filePath }));
      }

      broadcast({ type: 'reload' });
    }, 100));
  });
  watcher.on('error', (err) => console.error('fs.watch error:', err.message));

  let shuttingDown = false;
  function shutdown(reason) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(JSON.stringify({ type: 'server-stopped', reason }));
    const infoFile = path.join(STATE_DIR, 'server-info');
    if (fs.existsSync(infoFile)) fs.unlinkSync(infoFile);
    fs.writeFileSync(
      path.join(STATE_DIR, 'server-stopped'),
      JSON.stringify({ reason, timestamp: Date.now() }) + '\n'
    );
    clearInterval(lifecycleCheck);
    for (const timer of debounceTimers.values()) clearTimeout(timer);
    debounceTimers.clear();
    watcher.close();
    for (const socket of clients) socket.destroy();
    clients.clear();
    server.close(() => process.exit(0));
  }

  function ownerAlive() {
    try { process.kill(ownerPid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
  }

  // Exit if the owner process dies or the local companion becomes idle.
  const lifecycleCheck = setInterval(() => {
    if (!ownerAlive()) shutdown('owner process exited');
    else if (Date.now() - lastActivity > IDLE_TIMEOUT_MS) shutdown('idle timeout');
  }, LIFECYCLE_INTERVAL_MS);
  lifecycleCheck.unref();

  process.once('SIGTERM', () => shutdown('SIGTERM'));
  process.once('SIGINT', () => shutdown('SIGINT'));

  server.listen(PORT, LISTEN_HOST, () => {
    const address = server.address();
    if (!address || (address.address !== '127.0.0.1' && address.address !== '::1')) {
      shutdown('non-loopback listen address');
      return;
    }
    const info = JSON.stringify({
      type: 'server-started', port: address.port, host: address.address,
      url_host: URL_HOST, url: 'http://' + URL_HOST + ':' + address.port,
      screen_dir: CONTENT_DIR, state_dir: STATE_DIR
    });
    console.log(info);
    fs.writeFileSync(path.join(STATE_DIR, 'server-info'), info + '\n');
  });
}

if (require.main === module) {
  startServer();
}

module.exports = {
  computeAcceptKey, encodeFrame, decodeFrame, appendConnectionChunk, LIMITS, OPCODES
};
