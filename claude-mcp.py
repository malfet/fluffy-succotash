#!/usr/bin/env python3
"""
Model Context Protocol (MCP) for Claude on AWS Bedrock

This script provides:
1. Functions to list EC2 instances with SSM capabilities
2. The ability to execute commands on these instances via SSM
3. A Model Context Protocol (MCP) implementation to provide Claude with relevant
   context about your infrastructure when used with a Bedrock agent

Requirements:
- boto3 installed (pip install boto3)
- AWS CLI configured with appropriate permissions
- SSM agent installed on target EC2 instances
"""

import json
import argparse
import time
import datetime
import sys
import os
import boto3
import uuid
import logging
from botocore.exceptions import ClientError
from typing import Dict, List, Any, Optional, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('claude-mcp')

class EC2Manager:
    """Manager for EC2 instances with SSM integration."""

    def __init__(self, profile=None, region=None):
        """Initialize with optional AWS profile and region."""
        session_kwargs = {}
        if profile:
            session_kwargs['profile_name'] = profile
        if region:
            session_kwargs['region_name'] = region
            
        self.session = boto3.Session(**session_kwargs)
        self.ec2_client = self.session.client('ec2')
        self.ssm_client = self.session.client('ssm')
        self.region = region or self.session.region_name
        
    def list_instances(self, instance_types=None, name_prefix=None, tags=None, ssm_only=True):
        """
        List EC2 instances with optional filtering.
        
        Args:
            instance_types (list): List of EC2 instance types to filter by
            name_prefix (str): Filter instances by name prefix
            tags (dict): Dictionary of tag key-value pairs to filter by
            ssm_only (bool): Only return instances available via SSM
            
        Returns:
            list: List of dictionaries containing instance information
        """
        filters = []
        
        if instance_types:
            filters.append({
                'Name': 'instance-type',
                'Values': instance_types
            })
            
        if name_prefix:
            filters.append({
                'Name': 'tag:Name',
                'Values': [f'{name_prefix}*']
            })
            
        if tags:
            for key, value in tags.items():
                filters.append({
                    'Name': f'tag:{key}',
                    'Values': [value]
                })
                
        # Only get running instances
        filters.append({'Name': 'instance-state-name', 'Values': ['running']})
        
        response = self.ec2_client.describe_instances(Filters=filters)
        
        instances = []
        for reservation in response.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                # Get the instance name from tags
                instance_name = 'Unnamed'
                for tag in instance.get('Tags', []):
                    if tag['Key'] == 'Name':
                        instance_name = tag['Value']
                        break
                
                ssm_status = self._check_ssm_status(instance['InstanceId'])
                
                # Skip if SSM is not available and ssm_only is True
                if ssm_only and ssm_status != 'Available':
                    continue
                
                instances.append({
                    'InstanceId': instance['InstanceId'],
                    'Name': instance_name,
                    'Type': instance['InstanceType'],
                    'State': instance['State']['Name'],
                    'PrivateIP': instance.get('PrivateIpAddress', 'N/A'),
                    'PublicIP': instance.get('PublicIpAddress', 'N/A'),
                    'SSM_Status': ssm_status,
                    'LaunchTime': instance.get('LaunchTime', '').isoformat() if instance.get('LaunchTime') else 'N/A',
                    'Platform': instance.get('PlatformDetails', 'N/A'),
                    'Tags': instance.get('Tags', [])
                })
                
        return instances
    
    def _check_ssm_status(self, instance_id):
        """Check if instance is accessible via SSM."""
        try:
            response = self.ssm_client.describe_instance_information(
                Filters=[{'Key': 'InstanceIds', 'Values': [instance_id]}]
            )
            if response['InstanceInformationList']:
                return 'Available'
            return 'Not Available'
        except ClientError:
            return 'Unknown'
    
    def run_command(self, instance_ids, command, comment=''):
        """
        Run a command on specified EC2 instances through SSM.
        
        Args:
            instance_ids (list): List of EC2 instance IDs
            command (str): The command to execute
            comment (str): Optional comment for the command
            
        Returns:
            str: Command ID if successful
        """
        try:
            response = self.ssm_client.send_command(
                InstanceIds=instance_ids,
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': [command]},
                Comment=comment or f'Command executed via MCP at {time.strftime("%Y-%m-%d %H:%M:%S")}'
            )
            return response['Command']['CommandId']
        except ClientError as e:
            logger.error(f"Error running command: {e}")
            return None
    
    def get_command_output(self, command_id, instance_id, wait=True):
        """
        Get the output of a command execution.
        
        Args:
            command_id (str): The command ID from run_command
            instance_id (str): The instance ID the command was run on
            wait (bool): Whether to wait for command completion
            
        Returns:
            dict: Command output status and content
        """
        try:
            # Wait for command to complete if requested
            if wait:
                waiter = self.ssm_client.get_waiter('command_executed')
                waiter.wait(
                    CommandId=command_id,
                    InstanceId=instance_id
                )
            
            # Get the output
            response = self.ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id
            )
            
            return {
                'Status': response['Status'],
                'Output': response.get('StandardOutputContent', ''),
                'Error': response.get('StandardErrorContent', '')
            }
        except ClientError as e:
            logger.error(f"Error getting command output: {e}")
            return {
                'Status': 'Failed',
                'Output': '',
                'Error': str(e)
            }

