// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const { test } = require('node:test');
const assert = require('node:assert');
const { classifyUrl, hostMatchesAllowlist } = require('../lib/url-classify');

test('classifyUrl marks example.com as public', () => {
    const r = classifyUrl('https://example.com/');
    assert.strictEqual(r.ok, true);
    if (r.ok) assert.strictEqual(r.isPublic, true);
});

test('classifyUrl marks 192.168.1.1 as non-public', () => {
    const r = classifyUrl('http://192.168.1.1/');
    assert.strictEqual(r.ok, true);
    if (r.ok) assert.strictEqual(r.isPublic, false);
});

test('hostMatchesAllowlist subdomain match', () => {
    assert.strictEqual(hostMatchesAllowlist('api.partner.example', ['partner.example']), true);
    assert.strictEqual(hostMatchesAllowlist('evil.partner.example', ['api.partner.example']), false);
});
