#!/usr/bin/env python3
"""
Send OTLP spans to Arize AX via gRPC.
Phoenix uses REST API directly via the collector - no separate sender needed.

Install dependencies:
  pip install opentelemetry-proto grpcio
"""

import base64
import json
import os
import sys
import yaml

CONFIG_FILE = os.path.expanduser("~/.arize/harness/config.yaml")


def _load_config():
    """Load config from ~/.arize/harness/config.yaml."""
    if not os.path.isfile(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"[arize] Warning: malformed config.yaml: {e}", file=sys.stderr)
        return None


def _resolve_project_name(span_data, config):
    """Resolve project name from harness config, env var, or service.name."""
    service_name = ""
    for rs in span_data.get("resourceSpans", []):
        for attr in rs.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service_name = attr.get("value", {}).get("stringValue", "")
                break
        if service_name:
            break

    if config:
        harness_cfg = config.get("harnesses", {}).get(service_name, {})
        project_name = harness_cfg.get("project_name", "")
        if project_name:
            return project_name

    project_name = os.environ.get("ARIZE_PROJECT_NAME", "")
    if project_name:
        return project_name
    if service_name:
        return service_name
    return "default"


def send_to_arize_grpc(span_data: dict, api_key: str, space_id: str) -> bool:
    """Send spans to Arize using gRPC with proper trace IDs."""
    try:
        import grpc
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc
        from opentelemetry.proto.trace.v1 import trace_pb2
        from opentelemetry.proto.common.v1 import common_pb2
        from opentelemetry.proto.resource.v1 import resource_pb2

        def any_value_from_json(value: dict) -> common_pb2.AnyValue:
            """Convert OTLP JSON values to AnyValue, preserving numeric/bool types."""
            if not isinstance(value, dict):
                return common_pb2.AnyValue(string_value=str(value))
            if "stringValue" in value:
                return common_pb2.AnyValue(string_value=str(value["stringValue"]))
            if "intValue" in value:
                try:
                    return common_pb2.AnyValue(int_value=int(value["intValue"]))
                except (TypeError, ValueError):
                    pass
            if "doubleValue" in value:
                try:
                    return common_pb2.AnyValue(double_value=float(value["doubleValue"]))
                except (TypeError, ValueError):
                    pass
            if "boolValue" in value:
                bool_val = value["boolValue"]
                if isinstance(bool_val, str):
                    bool_val = bool_val.strip().lower() in ("true", "1", "yes")
                else:
                    bool_val = bool(bool_val)
                return common_pb2.AnyValue(bool_value=bool_val)
            if "bytesValue" in value:
                raw = value["bytesValue"]
                try:
                    data = base64.b64decode(raw)
                except Exception:
                    data = str(raw).encode("utf-8", errors="ignore")
                return common_pb2.AnyValue(bytes_value=data)
            if "arrayValue" in value:
                serialized = json.dumps(value.get("arrayValue", {}).get("values", []))
                return common_pb2.AnyValue(string_value=serialized)
            if "kvlistValue" in value:
                serialized = json.dumps(value.get("kvlistValue", {}).get("values", []))
                return common_pb2.AnyValue(string_value=serialized)
            return common_pb2.AnyValue(string_value=json.dumps(value))

        # Resolve project name from config, env var, or service.name
        config = _load_config()
        project_name = _resolve_project_name(span_data, config)

        # Build the protobuf message from our JSON
        resource_spans = []
        status_ok = 1
        try:
            status_ok = trace_pb2.Status.StatusCode.STATUS_CODE_OK
        except AttributeError:
            status_ok = getattr(trace_pb2.Status, "STATUS_CODE_OK", 1)

        for rs in span_data.get("resourceSpans", []):
            # Build resource - MUST include arize.project.name
            resource_attrs = [
                common_pb2.KeyValue(
                    key="arize.project.name",
                    value=common_pb2.AnyValue(string_value=project_name)
                ),
            ]
            for attr in rs.get("resource", {}).get("attributes", []):
                key = attr.get("key", "")
                value = attr.get("value", {})
                if not key:
                    continue
                resource_attrs.append(common_pb2.KeyValue(
                    key=key,
                    value=any_value_from_json(value)
                ))

            resource = resource_pb2.Resource(attributes=resource_attrs)

            # Build scope spans
            scope_spans = []
            for ss in rs.get("scopeSpans", []):
                spans = []
                for s in ss.get("spans", []):
                    # Get IDs as bytes
                    trace_id = bytes.fromhex(s.get("traceId", "0" * 32))
                    span_id = bytes.fromhex(s.get("spanId", "0" * 16))
                    parent_span_id = bytes.fromhex(s.get("parentSpanId", "")) if s.get("parentSpanId") else b""

                    # Build attributes - MUST include arize.project.name
                    attrs = [
                        common_pb2.KeyValue(
                            key="arize.project.name",
                            value=common_pb2.AnyValue(string_value=project_name)
                        ),
                    ]
                    for attr in s.get("attributes", []):
                        key = attr.get("key", "")
                        value = attr.get("value", {})
                        if not key:
                            continue
                        attrs.append(common_pb2.KeyValue(
                            key=key,
                            value=any_value_from_json(value)
                        ))

                    # Build span
                    kind_value = s.get("kind", 1)
                    try:
                        kind_value = int(kind_value)
                    except (TypeError, ValueError):
                        kind_value = 1
                    span = trace_pb2.Span(
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        name=s.get("name", "span"),
                        kind=kind_value,
                        start_time_unix_nano=int(s.get("startTimeUnixNano", 0)),
                        end_time_unix_nano=int(s.get("endTimeUnixNano", 0)),
                        attributes=attrs,
                        status=trace_pb2.Status(code=status_ok),
                    )
                    spans.append(span)

                scope_info = ss.get("scope", {}) or {}
                scope_kwargs = {}
                scope_name = scope_info.get("name")
                scope_version = scope_info.get("version")
                if scope_name:
                    scope_kwargs["name"] = scope_name
                if scope_version:
                    scope_kwargs["version"] = scope_version
                scope_attributes = []
                for scope_attr in scope_info.get("attributes", []):
                    scope_key = scope_attr.get("key")
                    if not scope_key:
                        continue
                    scope_attributes.append(common_pb2.KeyValue(
                        key=scope_key,
                        value=any_value_from_json(scope_attr.get("value", {}))
                    ))
                if scope_attributes:
                    scope_kwargs["attributes"] = scope_attributes
                scope_args = {"spans": spans}
                if scope_kwargs:
                    scope_args["scope"] = common_pb2.InstrumentationScope(**scope_kwargs)

                scope_spans.append(trace_pb2.ScopeSpans(**scope_args))

            resource_spans.append(trace_pb2.ResourceSpans(
                resource=resource,
                scope_spans=scope_spans,
            ))

        # Create the request
        request = trace_service_pb2.ExportTraceServiceRequest(
            resource_spans=resource_spans
        )

        # Send via gRPC (endpoint from config or env)
        if config:
            endpoint = config.get("backend", {}).get("arize", {}).get("endpoint", "otlp.arize.com:443")
        else:
            endpoint = os.environ.get("ARIZE_OTLP_ENDPOINT", "otlp.arize.com:443")
        credentials = grpc.ssl_channel_credentials()
        channel = grpc.secure_channel(endpoint, credentials)
        stub = trace_service_pb2_grpc.TraceServiceStub(channel)

        metadata = [
            ("authorization", f"Bearer {api_key}"),
            ("space_id", space_id),
        ]

        response = stub.Export(request, metadata=metadata, timeout=10)
        channel.close()

        return True

    except Exception as e:
        print(f"[arize] gRPC error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def main():
    # Read JSON from stdin
    try:
        span_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"[arize] Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Arize AX credentials: config.yaml if it exists, otherwise env vars
    config = _load_config()
    if config:
        arize_cfg = config.get("backend", {}).get("arize", {})
        api_key = arize_cfg.get("api_key")
        space_id = arize_cfg.get("space_id")
    else:
        api_key = os.environ.get("ARIZE_API_KEY")
        space_id = os.environ.get("ARIZE_SPACE_ID")

    if not api_key or not space_id:
        print("[arize] ARIZE_API_KEY and ARIZE_SPACE_ID required (set in config.yaml or env)", file=sys.stderr)
        sys.exit(1)

    success = send_to_arize_grpc(span_data, api_key, space_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
