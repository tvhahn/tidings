"""ChatGPT device-code login endpoints under `/api/v1/auth/chatgpt`.

The flow delegates to the Codex CLI (`codex login --device-auth`): /start
spawns the login and returns the verification URL + one-time code, /status
is polled by Settings until the CLI confirms the sign-in, /disconnect runs
`codex logout`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api import dependencies
from src.api.auth import require_request_auth
from src.finance import chatgpt_oauth

logger = logging.getLogger(__name__)

# The `/api/v1/auth/` prefix bypasses the auth middleware so that the
# bootstrap endpoints (login, set-password) stay reachable. These handlers
# only share the prefix — they manage the operator's linked ChatGPT account
# and must NOT be callable anonymously (an open /disconnect wipes
# credentials; an open /start binds an attacker's account). Enforce the
# standard channels per-router.
router = APIRouter(tags=["auth"], dependencies=[Depends(require_request_auth)])


class StartChatgptLoginResponse(BaseModel):
    verification_url: str
    user_code: str


class ChatgptLoginStatusResponse(BaseModel):
    connected: bool
    pending: bool
    email: str | None
    error: str | None
    verification_url: str | None
    user_code: str | None


class DisconnectChatgptResponse(BaseModel):
    ok: bool


@router.post(
    "/auth/chatgpt/start",
    response_model=StartChatgptLoginResponse,
    operation_id="startChatgptLogin",
    summary="Begin the ChatGPT device-code sign-in via the Codex CLI",
)
async def start_chatgpt_login() -> StartChatgptLoginResponse:
    try:
        result = await dependencies.run_sync(chatgpt_oauth.start_login)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return StartChatgptLoginResponse(**result)


@router.get(
    "/auth/chatgpt/status",
    response_model=ChatgptLoginStatusResponse,
    operation_id="getChatgptLoginStatus",
    summary="Poll the ChatGPT sign-in state",
)
async def get_chatgpt_login_status() -> ChatgptLoginStatusResponse:
    return ChatgptLoginStatusResponse(**chatgpt_oauth.login_status())


@router.post(
    "/auth/chatgpt/disconnect",
    response_model=DisconnectChatgptResponse,
    operation_id="disconnectChatgpt",
    summary="Disconnect a previously-linked ChatGPT account",
)
async def disconnect_chatgpt() -> DisconnectChatgptResponse:
    await dependencies.run_sync(chatgpt_oauth.disconnect)
    return DisconnectChatgptResponse(ok=True)
