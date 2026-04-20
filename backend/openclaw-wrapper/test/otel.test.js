// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.

const assert = require('node:assert');
const http = require('http');
const test = require('node:test');
const { Resource } = require('@opentelemetry/resources');
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { InMemorySpanExporter, SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-base');

test('health + tools routes emit manual spans when a TracerProvider is set', async () => {
    const prevAllow = process.env.DIRIJOR_TOOL_ALLOWLIST;
    process.env.DIRIJOR_TOOL_ALLOWLIST = 'demo';

    const exporter = new InMemorySpanExporter();
    const provider = new NodeTracerProvider({
        resource: new Resource({ 'service.name': 'openclaw-test' }),
    });
    provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
    provider.register();

    try {
        const { createServer } = require('../lib/server');
        const { loadPolicy } = require('../lib/policy');
        const policy = loadPolicy();
        const srv = createServer(policy, {
            realm: 'otel-test-realm',
            headscaleUrl: 'http://127.0.0.1:9',
            port: 0,
            buildId: 'test',
        });

        await new Promise((resolve, reject) => {
            srv.listen(0, '127.0.0.1', (err) => (err ? reject(err) : resolve()));
        });
        const { port } = srv.address();

        await new Promise((resolve, reject) => {
            http.get(`http://127.0.0.1:${port}/health`, (res) => {
                res.resume();
                res.on('end', resolve);
            }).on('error', reject);
        });

        await new Promise((resolve, reject) => {
            const body = JSON.stringify({ tool: 'demo' });
            const req = http.request(
                {
                    hostname: '127.0.0.1',
                    port,
                    path: '/v1/tools/invoke',
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Content-Length': Buffer.byteLength(body),
                    },
                },
                (res) => {
                    res.resume();
                    res.on('end', resolve);
                }
            );
            req.on('error', reject);
            req.write(body);
            req.end();
        });

        await new Promise((resolve) => srv.close(resolve));

        const names = exporter.getFinishedSpans().map((s) => s.name);
        assert.ok(names.includes('dirijor.wrapper.health'), names);
        assert.ok(names.includes('dirijor.wrapper.tools.invoke'), names);
        const toolsSpan = exporter
            .getFinishedSpans()
            .find((s) => s.name === 'dirijor.wrapper.tools.invoke');
        assert.equal(toolsSpan.attributes['http.route'], '/v1/tools/invoke');
    } finally {
        if (prevAllow === undefined) delete process.env.DIRIJOR_TOOL_ALLOWLIST;
        else process.env.DIRIJOR_TOOL_ALLOWLIST = prevAllow;
        await provider.shutdown();
    }
});
