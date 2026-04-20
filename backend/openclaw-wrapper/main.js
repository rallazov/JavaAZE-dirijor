// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// Secure OpenClaw Agent Wrapper — tool allowlist + application-layer egress stub (Story 5.2)

const { loadPolicy } = require('./lib/policy');
const { createServer } = require('./lib/server');

const HEADSCALE_URL = process.env.HEADSCALE_URL || 'http://localhost:8080';
const REALM_NAME = process.env.REALM_NAME || 'default-realm';
const PORT = Number(process.env.PORT || '3001') || 3001;
const BUILD_ID = process.env.DIRIJOR_WRAPPER_BUILD_ID || 'dev';

const policy = loadPolicy();
const server = createServer(policy, {
    realm: REALM_NAME,
    headscaleUrl: HEADSCALE_URL,
    port: PORT,
    buildId: BUILD_ID,
});

server.listen(PORT, () => {
    console.log(`🦞 OpenClaw agent ready on port ${PORT} | Realm: ${REALM_NAME}`);
});
