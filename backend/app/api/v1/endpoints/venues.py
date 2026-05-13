from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.venue import Venue
from app.models.user import User
from app.schemas.academic import VenueSearchItem, VenueSearchResponse

router = APIRouter(prefix="/venues", tags=["venues"])


@router.get("/search", response_model=VenueSearchResponse)
def search_venues(
    q: str = Query(..., min_length=2, description="Venue title, publisher, or subject query"),
    limit: int = Query(20, ge=1, le=100),
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))] = None,
) -> VenueSearchResponse:
    query = (
        db.query(Venue)
        .options(selectinload(Venue.subjects), selectinload(Venue.metrics), selectinload(Venue.policies))
        .filter(
            or_(
                Venue.title.ilike(f"%{q}%"),
                Venue.canonical_title.ilike(f"%{q}%"),
                Venue.publisher.ilike(f"%{q}%"),
            )
        )
        .limit(limit)
    )
    venues = query.all()
    items = []
    for venue in venues:
        latest_metric = sorted(venue.metrics, key=lambda metric: (metric.metric_year or 0, metric.updated_at), reverse=True)
        metric = latest_metric[0] if latest_metric else None
        policy = venue.policies[0] if venue.policies else None
        items.append(
            VenueSearchItem(
                id=venue.id,
                title=venue.title,
                canonical_title=venue.canonical_title,
                venue_type=venue.venue_type.value,
                publisher=venue.publisher,
                subjects=[subject.label for subject in venue.subjects],
                metrics={
                    "metric_year": metric.metric_year if metric else None,
                    "sjr_quartile": metric.sjr_quartile if metric else None,
                    "jcr_quartile": metric.jcr_quartile if metric else None,
                    "citescore": metric.citescore if metric else None,
                    "impact_factor": metric.impact_factor if metric else None,
                    "h_index": metric.h_index if metric else None,
                },
                policy={
                    "peer_review_model": policy.peer_review_model if policy else None,
                    "open_access_policy": policy.open_access_policy if policy else None,
                    "apc_usd": policy.apc_usd if policy else None,
                    "turnaround_weeks": policy.turnaround_weeks if policy else None,
                },
                indexed_scopus=venue.indexed_scopus,
                indexed_wos=venue.indexed_wos,
                is_open_access=venue.is_open_access,
                is_hybrid=venue.is_hybrid,
            )
        )
    return VenueSearchResponse(items=items, total=len(items))