class ModelContextProtocol:
    """
    Model Context Protocol (MCP) implementation for Claude on AWS Bedrock.
    
    This class implements the MCP spec to provide Claude with relevant context
    about your infrastructure when used with AWS Bedrock.
    """
    
    def __init__(self, ec2_manager=None, profile=None, region=None):
        """Initialize the MCP with an optional EC2Manager."""
        self.ec2_manager = ec2_manager or EC2Manager(profile=profile, region=region)
        self.bedrock_client = boto3.client('bedrock-runtime')
        self.claude_model_id = 'anthropic.claude-3-sonnet-20240229-v1:0'  # Update as needed
        self.session_data = {
            'session_id': str(uuid.uuid4()),
            'start_time': datetime.datetime.now().isoformat(),
            'commands': []
        }
    
    def _format_instances_for_context(self, instances):
        """Format EC2 instance information for Claude context."""
        # Simplify the instance data to include only what's needed for context
        simplified = []
        for instance in instances:
            # Extract useful tags as a dictionary
            tags_dict = {}
            for tag in instance.get('Tags', []):
                tags_dict[tag['Key']] = tag['Value']
                
            simplified.append({
                'id': instance['InstanceId'],
                'name': instance['Name'],
                'type': instance['Type'],
                'private_ip': instance['PrivateIP'],
                'platform': instance['Platform'],
                'ssm_status': instance['SSM_Status'],
                'tags': tags_dict
            })
        
        return simplified
        
    def generate_context(self, instance_types=None, name_prefix=None, tags=None, include_commands=True):
        """
        Generate context information for Claude based on infrastructure.
        
        Args:
            instance_types (list): List of EC2 instance types to filter by
            name_prefix (str): Filter instances by name prefix
            tags (dict): Dictionary of tag key-value pairs to filter by
            include_commands (bool): Whether to include command history
            
        Returns:
            dict: Context data in MCP format
        """
        # Get EC2 instances
        instances = self.ec2_manager.list_instances(
            instance_types=instance_types,
            name_prefix=name_prefix,
            tags=tags
        )
        
        # Format context information
        context = {
            "schema_version": "v1",
            "session": {
                "id": self.session_data['session_id'],
                "start_time": self.session_data['start_time']
            },
            "environment": {
                "aws_region": self.ec2_manager.region,
                "ec2_instances": self._format_instances_for_context(instances)
            }
        }
        
        # Include command history if requested
        if include_commands and self.session_data['commands']:
            context["command_history"] = self.session_data['commands']
        
        return context
    
    def run_command_on_instance(self, instance_id, command):
        """
        Run command on instance and update command history.
        
        Args:
            instance_id (str): EC2 instance ID
            command (str): Command to execute
            
        Returns:
            dict: Command output
        """
        command_id = self.ec2_manager.run_command([instance_id], command)
        if not command_id:
            return {"status": "Failed", "error": "Failed to send command"}
        
        # Get the output
        output = self.ec2_manager.get_command_output(command_id, instance_id)
        
        # Record in command history
        command_record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "instance_id": instance_id,
            "command": command,
            "status": output['Status'],
            "output": output['Output'][:1000] if len(output['Output']) > 1000 else output['Output'],
            "command_id": command_id
        }
        
        self.session_data['commands'].append(command_record)
        
        return output
    
    def query_claude(self, user_message, context=None, max_tokens=1000, temperature=0.7):
        """
        Send a query to Claude on Bedrock with MCP context.
        
        Args:
            user_message (str): The user message to send to Claude
            context (dict): Optional context override, otherwise uses generated context
            max_tokens (int): Maximum tokens in response
            temperature (float): Sampling temperature
            
        Returns:
            str: Claude's response
        """
        # Generate context if not provided
        if context is None:
            context = self.generate_context()
        
        # Format prompt with MCP
        mcp_json = json.dumps(context)
        
        # Use the Anthropic message API format
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"<mcp>\n{mcp_json}\n</mcp>\n\n{user_message}"
                    }
                ]
            }
        ]
        
        # Prepare the payload
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }
        
        try:
            # Send request to Bedrock
            response = self.bedrock_client.invoke_model(
                modelId=self.claude_model_id,
                body=json.dumps(payload)
            )
            
            # Parse the response
            response_body = json.loads(response['body'].read())
            return response_body['content'][0]['text']
            
        except Exception as e:
            logger.error(f"Error querying Claude: {e}")
            return f"Error communicating with Claude: {str(e)}"

