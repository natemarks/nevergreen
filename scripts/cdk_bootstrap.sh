#!/usr/bin/env bash

AWS_REGION="$(aws configure get region)"
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "bootstrap aws://${AWS_ACCOUNT_ID}/${AWS_REGION}"