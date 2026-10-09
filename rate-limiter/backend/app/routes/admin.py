"""Admin routes: create/list clients and change plan tiers."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import ClientRecord, get_db
from ..policies import POLICIES

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateClientRequest(BaseModel):
    api_key: str
    plan: str = "free"
    name: str = ""


class UpdatePlanRequest(BaseModel):
    plan: str


@router.get("/clients")
async def list_clients(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    records = db.query(ClientRecord).all()
    return [
        {
            "api_key": r.api_key,
            "plan": r.plan,
            "name": r.name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@router.post("/clients", status_code=201)
async def create_client(
    body: CreateClientRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if body.plan not in POLICIES:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")
    existing = db.query(ClientRecord).filter(ClientRecord.api_key == body.api_key).first()
    if existing:
        raise HTTPException(status_code=409, detail="API key already exists")
    record = ClientRecord(api_key=body.api_key, plan=body.plan, name=body.name)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"api_key": record.api_key, "plan": record.plan, "name": record.name}


@router.put("/clients/{api_key}/plan")
async def update_plan(
    api_key: str,
    body: UpdatePlanRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if body.plan not in POLICIES:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")
    record = db.query(ClientRecord).filter(ClientRecord.api_key == api_key).first()
    if not record:
        raise HTTPException(status_code=404, detail="Client not found")
    record.plan = body.plan
    db.commit()
    return {"api_key": record.api_key, "plan": record.plan}


@router.get("/plans")
async def list_plans() -> Dict[str, Any]:
    return {
        name: {
            "capacity": p.capacity,
            "refill_rate": p.refill_rate,
            "sw_limit": p.sw_limit,
            "sw_window_seconds": p.sw_window_seconds,
        }
        for name, p in POLICIES.items()
    }
