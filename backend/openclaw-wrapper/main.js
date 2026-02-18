// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// Secure OpenClaw Agent Wrapper – Auto-joins Headscale mesh

const http = require('http');

const HEADSCALE_URL = process.env.HEADSCALE_URL || 'http://localhost:8080';
const REALM_NAME = process.env.REALM_NAME || 'default-realm';
const PORT = 3001;

const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        agent: 'openclaw-wrapper',
        realm: REALM_NAME,
        status: 'ready',
        mesh: HEADSCALE_URL,
    }));
});

server.listen(PORT, () => {
    console.log(`🦞 OpenClaw agent ready on port ${PORT} | Realm: ${REALM_NAME}`);
});
