# Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
"""OpenTelemetry bootstrap for Dirijor Core (Story 6.1).

Export is **opt-in**: unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (and
``OTEL_SDK_DISABLED`` is not truthy), the global tracer is a no-op and tests
stay hermetic. FastAPI HTTP instrumentation is registered once so route spans
exist when a ``TracerProvider`` is configured (local collector or tests).
"""

from __future__ import annotations

import atexit
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("dirijor.otel")

_OTEL_BOOTSTRAPPED = False
_FASTAPI_INSTRUMENTED = False

# Second argument to ``trace.get_tracer`` — instrumentation scope version (not service version).
INSTRUMENTATION_SCOPE_VERSION = "1.0.0"


def _sdk_disabled() -> bool:
    return os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def _otlp_endpoint_configured() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


def _register_tracer_provider_shutdown() -> None:
    def _shutdown() -> None:
        try:
            from opentelemetry import trace

            trace.get_tracer_provider().shutdown()
        except Exception:
            pass

    atexit.register(_shutdown)


def _http_server_scrub_hook(span, scope: dict) -> None:
    """Strip query strings from auto-instrumentation HTTP URL attributes (AC7)."""
    if not span.is_recording():
        return
    try:
        from opentelemetry.instrumentation.asgi import get_host_port_url_tuple
        from opentelemetry.semconv.trace import SpanAttributes

        _, _, url_without_query = get_host_port_url_tuple(scope)
        if url_without_query:
            span.set_attribute(SpanAttributes.HTTP_URL, url_without_query)
    except Exception:
        logger.debug("otel.http_scrub_hook.failed", exc_info=True)


def configure_opentelemetry(*, service_name: str, service_version: str) -> None:
    """Install OTLP HTTP export when env requests it. Safe to call once."""
    global _OTEL_BOOTSTRAPPED
    if _OTEL_BOOTSTRAPPED:
        return
    _OTEL_BOOTSTRAPPED = True
    if _sdk_disabled():
        logger.info(
            "otel.sdk_disabled",
            extra={"event": "otel.sdk_disabled", "reason": "OTEL_SDK_DISABLED"},
        )
        return
    if not _otlp_endpoint_configured():
        logger.info(
            "otel.export.skipped",
            extra={
                "event": "otel.export.skipped",
                "reason": "OTEL_EXPORTER_OTLP_ENDPOINT unset",
            },
        )
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        name = os.environ.get("OTEL_SERVICE_NAME", service_name).strip() or service_name
        version = os.environ.get("OTEL_SERVICE_VERSION", service_version).strip() or (
            service_version
        )
        resource = Resource.create(
            {
                "service.name": name,
                "service.version": version,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _register_tracer_provider_shutdown()
        logger.info(
            "otel.export.enabled",
            extra={"event": "otel.export.enabled", "service.name": name},
        )
    except Exception:
        logger.exception(
            "otel.configure.failed",
            extra={"event": "otel.configure.failed"},
        )


def instrument_fastapi_app(app: FastAPI) -> None:
    """Register FastAPI/Starlette auto-instrumentation once.

    **Excluded URLs** (override with ``OTEL_HTTP_EXCLUDED_URLS``, comma-separated
    regex fragments matched against the path):

    - ``GET /health`` — high-churn health probes (with optional trailing slash).
    - ``GET /`` — aggregate readiness snapshot polled by dashboards.

    WebSocket upgrades are **not** covered by this middleware; see
    ``realm_ws`` manual spans in ``supervisor.py``.
    """
    global _FASTAPI_INSTRUMENTED
    if _FASTAPI_INSTRUMENTED:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    excluded = os.environ.get("OTEL_HTTP_EXCLUDED_URLS", "^/health/?$,^/?$")
    try:
        FastAPIInstrumentor().instrument_app(
            app,
            excluded_urls=excluded,
            server_request_hook=_http_server_scrub_hook,
            http_capture_headers_server_request=[],
            http_capture_headers_server_response=[],
        )
    except Exception:
        logger.exception(
            "otel.fastapi_instrument.failed",
            extra={"event": "otel.fastapi_instrument.failed", "excluded_urls": excluded},
        )
        try:
            FastAPIInstrumentor().instrument_app(
                app,
                excluded_urls="^/health/?$,^/?$",
                server_request_hook=_http_server_scrub_hook,
                http_capture_headers_server_request=[],
                http_capture_headers_server_response=[],
            )
        except Exception:
            logger.exception("otel.fastapi_instrument.fallback_failed")
            return
    _FASTAPI_INSTRUMENTED = True


def setup_core_observability(app: FastAPI, *, service_name: str, service_version: str) -> None:
    """Configure OTLP (if env enables) and instrument HTTP routes."""
    configure_opentelemetry(service_name=service_name, service_version=service_version)
    instrument_fastapi_app(app)


def get_tracer(name: str, version: str):
    """Return a tracer for manual spans (no-op until a provider is set)."""
    from opentelemetry import trace

    return trace.get_tracer(name, version)
