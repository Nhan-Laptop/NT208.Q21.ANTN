from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.ai_detection import (
    AIDetectionAnalyzeRequest,
    AIDetectionAnalyzeResponse,
    AIDetectionRuleCompileRequest,
    AIDetectionRuleCompileResponse,
    AIDetectionRuleCreateRequest,
    AIDetectionRuleListResponse,
    AIDetectionRuleOut,
    AIDetectionRuleUpdateRequest,
)
from app.services.ai_detection_rule_service import (
    AIDetectionRuleCompileError,
    AIDetectionRuleError,
    AIDetectionRuleNotFoundError,
    AIDetectionRulePermissionError,
    compile_natural_language_rule,
    create_rule,
    delete_rule,
    get_runtime_rule_payloads,
    list_rules,
    update_rule,
)
from app.services.ai_detection_service import ai_detection_service

router = APIRouter(prefix="/ai-detection", tags=["ai_detection"])


def _raise_rule_error(error: Exception) -> None:
    if isinstance(error, AIDetectionRulePermissionError):
        raise HTTPException(status_code=403, detail=str(error)) from error
    if isinstance(error, AIDetectionRuleNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, AIDetectionRuleCompileError):
        status_code = 503 if "Groq is not configured" in str(error) else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    if isinstance(error, AIDetectionRuleError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=500, detail="Unexpected AI detection rule error") from error


@router.post("/rules/compile", response_model=AIDetectionRuleCompileResponse)
def compile_rule(
    payload: AIDetectionRuleCompileRequest,
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIDetectionRuleCompileResponse:
    try:
        compiled_rule, warnings = compile_natural_language_rule(
            payload.source_text,
            user_context={"role": current_user.role.value},
        )
    except Exception as exc:  # pragma: no cover - centralized mapping
        _raise_rule_error(exc)
    return AIDetectionRuleCompileResponse(compiled_rule=compiled_rule, warnings=warnings)


@router.post("/rules", response_model=AIDetectionRuleOut, status_code=201)
def create_rule_endpoint(
    payload: AIDetectionRuleCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIDetectionRuleOut:
    try:
        rule, _ = create_rule(db, current_user, payload)
    except Exception as exc:  # pragma: no cover - centralized mapping
        _raise_rule_error(exc)
    return AIDetectionRuleOut.model_validate(rule)


@router.get("/rules", response_model=AIDetectionRuleListResponse)
def list_rules_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIDetectionRuleListResponse:
    rules = [AIDetectionRuleOut.model_validate(rule) for rule in list_rules(db, current_user)]
    return AIDetectionRuleListResponse(rules=rules)


@router.patch("/rules/{rule_id}", response_model=AIDetectionRuleOut)
def update_rule_endpoint(
    rule_id: str,
    payload: AIDetectionRuleUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIDetectionRuleOut:
    try:
        rule, _ = update_rule(db, current_user, rule_id, payload)
    except Exception as exc:  # pragma: no cover - centralized mapping
        _raise_rule_error(exc)
    return AIDetectionRuleOut.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule_endpoint(
    rule_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> Response:
    try:
        delete_rule(db, current_user, rule_id)
    except Exception as exc:  # pragma: no cover - centralized mapping
        _raise_rule_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/analyze", response_model=AIDetectionAnalyzeResponse)
def analyze_text_endpoint(
    payload: AIDetectionAnalyzeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIDetectionAnalyzeResponse:
    runtime_rules = get_runtime_rule_payloads(
        db,
        current_user,
        use_custom_rules=payload.use_custom_rules,
        rule_ids=payload.rule_ids,
    )
    return ai_detection_service.analyze_text(
        payload.text,
        mode=payload.mode,
        use_custom_rules=payload.use_custom_rules,
        runtime_rule_payloads=runtime_rules,
        include_explanation=payload.include_explanation,
    )
