// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const fs = require('fs');
const path = require('path');

const EGRESS_MODES = new Set(['deny_public', 'allowlist']);

/**
 * @typedef {Object} WrapperPolicy
 * @property {Set<string>} toolAllowlist
 * @property {'deny_public'|'allowlist'} egressMode
 * @property {string[]} egressAllowHosts normalized host suffixes / exact hosts (lowercase)
 * @property {Set<string>|null} implementedTools null = all allowlisted tools are stub-implemented
 */

/**
 * Parse comma-separated tool list; trim; drop empties.
 * @param {string} raw
 * @returns {string[]}
 */
function parseCommaList(raw) {
    if (!raw || typeof raw !== 'string') return [];
    return raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
}

/**
 * Load policy at process start. Fail fast if DIRIJOR_WRAPPER_POLICY_PATH is set but unreadable.
 * @returns {WrapperPolicy}
 */
function loadPolicy() {
    const policyPath = process.env.DIRIJOR_WRAPPER_POLICY_PATH;
    let toolList = [];
    let egressMode = process.env.DIRIJOR_EGRESS_MODE || 'deny_public';
    let egressAllowHosts = parseCommaList(process.env.DIRIJOR_EGRESS_ALLOW_HOSTS || '').map((h) =>
        h.toLowerCase()
    );

    if (policyPath) {
        const abs = path.isAbsolute(policyPath) ? policyPath : path.resolve(process.cwd(), policyPath);
        let raw;
        try {
            raw = fs.readFileSync(abs, 'utf8');
        } catch (e) {
            console.error(
                `[openclaw-wrapper] FATAL: DIRIJOR_WRAPPER_POLICY_PATH set but file not readable: ${abs}`
            );
            process.exit(1);
        }
        let doc;
        try {
            doc = JSON.parse(raw);
        } catch (e) {
            console.error(`[openclaw-wrapper] FATAL: invalid JSON in policy file ${abs}`);
            process.exit(1);
        }
        if (!doc || typeof doc !== 'object') {
            console.error(`[openclaw-wrapper] FATAL: policy file must be a JSON object`);
            process.exit(1);
        }
        if (Array.isArray(doc.tools)) {
            toolList = doc.tools.map((t) => String(t).trim()).filter(Boolean);
        } else if (doc.tools !== undefined) {
            console.error(`[openclaw-wrapper] FATAL: policy "tools" must be an array when present`);
            process.exit(1);
        }
        if (doc.egress_mode !== undefined) {
            egressMode = String(doc.egress_mode);
        }
        if (Array.isArray(doc.egress_allow_hosts)) {
            egressAllowHosts = doc.egress_allow_hosts.map((h) => String(h).trim().toLowerCase()).filter(Boolean);
        }
    } else {
        toolList = parseCommaList(process.env.DIRIJOR_TOOL_ALLOWLIST || '');
    }

    if (!EGRESS_MODES.has(egressMode)) {
        console.error(
            `[openclaw-wrapper] FATAL: egress_mode must be one of ${[...EGRESS_MODES].join(', ')}; got ${egressMode}`
        );
        process.exit(1);
    }

    const implRaw = process.env.DIRIJOR_IMPLEMENTED_TOOLS;
    /** @type {Set<string>|null} */
    let implementedTools = null;
    if (implRaw !== undefined && implRaw !== '') {
        implementedTools = new Set(parseCommaList(implRaw).map((t) => t.toLowerCase()));
    }

    return {
        toolAllowlist: new Set(toolList.map((t) => t.toLowerCase())),
        egressMode: /** @type {'deny_public'|'allowlist'} */ (egressMode),
        egressAllowHosts,
        implementedTools,
    };
}

module.exports = { loadPolicy, parseCommaList, EGRESS_MODES };
