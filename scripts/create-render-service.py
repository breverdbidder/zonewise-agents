#!/usr/bin/env python3
"""
Render API Service Creator
Creates zonewise-agents service programmatically using Render API

Requires: RENDER_API_KEY environment variable
Get API key from: https://dashboard.render.com/account/api-keys
"""

import os
import json
import requests
from typing import Dict, Optional

RENDER_API_BASE = "https://api.render.com/v1"


def create_web_service(api_key: str, config: Dict) -> Dict:
    """Create a new web service on Render."""
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "type": "web_service",
        "name": config["name"],
        "ownerId": config.get("owner_id"),  # Can be user or team ID
        "repo": config["repo"],
        "branch": config.get("branch", "main"),
        "runtime": "python",
        "buildCommand": config["build_command"],
        "startCommand": config["start_command"],
        "plan": config.get("plan", "starter"),  # free, starter, standard, pro
        "envVars": config["env_vars"],
        "healthCheckPath": config.get("health_check_path", "/health"),
        "autoDeploy": config.get("auto_deploy", True),
    }
    
    response = requests.post(
        f"{RENDER_API_BASE}/services",
        headers=headers,
        json=payload
    )
    
    if response.status_code in [200, 201]:
        return response.json()
    else:
        raise Exception(f"Failed to create service: {response.status_code} - {response.text}")


def get_owner_id(api_key: str) -> str:
    """Get the owner ID (user or team) for the authenticated account."""
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Get user info
    response = requests.get(
        f"{RENDER_API_BASE}/owners",
        headers=headers
    )
    
    if response.status_code == 200:
        owners = response.json()
        if owners and len(owners) > 0:
            return owners[0]["owner"]["id"]
    
    raise Exception("Could not determine owner ID")


def main():
    # Get API key from environment
    api_key = os.getenv("RENDER_API_KEY")
    if not api_key:
        print("❌ RENDER_API_KEY environment variable not set")
        print("Get your API key from: https://dashboard.render.com/account/api-keys")
        return 1
    
    print("🔍 Getting owner ID...")
    try:
        owner_id = get_owner_id(api_key)
        print(f"✅ Owner ID: {owner_id}")
    except Exception as e:
        print(f"❌ Error getting owner ID: {e}")
        return 1
    
    # Configuration for zonewise-agents
    config = {
        "name": "zonewise-agents",
        "owner_id": owner_id,
        "repo": "https://github.com/breverdbidder/zonewise-agents",
        "branch": "main",
        "build_command": "pip install -r requirements.txt",
        "start_command": "uvicorn server.main:app --host 0.0.0.0 --port $PORT",
        "plan": "starter",  # $7/month - change to "free" for free tier
        "health_check_path": "/health",
        "auto_deploy": True,
        "env_vars": [
            {
                "key": "SUPABASE_URL",
                "value": os.getenv("SUPABASE_URL", "https://mocerqjnksmhcjzxrewo.supabase.co")
            },
            {
                "key": "SUPABASE_KEY",
                "value": os.getenv("SUPABASE_KEY", "")
            },
            {
                "key": "ANTHROPIC_API_KEY",
                "value": os.getenv("ANTHROPIC_API_KEY", "")
            },
            {
                "key": "GOOGLE_API_KEY",
                "value": os.getenv("GOOGLE_API_KEY", "")
            },
        ]
    }
    
    print("🚀 Creating zonewise-agents service on Render...")
    try:
        service = create_web_service(api_key, config)
        print("✅ Service created successfully!")
        print(f"\n📋 Service Details:")
        print(f"   ID: {service.get('service', {}).get('id')}")
        print(f"   Name: {service.get('service', {}).get('name')}")
        print(f"   URL: {service.get('service', {}).get('serviceDetails', {}).get('url')}")
        print(f"\n🔗 Dashboard: https://dashboard.render.com/web/{service.get('service', {}).get('id')}")
        print(f"\n⏳ Initial deployment starting... Check dashboard for status.")
        return 0
    except Exception as e:
        print(f"❌ Error creating service: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
