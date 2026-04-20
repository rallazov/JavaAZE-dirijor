// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const { test, afterEach } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { loadPolicy } = require('../lib/policy');

const envKeys = [
    'DIRIJOR_WRAPPER_POLICY_PATH',
    'DIRIJOR_TOOL_ALLOWLIST',
    'DIRIJOR_EGRESS_MODE',
    'DIRIJOR_EGRESS_ALLOW_HOSTS',
];

afterEach(() => {
    for (const k of envKeys) delete process.env[k];
});

test('loads tools and egress_mode from policy file', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wrapper-policy-'));
    const p = path.join(dir, 'policy.json');
    fs.writeFileSync(
        p,
        JSON.stringify({
            tools: ['FromFile'],
            egress_mode: 'allowlist',
            egress_allow_hosts: ['trusted.internal'],
        })
    );
    process.env.DIRIJOR_WRAPPER_POLICY_PATH = p;
    const pol = loadPolicy();
    assert.ok(pol.toolAllowlist.has('fromfile'));
    assert.strictEqual(pol.egressMode, 'allowlist');
    assert.deepStrictEqual(pol.egressAllowHosts, ['trusted.internal']);
});
