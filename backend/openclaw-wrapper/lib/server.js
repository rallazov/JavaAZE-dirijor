// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const http = require('http');
const crypto = require('crypto');
const { SpanStatusCode } = require('@opentelemetry/api');
const { classifyUrl, isPrivateOrLocalHost, hostMatchesAllowlist } = require('./url-classify');
const { getTracer } = require('./otel');

const WRAPPER_POLICY_VERSION = '1';

const DEFAULT_MAX_BODY_BYTES = 1048576; // 1 MiB

/**
 * Strip userinfo from URLs before logging so credentials never hit stderr.
 * @param {string} urlStr
 * @returns {string}
 */
function redactUrlForLog(urlStr) {
    if (!urlStr || typeof urlStr !== 'string') return urlStr;
    try {
        const u = new URL(urlStr);
        if (u.username || u.password) {
            u.username = '';
            u.password = '';
        }
        return u.href;
    } catch {
        return urlStr.replace(/^([a-z][a-z0-9+.-]*:\/\/)(?:[^/@?#]+@)/i, '$1');
    }
}

/**
 * @param {import('./policy').WrapperPolicy} policy
 * @param {{ realm: string, headscaleUrl: string, port: number, buildId: string }} opts
 */
function createServer(policy, opts) {
    const { realm, headscaleUrl, port, buildId } = opts;

    return http.createServer((req, res) => {
        const url = new URL(req.url || '/', `http://127.0.0.1:${port}`);
        const pathname = url.pathname.replace(/\/+$/, '') || '/';

        if (req.method === 'GET' && (pathname === '/' || pathname === '/health')) {
            const span = getTracer().startSpan('dirijor.wrapper.health');
            span.setAttribute('dirijor.realm', realm);
            span.setAttribute('http.route', pathname);
            try {
                sendJson(res, 200, healthBody(policy, realm, headscaleUrl, buildId));
            } finally {
                span.end();
            }
            return;
        }

        if (req.method === 'POST' && pathname === '/v1/tools/invoke') {
            const span = getTracer().startSpan('dirijor.wrapper.tools.invoke');
            span.setAttribute('dirijor.realm', realm);
            span.setAttribute('http.route', '/v1/tools/invoke');
            handleToolInvoke(req, res, policy, realm)
                .catch((err) => {
                    span.recordException(err);
                    span.setStatus({ code: SpanStatusCode.ERROR });
                    sendInternalError(res, realm);
                })
                .finally(() => span.end());
            return;
        }

        if (req.method === 'POST' && pathname === '/v1/egress/check') {
            const span = getTracer().startSpan('dirijor.wrapper.egress_check');
            span.setAttribute('dirijor.realm', realm);
            span.setAttribute('http.route', '/v1/egress/check');
            handleEgressCheck(req, res, policy, realm)
                .catch((err) => {
                    span.recordException(err);
                    span.setStatus({ code: SpanStatusCode.ERROR });
                    sendInternalError(res, realm);
                })
                .finally(() => span.end());
            return;
        }

        sendJson(res, 404, { error: 'not_found', wrapper_policy_version: WRAPPER_POLICY_VERSION });
    });
}

function healthBody(policy, realm, headscaleUrl, buildId) {
    return {
        agent: 'openclaw-wrapper',
        realm,
        status: 'ready',
        mesh: headscaleUrl,
        policy: {
            allowed_tool_count: policy.toolAllowlist.size,
            egress_mode: policy.egressMode,
            policy_source: process.env.DIRIJOR_WRAPPER_POLICY_PATH ? 'file' : 'env',
        },
        build: buildId,
        wrapper_policy_version: WRAPPER_POLICY_VERSION,
    };
}

/**
 * @param {import('./policy').WrapperPolicy} policy
 */
async function handleToolInvoke(req, res, policy, realm) {
    let body;
    try {
        body = await readJson(req);
    } catch (e) {
        if (e && e.code === 'PAYLOAD_TOO_LARGE') {
            sendJson(res, 413, { error: 'payload_too_large', wrapper_policy_version: WRAPPER_POLICY_VERSION });
            return;
        }
        sendJson(res, 400, { error: 'invalid_json', wrapper_policy_version: WRAPPER_POLICY_VERSION });
        return;
    }
    const toolRaw = body.tool;
    const tool = typeof toolRaw === 'string' ? toolRaw.trim().toLowerCase() : '';
    if (!tool) {
        const auditId = crypto.randomUUID();
        logDenial({ audit_id: auditId, error: 'invalid_request', realm, tool: toolRaw });
        sendJson(res, 400, {
            error: 'invalid_request',
            realm,
            tool: toolRaw ?? null,
            audit_id: auditId,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    if (!policy.toolAllowlist.has(tool)) {
        const auditId = crypto.randomUUID();
        logDenial({ audit_id: auditId, error: 'tool_denied', realm, tool });
        sendJson(res, 403, {
            error: 'tool_denied',
            realm,
            tool,
            audit_id: auditId,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    if (policy.implementedTools && !policy.implementedTools.has(tool)) {
        const auditId = crypto.randomUUID();
        logDenial({ audit_id: auditId, error: 'not_implemented', realm, tool });
        sendJson(res, 501, {
            error: 'not_implemented',
            realm,
            tool,
            audit_id: auditId,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    sendJson(res, 200, {
        ok: true,
        tool,
        result: { stub: true, args: body.args !== undefined ? body.args : {} },
        wrapper_policy_version: WRAPPER_POLICY_VERSION,
    });
}

/**
 * @param {import('./policy').WrapperPolicy} policy
 */
async function handleEgressCheck(req, res, policy, realm) {
    let body;
    try {
        body = await readJson(req);
    } catch (e) {
        if (e && e.code === 'PAYLOAD_TOO_LARGE') {
            sendJson(res, 413, { error: 'payload_too_large', wrapper_policy_version: WRAPPER_POLICY_VERSION });
            return;
        }
        sendJson(res, 400, { error: 'invalid_json', wrapper_policy_version: WRAPPER_POLICY_VERSION });
        return;
    }
    const urlStr = typeof body.url === 'string' ? body.url : '';
    const classified = classifyUrl(urlStr);
    if (!classified.ok) {
        const auditId = crypto.randomUUID();
        logDenial({
            audit_id: auditId,
            error: 'egress_denied',
            realm,
            url: urlStr,
            reason: classified.reason,
        });
        sendJson(res, 403, {
            error: 'egress_denied',
            realm,
            url: urlStr || null,
            audit_id: auditId,
            reason: classified.reason,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    const { hostname, isPublic } = classified;

    if (policy.egressMode === 'deny_public') {
        if (isPublic) {
            const auditId = crypto.randomUUID();
            logDenial({ audit_id: auditId, error: 'egress_denied', realm, url: urlStr });
            sendJson(res, 403, {
                error: 'egress_denied',
                realm,
                url: urlStr,
                audit_id: auditId,
                wrapper_policy_version: WRAPPER_POLICY_VERSION,
            });
            return;
        }
        sendJson(res, 200, {
            ok: true,
            url: urlStr,
            hostname,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    // allowlist mode: private/local hosts always allowed; public only if on allowlist
    if (!isPublic || hostMatchesAllowlist(hostname, policy.egressAllowHosts)) {
        sendJson(res, 200, {
            ok: true,
            url: urlStr,
            hostname,
            wrapper_policy_version: WRAPPER_POLICY_VERSION,
        });
        return;
    }

    const auditId = crypto.randomUUID();
    logDenial({ audit_id: auditId, error: 'egress_denied', realm, url: urlStr });
    sendJson(res, 403, {
        error: 'egress_denied',
        realm,
        url: urlStr,
        audit_id: auditId,
        wrapper_policy_version: WRAPPER_POLICY_VERSION,
    });
}

function logDenial(fields) {
    const payload = { ...fields, component: 'openclaw-wrapper-denial' };
    if (payload.url !== undefined) payload.url = redactUrlForLog(payload.url);
    console.error(JSON.stringify(payload));
}

function sendInternalError(res, realm) {
    const auditId = crypto.randomUUID();
    sendJson(res, 500, {
        error: 'internal_error',
        realm,
        audit_id: auditId,
        wrapper_policy_version: WRAPPER_POLICY_VERSION,
    });
}

function sendJson(res, status, obj) {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(obj));
}

function readJson(req) {
    const maxBytes = (() => {
        const n = Number(process.env.DIRIJOR_WRAPPER_MAX_BODY_BYTES);
        return Number.isFinite(n) && n > 0 ? n : DEFAULT_MAX_BODY_BYTES;
    })();
    return new Promise((resolve, reject) => {
        const chunks = [];
        let size = 0;
        let oversize = false;
        req.on('data', (c) => {
            if (oversize) return;
            size += c.length;
            if (size > maxBytes) {
                oversize = true;
                const err = new Error('payload too large');
                err.code = 'PAYLOAD_TOO_LARGE';
                reject(err);
                return;
            }
            chunks.push(c);
        });
        req.on('end', () => {
            if (oversize) return;
            const raw = Buffer.concat(chunks).toString('utf8');
            if (!raw) {
                resolve({});
                return;
            }
            try {
                resolve(JSON.parse(raw));
            } catch {
                reject(new Error('invalid json'));
            }
        });
        req.on('error', reject);
    });
}

module.exports = {
    createServer,
    healthBody,
    WRAPPER_POLICY_VERSION,
    redactUrlForLog,
};