def display_instances(instances):
    """Pretty print the instances list."""
    if not instances:
        print("No instances found matching the criteria.")
        return
    
    # Calculate column widths
    id_width = max(len(i['InstanceId']) for i in instances) + 2
    name_width = max(len(i['Name']) for i in instances) + 2
    type_width = max(len(i['Type']) for i in instances) + 2
    ip_width = max(len(i['PrivateIP']) for i in instances) + 2
    ssm_width = max(len(i['SSM_Status']) for i in instances) + 2
    
    # Print header
    header = f"{'#':<3} {'ID':<{id_width}} {'Name':<{name_width}} {'Type':<{type_width}} " \
             f"{'Private IP':<{ip_width}} {'SSM Status':<{ssm_width}}"
    print(header)
    print("-" * len(header))
    
    # Print instances
    for idx, instance in enumerate(instances, 1):
        print(f"{idx:<3} {instance['InstanceId']:<{id_width}} {instance['Name']:<{name_width}} "
              f"{instance['Type']:<{type_width}} {instance['PrivateIP']:<{ip_width}} "
              f"{instance['SSM_Status']:<{ssm_width}}")

def interactive_mode(mcp):
    """Run interactive session with Claude using MCP."""
    print("\n===== Claude MCP Interactive Mode =====")
    print("Type 'exit' to quit, 'list' to show EC2 instances, or 'run' to execute a command")
    
    instances = mcp.ec2_manager.list_instances()
    
    while True:
        user_input = input("\nYou: ").strip()
        
        if user_input.lower() == 'exit':
            break
        elif user_input.lower() == 'list':
            instances = mcp.ec2_manager.list_instances()
            display_instances(instances)
            continue
        elif user_input.lower().startswith('run'):
            # Format: run <instance_id or #> <command>
            parts = user_input.split(' ', 2)
            if len(parts) < 3:
                print("Usage: run <instance_id or #> <command>")
                continue
                
            instance_id = parts[1]
            command = parts[2]
            
            # Check if using # instead of instance ID
            if instance_id.isdigit():
                idx = int(instance_id) - 1
                if 0 <= idx < len(instances):
                    instance_id = instances[idx]['InstanceId']
                else:
                    print(f"Invalid instance number. Use 'list' to see available instances.")
                    continue
            
            print(f"Running command on {instance_id}...")
            output = mcp.run_command_on_instance(instance_id, command)
            
            print("Status:", output['Status'])
            if output['Output']:
                print("--- Output ---")
                print(output['Output'])
            
            if output['Error']:
                print("--- Error ---")
                print(output['Error'])
                
            continue
        
        # Normal query to Claude with MCP context
        print("Querying Claude with MCP context...")
        response = mcp.query_claude(user_input)
        print("\nClaude:", response)

def main():
    parser = argparse.ArgumentParser(description='Model Context Protocol (MCP) for Claude on AWS Bedrock')
    
    # AWS configuration
    parser.add_argument('--profile', help='AWS profile name')
    parser.add_argument('--region', help='AWS region')
    
    # EC2 filtering options
    parser.add_argument('--types', nargs='+', help='Instance types to filter by (e.g., t2.micro t3.small)')
    parser.add_argument('--name-prefix', help='Filter instances by name prefix')
    parser.add_argument('--tag', action='append', nargs=2, metavar=('KEY', 'VALUE'), 
                        help='Filter instances by tag (can be used multiple times)')
    
    # Command execution
    parser.add_argument('--instance', help='Instance ID to run command on')
    parser.add_argument('--command', help='Command to run on the instance')
    
    # MCP options
    parser.add_argument('--interactive', action='store_true', help='Run in interactive mode with Claude')
    parser.add_argument('--query', help='Single query to send to Claude with MCP context')
    parser.add_argument('--list-only', action='store_true', help='Only list instances, don\'t query Claude')
    
    args = parser.parse_args()
    
    # Convert the tag list to dict
    tags = {}
    if args.tag:
        for key, value in args.tag:
            tags[key] = value
    
    # Initialize MCP with EC2 manager
    mcp = ModelContextProtocol(profile=args.profile, region=args.region)
    
    # Just list instances if requested
    if args.list_only:
        instances = mcp.ec2_manager.list_instances(
            instance_types=args.types,
            name_prefix=args.name_prefix,
            tags=tags
        )
        display_instances(instances)
        return
        
    # Run a command on an instance if both instance and command are provided
    if args.instance and args.command:
        print(f"Running command on {args.instance}...")
        output = mcp.run_command_on_instance(args.instance, args.command)
        
        print("Status:", output['Status'])
        if output['Output']:
            print("--- Output ---")
            print(output['Output'])
        
        if output['Error']:
            print("--- Error ---")
            print(output['Error'])
            
        return
    
    # Single query mode
    if args.query:
        context = mcp.generate_context(
            instance_types=args.types,
            name_prefix=args.name_prefix,
            tags=tags
        )
        
        print("Sending query to Claude with MCP context...")
        response = mcp.query_claude(args.query, context)
        
        print("\nClaude's response:")
        print(response)
        return
    
    # Interactive mode
    if args.interactive:
        interactive_mode(mcp)
        return
        
    # If no specific action requested, just print usage
    parser.print_help()

if __name__ == "__main__":
    main()
