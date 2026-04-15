"""Observability: structured JSON logging, OpenTelemetry, safe log filter.

Per GAP-015, ops-config.yaml, architecture.md CC-11.
"""
import json
import logging
import sys


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter with trace context."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id = None
        span_id = None
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx and ctx.trace_id:
                trace_id = format(ctx.trace_id, "032x")
                span_id = format(ctx.span_id, "016x")
        except ImportError:
            pass

        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
            "service": "bom-intelligence-engine",
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, default=str)


class SafeLogFilter(logging.Filter):
    """Redact file paths and raw BOM content in production logs."""

    def __init__(self, is_production: bool = False) -> None:
        super().__init__()
        self.is_production = is_production

    def filter(self, record: logging.LogRecord) -> bool:
        if self.is_production:
            msg = record.getMessage()
            if len(msg) > 200:
                record.msg = msg[:200] + "...[truncated]"
                record.args = None
        return True


def configure_observability(app=None, config=None) -> None:
    """Configure structured logging and optional OpenTelemetry."""
    from core.config import config as default_config
    cfg = config or default_config

    # Structured logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(SafeLogFilter(is_production=(cfg.PLATFORM_ENV == "production")))
    logging.root.handlers = [handler]
    logging.root.setLevel(cfg.LOG_LEVEL)

    # OpenTelemetry (optional)
    if cfg.OTEL_EXPORTER_OTLP_ENDPOINT and app:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            provider = TracerProvider()
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.OTEL_EXPORTER_OTLP_ENDPOINT))
            )
            trace.set_tracer_provider(provider)
            FastAPIInstrumentor.instrument_app(app)
            logging.getLogger("observability").info("OpenTelemetry initialized")
        except ImportError:
            logging.getLogger("observability").warning(
                "OpenTelemetry packages not installed; tracing disabled"
            )
