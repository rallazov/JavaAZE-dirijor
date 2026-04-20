// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const { test, describe, afterEach } = require('node:test');
const assert = require('node:assert');
const http = require('http');
const { loadPolicy } = require('../lib/policy');
const { createServer } = require('../lib/server');

const UUID_RE =
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** @type {string[]} */
const envKeysTouched = [];

function setEnv(key, value) {
    envKeysTouched.push(key);
    if (value === undefined || value === null) delete process.env[key];
    else process.env[key] = value;
}

afterEach(() => {
    while (envKeysTouched.length) {
        const k = envKeysTouched.pop();
        delete process.env[k];
    }
});

function start(policy, realm = 'test-realm') {
    const server = createServer(policy, {
        realm,
        headscaleUrl: 'http://headscale.test',
        port: 0,
        buildId: 'test-build',
    });
    return new Promise((resolve, reject) => {
        server.listen(0, '127.0.0.1', () => resolve(server));
        server.on('error', reject);
    });
}

function serverPort(server) {
    const a = server.address();
    assert.ok(a && typeof a === 'object' && a.port);
    return /** @type {import('net').AddressInfo} */ (a).port;
}

async function jsonRequest(port, method, path, body) {
    const opts = {
        hostname: '127.0.0.1',
        port,
        path,
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    return new Promise((resolve, reject) => {
        const req = http.request(opts, (res) => {
            const chunks = [];
            res.on('data', (c) => chunks.push(c));
            res.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                let data = null;
                try {
                    data = raw ? JSON.parse(raw) : null;
                } catch {
                    data = { _raw: raw };
                }
                resolve({ status: res.statusCode, data });
            });
        });
        req.on('error', reject);
        if (body !== undefined) req.write(JSON.stringify(body));
        req.end();
    });
}

/** Raw POST body (e.g. oversized non-JSON) for readJson limits */
function rawPost(port, path, rawBody) {
    const opts = {
        hostname: '127.0.0.1',
        port,
        path,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(rawBody, 'utf8') },
    };
    return new Promise((resolve, reject) => {
        const req = http.request(opts, (res) => {
            const chunks = [];
            res.on('data', (c) => chunks.push(c));
            res.on('end', () => {
                const raw = Buffer.concat(chunks).toString('utf8');
                let data = null;
                try {
                    data = raw ? JSON.parse(raw) : null;
                } catch {
                    data = { _raw: raw };
                }
                resolve({ status: res.statusCode, data });
            });
        });
        req.on('error', reject);
        req.write(rawBody);
        req.end();
    });
}

describe('tool invoke', () => {
    test('allows allowlisted tool with deterministic stub', async () => {
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop,other');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'POST', '/v1/tools/invoke', {
            tool: 'noop',
            args: { x: 1 },
        });
        assert.strictEqual(status, 200);
        assert.strictEqual(data.ok, true);
        assert.strictEqual(data.tool, 'noop');
        assert.deepStrictEqual(data.result, { stub: true, args: { x: 1 } });
        srv.close();
    });

    test('denies non-allowlisted tool with 403 and audit_id', async () => {
        const stderrLines = [];
        const prevErr = console.error;
        console.error = (msg) => stderrLines.push(String(msg));
        try {
            setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
            const policy = loadPolicy();
            const srv = await start(policy);
            const port = serverPort(srv);
            const { status, data } = await jsonRequest(port, 'POST', '/v1/tools/invoke', { tool: 'evil' });
            assert.strictEqual(status, 403);
            assert.strictEqual(data.error, 'tool_denied');
            assert.strictEqual(data.realm, 'test-realm');
            assert.strictEqual(data.tool, 'evil');
            assert.match(data.audit_id, UUID_RE);
            const denial = stderrLines
                .map((l) => {
                    try {
                        return JSON.parse(l);
                    } catch {
                        return null;
                    }
                })
                .find((j) => j && j.component === 'openclaw-wrapper-denial');
            assert.ok(denial);
            assert.strictEqual(denial.audit_id, data.audit_id);
            assert.strictEqual(denial.error, 'tool_denied');
            srv.close();
        } finally {
            console.error = prevErr;
        }
    });

    test('501 when allowlisted but not in DIRIJOR_IMPLEMENTED_TOOLS', async () => {
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop,browser');
        setEnv('DIRIJOR_IMPLEMENTED_TOOLS', 'noop');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'POST', '/v1/tools/invoke', { tool: 'browser' });
        assert.strictEqual(status, 501);
        assert.strictEqual(data.error, 'not_implemented');
        assert.match(data.audit_id, UUID_RE);
        srv.close();
    });

    test('413 when POST body exceeds DIRIJOR_WRAPPER_MAX_BODY_BYTES', async () => {
        setEnv('DIRIJOR_WRAPPER_MAX_BODY_BYTES', '48');
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await rawPost(port, '/v1/tools/invoke', 'x'.repeat(64));
        assert.strictEqual(status, 413);
        assert.strictEqual(data.error, 'payload_too_large');
        srv.close();
    });
});

