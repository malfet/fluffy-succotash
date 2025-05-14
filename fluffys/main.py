import os
from mcp.server.fastmcp import FastMCP, Context
import boto3
import datetime
<<<<<<< HEAD
from typing import Optional, Dict, Any, List
=======
from typing import List, Optional, Dict, Any
import requests
>>>>>>> origin/main


mcp = FastMCP("PyTorch infra")
cloudtrail = boto3.client("cloudtrail")
cloudwatch = boto3.client("logs")


DEFAULT_LOG_GROUPS = [
    "/aws/lambda/gh-ci-scale-up",
    "/aws/lambda/gh-ci-scale-down",
    "/aws/lambda/gh-ci-scale-up-chron",
]


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
                }
            )

        return {
            "total_events": len(events),
            "events": events,
            "next_token": response.get("NextToken"),
        }
    except Exception as e:
        return {"error": str(e), "status": "failed"}


@mcp.tool()
def query_cloudwatch_logs(
    search_pattern: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    log_groups: Optional[List[str]] = DEFAULT_LOG_GROUPS,
    ctx: Optional[Context] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Query CloudWatch logs for a specific pattern within a time period.

    Args:
        search_pattern: Pattern to search for in the logs
        start_time: The start time as a datetime object
        end_time: The end time as a datetime object
        log_groups: List of log groups to query (if None, will query all available log groups)

    Returns:
        Dictionary mapping log group names to their events
    """
    results = {}

    # Convert ISO strings to milliseconds since epoch for CloudWatch
    if start_time:
        start_time_ms = int(
            datetime.datetime.fromisoformat(
                start_time.replace("Z", "+00:00")
            ).timestamp()
            * 1000
        )
    if end_time:
        end_time_ms = int(
            datetime.datetime.fromisoformat(end_time.replace("Z", "+00:00")).timestamp()
            * 1000
        )

    # Query each log group
    for log_group in log_groups:
        try:
            # Check if log group exists
            try:
                cloudwatch.describe_log_groups(logGroupNamePrefix=log_group)
            except cloudwatch.exceptions.ResourceNotFoundException:
                print(f"Log group {log_group} does not exist, skipping...")
                continue

            # Get log streams for this group
            response = cloudwatch.filter_log_events(
                logGroupName=log_group,
                startTime=start_time_ms,
                endTime=end_time_ms,
                filterPattern=search_pattern,
                limit=10000,  # Adjust limit as needed
            )

            events = response.get("events", [])

            # Handle pagination if there are more results
            while "nextToken" in response:
                response = cloudwatch.filter_log_events(
                    logGroupName=log_group,
                    startTime=start_time_ms,
                    endTime=end_time_ms,
                    filterPattern=search_pattern,
                    nextToken=response["nextToken"],
                    limit=10000,
                )
                events.extend(response.get("events", []))

            if events:
                results[log_group] = events

        except Exception as e:
            print(f"Error querying {log_group}: {str(e)}")

    return results


@mcp.tool()
def num_instances(instance_type: Optional[str] = None) -> int:
    """
    List EC2 instances with optional filtering by instance type

    Args:
        instance_type: Optional EC2 instance type to filter by (e.g., 't2.micro')

    Returns:
        Number of active instances matching the filter
    """
    ec2 = boto3.client("ec2")

    # Create filters
    filters = [{"Name": "instance-state-name", "Values": ["running"]}]

    # Add instance type filter if provided
    if instance_type:
        filters.append({"Name": "instance-type", "Values": [instance_type]})

    # Get instances
    response = ec2.describe_instances(Filters=filters)

    # Count instances across all reservations
    count = 0
    for reservation in response.get("Reservations", []):
        count += len(reservation.get("Instances", []))

    return count


@mcp.tool()
def list_instances_types(search_string: Optional[str] = None) -> List[str]:
    """
    List EC2 instance types with optional filtering by search string

    Args:
        search_string: Optional string to filter instance types (e.g., 't2')

    Returns:
        List of instance types matching the filter
    """
    ec2 = boto3.client("ec2")

    # Initialize variables for pagination
    all_instance_types = []
    next_token = None

    # Loop to handle pagination from AWS API
    while True:
        # Prepare parameters for the API call
        params = {}
        if next_token:
            params["NextToken"] = next_token

        # Get instance types with pagination
        response = ec2.describe_instance_types(**params)

        # Add instance types from this page
        for it in response["InstanceTypes"]:
            if search_string is None or search_string in it["InstanceType"]:
                all_instance_types.append(it["InstanceType"])

        # Check if there are more pages
        next_token = response.get("NextToken")
        if not next_token:
            break

    return all_instance_types


@mcp.tool()
def list_instances_connected_to_github() -> List:
    """
    List EC2 instances that are registered to GitHub at the organization level

    Returns:
        List of instance IDs or error messages
    """
    github_token = os.getenv("GITHUB_TOKEN_ADMIN_READ")
    if not github_token:
        return ["GITHUB_TOKEN_ADMIN_READ environment variable is not set."]

    import re

    # GitHub API endpoint for organization's self-hosted runners
    # This assumes the organization name is known or can be configured
    org_name = "pytorch"
    base_url = f"https://api.github.com/orgs/{org_name}/actions/runners"

    # Set default per_page to 100 (GitHub max)
    current_url = f"{base_url}?per_page=100"

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Initialize list for all runners
    all_instances = []

    try:
        # Loop through all pages
        while current_url:
            # Make request to GitHub API
            response = requests.get(current_url, headers=headers)
            response.raise_for_status()

            data = response.json()

            # Extract instance information from this page
            for runner in data.get("runners", []):
                # Look for EC2 instance identifiers
                # This may be in labels, name, or other fields depending on how the runner was registered
                # Add any identifiable information about the instance
                instance_info = f"{runner.get('id')} - {runner.get('name')} ({runner.get('status')})"
                all_instances.append(instance_info)

            # Check for Link header to handle pagination
            link_header = response.headers.get("Link")

            # Reset current_url to None to exit loop if no next page
            current_url = None

            # Parse Link header if present to get next page URL
            if link_header:
                links = {}
                # Parse the Link header format: <url>; rel="next", <url>; rel="last", etc.
                for link in link_header.split(","):
                    # Extract URL and rel values
                    url_match = re.search(r"<(.+?)>", link)
                    rel_match = re.search(r'rel="(.+?)"', link)

                    if url_match and rel_match:
                        links[rel_match.group(1)] = url_match.group(1)

                # Get the next page URL if it exists
                current_url = links.get("next")

        if not all_instances:
            return ["No EC2 instances found connected to GitHub."]

        return all_instances

    except requests.exceptions.RequestException as e:
        return [f"Error connecting to GitHub API: {str(e)}"]
    except Exception as e:
        return [f"Unexpected error: {str(e)}"]


def main():
    """Main entry point for the application"""
    print("Starting PyTorch infra MCP server...")
    mcp.run()


if __name__ == "__main__":
    main()
