// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
// OpenTelemetry bootstrap for the wrapper (Story 6.1). OTLP export is opt-in.

const { trace } = require('@opentelemetry/api');
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { BatchSpanProcessor } = require('@opentelemetry/sdk-trace-base');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { Resource } = require('@opentelemetry/resources');

let initialized = false;

function otelSdkDisabled() {
    const v = (process.env.OTEL_SDK_DISABLED || '').trim().toLowerCase();
    return v === 'true' || v === '1' || v === 'yes';
}

function otelExportEnabled() {
    if (otelSdkDisabled()) {
        return false;
    }
    return Boolean((process.env.OTEL_EXPORTER_OTLP_ENDPOINT || '').trim());
}

function initOtel() {
    if (initialized) return;
    initialized = true;
    if (!otelExportEnabled()) {
        return;
    }
    const serviceName = process.env.OTEL_SERVICE_NAME || 'dirijor-openclaw-wrapper';
    const serviceVersion = process.env.OTEL_SERVICE_VERSION || '0.1.0';
    try {
        const provider = new NodeTracerProvider({
            resource: new Resource({
                'service.name': serviceName,
                'service.version': serviceVersion,
            }),
        });
        provider.addSpanProcessor(new BatchSpanProcessor(new OTLPTraceExporter()));
        provider.register();
        process.once('beforeExit', () => {
            provider.shutdown().catch(() => {});
        });
    } catch (e) {
        console.error('otel.init.failed', e);
    }
}

function getTracer() {
    return trace.getTracer('dirijor-openclaw-wrapper', process.env.OTEL_SERVICE_VERSION || '0.1.0');
}

module.exports = {
    initOtel,
    getTracer,
    otelExportEnabled,
    otelSdkDisabled,
};
