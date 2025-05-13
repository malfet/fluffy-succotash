# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This repository contains a Model Context Protocol (MCP) implementation for Claude on AWS Bedrock.

## Main Components

### claude-mcp.py

This script provides:
1. Functions to list EC2 instances with SSM capabilities
2. The ability to execute commands on these instances via SSM
3. A Model Context Protocol (MCP) implementation to provide Claude with relevant context about infrastructure when used with a Bedrock agent

Key classes:
- `EC2Manager`: Manages EC2 instances with SSM integration
- `ModelContextProtocol`: Implements the MCP spec to provide Claude with relevant context

## Usage Instructions

### Requirements

- boto3 installed (`pip install boto3`)
- AWS CLI configured with appropriate permissions
- SSM agent installed on target EC2 instances

### Running the Script

Basic commands:

```bash
# List EC2 instances
python claude-mcp.py --list-only

# Filter instances by type and name
python claude-mcp.py --list-only --types t2.micro --name-prefix my-server

# Run a command on a specific instance
python claude-mcp.py --instance i-1234567890abcdef --command "df -h"

# Query Claude with MCP context
python claude-mcp.py --query "What instances do I have running?"

# Interactive mode
python claude-mcp.py --interactive
```

### AWS Authentication

The script supports AWS profiles and regions:

```bash
python claude-mcp.py --profile myprofile --region us-west-2
```