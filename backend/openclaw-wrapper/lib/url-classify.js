// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

/**
 * Application-layer stub: classify URL without DNS lookup.
 * Public HTTP(S) targets are those that are not loopback / RFC1918 / *.local / localhost.
 * @param {string} urlString
 * @returns {{ ok: true, hostname: string, isPublic: boolean } | { ok: false, reason: string }}
 */
function classifyUrl(urlString) {
    if (!urlString || typeof urlString !== 'string') {
        return { ok: false, reason: 'missing_url' };
    }
    let u;
    try {
        u = new URL(urlString);
    } catch {
        return { ok: false, reason: 'invalid_url' };
    }
    const protocol = u.protocol.toLowerCase();
    if (protocol !== 'http:' && protocol !== 'https:') {
        return { ok: false, reason: 'unsupported_protocol' };
    }
    const hostname = u.hostname.toLowerCase();
    const isPublic = !isPrivateOrLocalHost(hostname);
    return { ok: true, hostname, isPublic };
}

/**
 * @param {string} hostname lowercased hostname from URL
 */
function isPrivateOrLocalHost(hostname) {
    if (hostname === 'localhost' || hostname.endsWith('.local')) return true;
    const parts = hostname.split('.');
    if (parts.length === 4 && parts.every((p) => /^\d+$/.test(p))) {
        const a = Number(parts[0]);
        const b = Number(parts[1]);
        if (a === 10) return true;
        if (a === 172 && b >= 16 && b <= 31) return true;
        if (a === 192 && b === 168) return true;
        if (a === 127) return true;
        return false;
    }
    return false;
}

/**
 * @param {string} hostname
 * @param {string[]} egressAllowHosts
 */
function hostMatchesAllowlist(hostname, egressAllowHosts) {
    const h = hostname.toLowerCase();
    for (const entry of egressAllowHosts) {
        const e = entry.toLowerCase();
        if (h === e || h.endsWith(`.${e}`)) return true;
    }
    return false;
}

module.exports = { classifyUrl, isPrivateOrLocalHost, hostMatchesAllowlist };
