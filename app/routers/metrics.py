"""
Metrics Router - Prometheus Metrics Endpoint

Exposes /metrics endpoint for Prometheus scraping.
"""

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from ..utils.metrics import format_prometheus_metrics

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("")
@router.get("/")
async def get_metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus text format for scraping.
    """
    metrics_text = format_prometheus_metrics()
    return PlainTextResponse(
        content=metrics_text,
        media_type="text/plain; charset=utf-8"
    )
