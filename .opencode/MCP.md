# MCP.md
MCP configuration for documentation access in this repository.

## Goal
Provide agents with reliable access to the latest AWS CDK v2 Python API docs:

- https://docs.aws.amazon.com/cdk/api/v2/python/

## Recommended MCP Server
Use the official Fetch MCP server to read live documentation pages.

### Generic MCP client config (`mcpServers` JSON)
Add this to your MCP client configuration file:

```json
{
  "mcpServers": {
    "aws-cdk-python-docs": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-fetch"
      ],
      "env": {
        "FETCH_USER_AGENT": "cdk-starter-opencode"
      }
    }
  }
}
```

## Usage Guidance
- Prefer URLs under `https://docs.aws.amazon.com/cdk/api/v2/python/` for CDK v2 Python symbols.
- Use this MCP server when verifying construct signatures, properties, and deprecations.
- Treat local project conventions in `AGENTS.md` as authoritative when docs and repo style differ.

## Strict Allowlist (Recommended)
Use a host allowlist so this MCP server can only fetch AWS documentation.

Allow only:
- `docs.aws.amazon.com`

If your MCP client supports per-server network allowlists, configure one for
`aws-cdk-python-docs`.

Example (client-specific schema; adapt to your MCP client):

```json
{
  "mcpServers": {
    "aws-cdk-python-docs": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-fetch"],
      "env": {
        "FETCH_USER_AGENT": "cdk-starter-opencode"
      }
    }
  },
  "mcpServerPolicies": {
    "aws-cdk-python-docs": {
      "allowedHosts": ["docs.aws.amazon.com"],
      "blockedHosts": ["*"]
    }
  }
}
```

If your client does not support allowlists directly, enforce the same policy at
the runtime/network layer (container egress policy, firewall rule, or proxy).

## Quick Verification
After enabling the server, fetch this page successfully:

- https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.html

If that page resolves, the MCP server is ready for AWS CDK v2 Python lookup.
