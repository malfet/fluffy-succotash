from mcp.server.fastmcp import FastMCP, Context
import boto3
import datetime
from typing import Optional, Dict, Any


mcp = FastMCP("PyTorch infra")
cloudtrail = boto3.client("cloudtrail")


@mcp.tool()
def get_cloudtrail_events(
    resource_name: str,
    resource_type: Optional[str] = None,
    event_name: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    max_results: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get CloudTrail events for a specific resource.

    Args:
        resource_name: Name of the resource to query (e.g. bucket name, instance ID)
        resource_type: Optional filter for resource type (e.g. AWS::S3::Bucket)
        event_name: Optional filter for specific event name
        start_time: Optional start time in ISO format (e.g. 2023-01-01T00:00:00Z)
        end_time: Optional end time in ISO format
        max_results: Maximum number of results to return (default: 50)

    Returns:
        Dictionary containing CloudTrail events and metadata
    """
    # Build the lookup attributes
    lookup_attributes = [
        {"AttributeKey": "ResourceName", "AttributeValue": resource_name}
    ]

    if resource_type:
        lookup_attributes.append(
            {"AttributeKey": "ResourceType", "AttributeValue": resource_type}
        )

    # Build the request parameters
    params = {"LookupAttributes": lookup_attributes, "MaxResults": max_results}

    # Convert ISO strings to datetime objects if provided
    if start_time:
        params["StartTime"] = datetime.datetime.fromisoformat(
            start_time.replace("Z", "+00:00")
        )
    if end_time:
        params["EndTime"] = datetime.datetime.fromisoformat(
            end_time.replace("Z", "+00:00")
        )

    # Add optional event name filter using another lookup attribute
    if event_name:
        lookup_attributes.append(
            {"AttributeKey": "EventName", "AttributeValue": event_name}
        )

    # Make the API call to CloudTrail
    try:
        response = cloudtrail.lookup_events(**params)

        # Process the events
        events = []
        for event in response.get("Events", []):
            events.append(
                {
                    "event_id": event.get("EventId"),
                    "event_name": event.get("EventName"),
                    "event_time": event.get("EventTime").isoformat()
                    if event.get("EventTime")
                    else None,
                    "username": event.get("Username"),
                    "resources": event.get("Resources"),
                    "cloud_trail_event": event.get("CloudTrailEvent"),
                }
            )

        return {
            "total_events": len(events),
            "events": events,
            "next_token": response.get("NextToken"),
        }
    except Exception as e:
        return {"error": str(e), "status": "failed"}


def main():
    """Main entry point for the application"""
    print("Starting PyTorch infra MCP server...")
    mcp.run()


if __name__ == "__main__":
    main()
