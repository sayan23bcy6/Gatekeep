"""Protected demo API endpoints."""
from __future__ import annotations

import random
from typing import Any, Dict, List

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["api"])

_PRODUCTS = [
    {"id": 1, "name": "Widget Alpha", "price": 9.99, "stock": 150},
    {"id": 2, "name": "Gadget Beta",  "price": 24.99, "stock": 80},
    {"id": 3, "name": "Device Gamma", "price": 49.99, "stock": 45},
    {"id": 4, "name": "Tool Delta",   "price": 14.99, "stock": 200},
    {"id": 5, "name": "Module Epsilon","price": 34.99, "stock": 60},
]

_ORDERS = [
    {"id": 1001, "product_id": 1, "quantity": 3, "status": "shipped"},
    {"id": 1002, "product_id": 3, "quantity": 1, "status": "processing"},
    {"id": 1003, "product_id": 2, "quantity": 5, "status": "delivered"},
]


@router.get("/products")
async def list_products(request: Request) -> List[Dict[str, Any]]:
    """Return the product catalogue (rate-limited)."""
    return _PRODUCTS


@router.get("/products/{product_id}")
async def get_product(product_id: int, request: Request) -> Dict[str, Any]:
    product = next((p for p in _PRODUCTS if p["id"] == product_id), None)
    if product is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/orders")
async def list_orders(request: Request) -> List[Dict[str, Any]]:
    """Return orders (rate-limited)."""
    return _ORDERS


@router.get("/ping")
async def ping() -> Dict[str, str]:
    return {"pong": "ok"}