describe('egress check', () => {
    test('denies public URL in deny_public mode', async () => {
        setEnv('DIRIJOR_EGRESS_MODE', 'deny_public');
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'POST', '/v1/egress/check', {
            url: 'https://example.com/path',
        });
        assert.strictEqual(status, 403);
        assert.strictEqual(data.error, 'egress_denied');
        assert.match(data.audit_id, UUID_RE);
        srv.close();
    });

    test('stderr egress denial redacts userinfo in url field', async () => {
        const stderrLines = [];
        const prevErr = console.error;
        console.error = (msg) => stderrLines.push(String(msg));
        try {
            setEnv('DIRIJOR_EGRESS_MODE', 'deny_public');
            setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
            const policy = loadPolicy();
            const srv = await start(policy);
            const port = serverPort(srv);
            const secret = 'supersecret';
            await jsonRequest(port, 'POST', '/v1/egress/check', {
                url: `https://u:${secret}@example.com/x`,
            });
            const combined = stderrLines.join('\n');
            assert.ok(!combined.includes(secret), 'password must not appear in stderr');
            const denial = stderrLines
                .map((l) => {
                    try {
                        return JSON.parse(l);
                    } catch {
                        return null;
                    }
                })
                .find((j) => j && j.component === 'openclaw-wrapper-denial');
            assert.ok(denial && denial.url);
            assert.ok(!String(denial.url).includes(secret));
            srv.close();
        } finally {
            console.error = prevErr;
        }
    });

    test('allows private RFC1918 URL in deny_public mode', async () => {
        setEnv('DIRIJOR_EGRESS_MODE', 'deny_public');
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'POST', '/v1/egress/check', {
            url: 'http://10.0.0.1/api',
        });
        assert.strictEqual(status, 200);
        assert.strictEqual(data.ok, true);
        srv.close();
    });

    test('allowlist mode permits explicit public host', async () => {
        setEnv('DIRIJOR_EGRESS_MODE', 'allowlist');
        setEnv('DIRIJOR_EGRESS_ALLOW_HOSTS', 'api.partner.example');
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'noop');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'POST', '/v1/egress/check', {
            url: 'https://api.partner.example/v1',
        });
        assert.strictEqual(status, 200);
        assert.strictEqual(data.ok, true);
        srv.close();
    });
});

describe('health', () => {
    test('summarizes policy without exposing full allowlist', async () => {
        setEnv('DIRIJOR_TOOL_ALLOWLIST', 'a,b,c');
        setEnv('DIRIJOR_EGRESS_MODE', 'deny_public');
        const policy = loadPolicy();
        const srv = await start(policy);
        const port = serverPort(srv);
        const { status, data } = await jsonRequest(port, 'GET', '/health', undefined);
        assert.strictEqual(status, 200);
        assert.strictEqual(data.realm, 'test-realm');
        assert.strictEqual(data.policy.allowed_tool_count, 3);
        assert.strictEqual(data.policy.egress_mode, 'deny_public');
        assert.ok(!('tools' in data.policy));
        srv.close();
    });
});
