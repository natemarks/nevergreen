#!/usr/bin/env bash
set -Eeuoxv pipefail

# AWS CDK CLI and Construct Library Update Script
#
# PURPOSE:
# This script updates both the AWS CDK CLI (npm package) and the AWS CDK Construct
# Library (Python package) to their latest versions while ensuring compatibility.
#
# COMPATIBILITY RULES:
# As of February 2025, the CDK CLI and construct library have independent versioning.
# The key compatibility rule is: CLI release date >= Library release date
# Reference: https://aws.amazon.com/blogs/opensource/aws-cdk-is-splitting-construct-library-and-cli/
#
# - The AWS CDK Toolkit CLI must be at least the version that was current when the
#   construct library version was released
# - It's always safe to use a NEWER CLI version with an OLDER library version
# - Using an OLDER CLI with a NEWER library may fail with cloud assembly schema errors
# - Compatibility table: https://github.com/aws/aws-cdk-cli/blob/main/COMPATIBILITY.md
# - Official docs: https://docs.aws.amazon.com/cdk/v2/guide/versioning.html
#
# STRATEGY:
# Install both packages at their latest versions. Since the CLI is updated more
# frequently than the library and always supports all prior library versions, this
# ensures compatibility.
#
# NOTE ON NPM PREFIX:
# The --prefix flag forces install in the current directory. Without it, npm may
# install in $HOME/node_modules on pipeline agents, which causes issues.

# Get the latest CDK construct library version from PyPI
CDK_LIB_VERSION="$(curl -s https://pypi.org/pypi/aws-cdk-lib/json | jq -r '.info.version')"

# Install the latest AWS CDK CLI (npm package)
# The CLI always supports construct libraries released before it
npm install --prefix ./ aws-cdk@latest

# Update requirements.txt with the latest construct library version
sed -i '/aws-cdk-lib==/d' requirements.txt
echo "aws-cdk-lib==${CDK_LIB_VERSION}" >> requirements.txt