"""总路由：把所有子路由挂到 /api 前缀下。"""

from fastapi import APIRouter

from app.api import ai, auth, equipment, files, kb, lab, reservation, user

api = APIRouter(prefix="/api")

api.include_router(auth.router)
api.include_router(user.router)
api.include_router(files.router)
api.include_router(kb.router)
api.include_router(lab.router)
api.include_router(equipment.router)
api.include_router(reservation.router)
api.include_router(ai.router)
