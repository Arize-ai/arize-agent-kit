#!/usr/bin/env python3
"""
Send OTLP spans to Arize AX via gRPC.
Phoenix uses REST API directly from bash - no Python needed.

Install dependencies:
  pip install opentelemetry-proto grpcio
"""

import json
import os
import sys


def send_to_arize_grpc(span_data: dict, api_key: str, space_id: str) -> bool:
    """Send spans to Arize using gRPC with proper trace IDs."""
    try:
        import grpc
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2_grpc
        from opentelemetry.proto.trace.v1 import trace_pb2
        from opentelemetry.proto.common.v1 import common_pb2
        from opentelemetry.proto.resource.v1 import resource_pb2
        
        # Get project name from environment
        project_name = os.environ.get("ARIZE_PROJECT_NAME", "claude-code")
        
        # Build the protobuf message from our JSON
        resource_spans = []
        
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
                if "stringValue" in value:
                    resource_attrs.append(common_pb2.KeyValue(
                        key=key,
                        value=common_pb2.AnyValue(string_value=value["stringValue"])
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
                        if "stringValue" in value:
                            attrs.append(common_pb2.KeyValue(
                                key=key,
                                value=common_pb2.AnyValue(string_value=value["stringValue"])
                            ))
                        elif "intValue" in value:
                            attrs.append(common_pb2.KeyValue(
                                key=key,
                                value=common_pb2.AnyValue(int_value=int(value["intValue"]))
                            ))
                        elif "doubleValue" in value:
                            attrs.append(common_pb2.KeyValue(
                                key=key,
                                value=common_pb2.AnyValue(double_value=float(value["doubleValue"]))
                            ))
                    
                    # Build span
                    span = trace_pb2.Span(
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        name=s.get("name", "span"),
                        kind=s.get("kind", 1),
                        start_time_unix_nano=int(s.get("startTimeUnixNano", 0)),
                        end_time_unix_nano=int(s.get("endTimeUnixNano", 0)),
                        attributes=attrs,
                        status=trace_pb2.Status(code=trace_pb2.Status.STATUS_CODE_OK),
                    )
                    spans.append(span)
                
                scope_spans.append(trace_pb2.ScopeSpans(spans=spans))
            
            resource_spans.append(trace_pb2.ResourceSpans(
                resource=resource,
                scope_spans=scope_spans,
            ))
        
        # Create the request
        request = trace_service_pb2.ExportTraceServiceRequest(
            resource_spans=resource_spans
        )
        
        # Send via gRPC (endpoint is configurable for hosted Arize instances)
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
    
    # Arize AX credentials
    api_key = os.environ.get("ARIZE_API_KEY")
    space_id = os.environ.get("ARIZE_SPACE_ID")
    
    if not api_key or not space_id:
        print("[arize] ARIZE_API_KEY and ARIZE_SPACE_ID required", file=sys.stderr)
        sys.exit(1)
    
    success = send_to_arize_grpc(span_data, api_key, space_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
