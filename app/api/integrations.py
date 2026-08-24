"""Aggregated connection status for external integrations — the read-only
status a real Integrations page needs (Connected / Not connected), without
introducing any new credential storage. Both Bitbucket and Redmine stay
exactly as env-optional as they already are; this endpoint only reports
what's already true."""
from fastapi import APIRouter

from bitbucket.client import BitbucketConfig
from redmine.client import RedmineConfig


router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
def integrations_status():
    bitbucket_config = BitbucketConfig.from_env()
    redmine_config = RedmineConfig.from_env()
    return {
        "bitbucket": {
            "connected": bitbucket_config.is_configured(),
            "workspace": bitbucket_config.workspace or None,
        },
        "redmine": {
            "connected": redmine_config.is_configured(),
            "project_id": redmine_config.project_id or None,
        },
    }
