#!/bin/bash
set -e
echo "Deploying Pressroom to Fly.io..."
fly deploy --remote-only
echo "Done. https://pressroomhq.fly.dev"
