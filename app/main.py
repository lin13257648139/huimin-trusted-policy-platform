from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.domain.models import (
    BenefitId,
    FeedbackRequest,
    GuidanceDraft,
    GuidanceResponse,
    HouseholdProfile,
    LivingAssessmentRequest,
    LivingAssessmentResponse,
    MaterialType,
    Office,
    ParseProfileRequest,
    ParseProfileResponse,
    PolicyCompileRequest,
    PolicyCompileResponse,
    PolicyImpactRequest,
    PolicyImpactResponse,
    PolicySource,
    ScreeningResponse,
)
from app.repositories.database import Database
from app.services.ai_runtime import ollama_runtime_status
from app.services.benefit_relations import (
    benefit_relation_governance,
    load_benefit_relation_registry,
)
from app.services.catalog import load_evidence, load_offices, load_policy_sources
from app.services.document_check import (
    DocumentValidationError,
    check_document,
    check_document_package,
)
from app.services.intent_classifier import get_intent_classifier
from app.services.living_assessment import assessment_model_governance, calculate_living_assessment
from app.services.ocr import ocr_runtime_available
from app.services.policy_compiler import analyze_policy_impact, compile_policy
from app.services.policy_version import CURRENT_DIBAO_END, TEMPORARY_RESCUE_END
from app.services.profile_parser import parse_profile
from app.services.question_engine import next_guidance_question
from app.services.readiness import build_readiness_report
from app.services.retrieval import search_evidence_result
from app.services.rule_engine import DIBAO_STANDARD, EDGE_STANDARD, ENGINE_VERSION, evaluate_profile
from app.services.rule_registry import registry_governance
from app.services.safety_validator import safety_gate_passed, validate_screening_output
from app.services.workload import (
    WorkloadBusyError,
    WorkloadTimeoutError,
    run_bounded,
    shutdown_workloads,
    start_workloads,
    workload_status,
)

database = Database(settings.database_path)
logger = logging.getLogger("huimin.request")

# Windows 注册表在部分机器上会把 .js 识别为 text/plain；配合 nosniff 会导致
# 浏览器拒绝执行全部前端脚本。显式注册静态资源类型，保证安全头与交互同时生效。
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime()
    start_workloads()
    database.initialize()
    database.purge_expired(settings.data_retention_days)
    load_evidence()
    load_benefit_relation_registry()
    load_offices()
    load_policy_sources()
    try:
        yield
    finally:
        shutdown_workloads(wait=False)


app = FastAPI(
    title="惠民智导可信政策智能平台 API",
    description="以社会救助为首个场景的可信、可解释、可追溯政策智能平台",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Request-ID", "X-Admin-Token", "X-Screening-Token"],
)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
app.mount("/demo-assets", StaticFiles(directory=BASE_DIR / "demo_assets"), name="demo-assets")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    supplied_request_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_request_id
        if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_request_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    started = perf_counter()
    response = None
    upload_limits = {
        "/api/v1/documents/precheck": (
            settings.max_upload_bytes + settings.multipart_overhead_bytes
        ),
        "/api/v1/documents/package-precheck": (
            settings.max_package_bytes + settings.multipart_overhead_bytes
        ),
    }
    if request.method == "POST" and request.url.path in upload_limits:
        raw_length = request.headers.get("content-length")
        if raw_length is None:
            response = JSONResponse(
                status_code=411,
                content={
                    "detail": {
                        "code": "CONTENT_LENGTH_REQUIRED",
                        "message": "材料上传必须提供Content-Length，禁止无边界流式请求。",
                    }
                },
            )
        else:
            try:
                content_length = int(raw_length)
            except ValueError:
                content_length = -1
            if content_length < 0:
                response = JSONResponse(
                    status_code=400,
                    content={
                        "detail": {
                            "code": "INVALID_CONTENT_LENGTH",
                            "message": "Content-Length格式无效。",
                        }
                    },
                )
            elif content_length > upload_limits[request.url.path]:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "code": "REQUEST_BODY_TOO_LARGE",
                            "message": "上传请求在解析前已因总大小超限被拒绝。",
                        }
                    },
                )
    if response is None:
        response = await call_next(request)
    elapsed_ms = (perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; worker-src 'self'; "
        "manifest-src 'self'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    logger.info(
        "%s %s status=%s duration_ms=%.1f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    if settings.demo_mode:
        return
    if not settings.admin_api_token or (
        not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_api_token)
    ):
        raise HTTPException(status_code=403, detail="治理接口需要管理员令牌")


async def _run_workload(kind, function, *args, timeout: float, **kwargs):
    try:
        return await run_bounded(kind, function, *args, timeout=timeout, **kwargs)
    except WorkloadBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "2"}) from exc
    except WorkloadTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    return FileResponse(
        settings.static_dir / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service_id": "huimin-guide",
        "service": settings.app_name,
        "version": settings.app_version,
        "policy_as_of": settings.policy_as_of,
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/api/v1/metadata")
async def metadata() -> dict[str, object]:
    ai_status = await _run_workload(
        "llm",
        ollama_runtime_status,
        timeout=min(settings.ollama_timeout_seconds, 3),
    )
    policy_watch = [
        {
            "source_id": source.source_id,
            "title": source.title,
            "effective_to": source.effective_to,
            "status": source.status,
        }
        for source in load_policy_sources()
        if source.effective_to
    ]
    return {
        "name": settings.app_name,
        "runtime_mode": "demo" if settings.demo_mode else "authenticated",
        "version": settings.app_version,
        "region": "广州市",
        "policy_as_of": settings.policy_as_of,
        "official_sources": len(load_policy_sources()),
        "evidence_fragments": len(load_evidence()),
        "office_records": len(load_offices()),
        "mvp_benefits": 5,
        "parameters": {
            "dibao_standard": str(DIBAO_STANDARD),
            "edge_standard": str(EDGE_STANDARD),
            "unit": "元/人/月",
        },
        "ai_runtime": ai_status,
        "ai_provider": ai_status["active_provider"],
        "ai_components": {
            "intent_router": get_intent_classifier().model_version,
            "profile_llm": ai_status["active_provider"] if ai_status["reachable"] else None,
            "embedding_model": ai_status["embedding_model"],
            "ocr": "RapidOCR/ONNX Runtime"
            if settings.ocr_enabled and ocr_runtime_available()
            else None,
        },
        "policy_watch": policy_watch,
        "engine_version": ENGINE_VERSION,
        "capabilities": [
            "时态规则",
            "三值推理",
            "本地字符N-gram意图分类（只排序导办事项）",
            "Policy2Rule候选编译",
            "版本差异与影响分析",
            "证据链",
            "组合导办",
            "事项关系图谱与分层转介",
            "本地OCR内容分类与材料质量预检",
        ],
        "data_retention_days": settings.data_retention_days,
        "admin_protected": not settings.demo_mode,
        "bounded_workloads": workload_status(),
        "ocr": {
            "enabled": settings.ocr_enabled and ocr_runtime_available(),
            "provider": "RapidOCR/ONNX Runtime"
            if settings.ocr_enabled and ocr_runtime_available()
            else None,
            "reason": None
            if settings.ocr_enabled and ocr_runtime_available()
            else "OCR被配置关闭或运行依赖未安装",
            "privacy": "完整OCR文本不保存、不返回，仅返回分类证据与非身份字段候选。",
        },
        "disclaimer": "仅用于申请前预筛和导办，不具有行政审批效力。",
    }


@app.get("/api/v1/system/readiness")
async def system_readiness() -> dict[str, object]:
    return await _run_workload(
        "llm",
        build_readiness_report,
        timeout=min(settings.ollama_timeout_seconds + 1, 5),
    )


@app.post("/api/v1/profile/parse", response_model=ParseProfileResponse)
async def parse_profile_endpoint(request: ParseProfileRequest) -> ParseProfileResponse:
    return await _run_workload(
        "llm",
        parse_profile,
        request,
        timeout=settings.ollama_timeout_seconds + 5,
    )


@app.post("/api/v1/guidance/next-question", response_model=GuidanceResponse)
async def guidance_next_question(draft: GuidanceDraft) -> GuidanceResponse:
    return next_guidance_question(draft)


@app.post(
    "/api/v1/assessments/living-conditions",
    response_model=LivingAssessmentResponse,
)
async def living_conditions_assessment(
    request: LivingAssessmentRequest,
) -> LivingAssessmentResponse:
    """执行可追溯的第二版综合评估计算，不替代入户调查或行政审核。"""

    return calculate_living_assessment(request)


@app.post("/api/v1/screenings", response_model=ScreeningResponse)
async def create_screening(
    profile: HouseholdProfile,
    request: Request,
    persist: bool = Query(
        default=False,
        description="用户主动选择保存结构化预筛记录30天；默认无状态。",
    ),
) -> ScreeningResponse:
    snapshot, results, warnings = evaluate_profile(profile)
    safety_validation = validate_screening_output(profile, results)
    if not safety_gate_passed(safety_validation):
        failed_ids = safety_validation.get("failed_check_ids", [])
        database.record_audit_event(
            "screening.safety_blocked",
            entity_id=None,
            details={
                "failed_check_ids": failed_ids,
                "query_date": profile.query_date.isoformat(),
                "district": profile.district,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SAFETY_GATE_BLOCKED",
                "message": "安全校验未通过，本次结果已阻断，未展示、未保存，也不可打印导出。",
                "failed_check_ids": failed_ids,
                "next_action": "请核对输入与政策证据；如情况紧急，请直接联系所在街道或广州12345。",
            },
        )
    screening_id = f"HM-{uuid4().hex[:12].upper()}"
    office_records = load_offices()
    office = next((item for item in office_records if item.region == profile.district), None)
    if office is None:
        office = next((item for item in office_records if item.region == "广州市"), None)
    first_actionable = next(
        (item for item in results if item.plan_role == "primary"),
        next(
            (item for item in results if item.plan_role in {"manual", "alternative"}),
            results[0],
        ),
    )
    action_label = "优先查看" if first_actionable.plan_role == "primary" else "优先核验"
    guidance_summary = [
        f"{action_label}：{first_actionable.name}（{first_actionable.summary}）",
        "先补齐报告中的最小必要信息，再携带材料咨询对应窗口。",
        "办理前建议电话确认受理地点、材料版本和服务时间。",
    ]
    alternatives = [item.name for item in results if item.plan_role == "alternative"]
    if alternatives:
        guidance_summary.insert(
            2,
            f"分层备选/转介：{'、'.join(alternatives)}；由窗口统一核验，避免重复申请。",
        )
    parallel_pairs = {
        tuple(sorted((item.benefit_id, relation.related_benefit_id)))
        for item in results
        for relation in item.plan_relations
        if relation.relation_type == "parallel_assessment"
    }
    if parallel_pairs:
        guidance_summary.insert(1, "低保边缘与刚性支出困难可分别认定：建议同窗并行核验并复用经济状况材料。")
    if profile.urgent_event is True and profile.basic_life_interrupted is True:
        guidance_summary.insert(0, "基本生活已受严重影响：请优先联系所在街道或广州12345。")
    response = ScreeningResponse(
        screening_id=screening_id,
        created_at=datetime.now(UTC),
        policy_snapshot=snapshot.snapshot_id,
        query_date=profile.query_date,
        district=profile.district,
        profile_summary={
            "household_size": profile.household_size,
            "per_capita_monthly_income": (
                str(profile.per_capita_monthly_income)
                if profile.per_capita_monthly_income is not None
                else None
            ),
            "rigid_expenses_12m": (
                str(profile.rigid_expenses_12m) if profile.rigid_expenses_12m is not None else None
            ),
            "urgent_event": profile.urgent_event,
            "data_minimized": True,
        },
        results=results,
        global_warnings=warnings,
        recommended_office=office.model_dump(mode="json") if office else None,
        guidance_summary=guidance_summary,
        safety_validation=safety_validation,
        persisted=persist,
        data_retention_days=settings.data_retention_days if persist else 0,
        engine_version=ENGINE_VERSION,
        combination_plan_version=benefit_relation_governance()["registry_version"],
        disclaimer=(
            "本结果基于用户自述和当前已核验公开政策生成，仅供申请前预筛、备料和咨询参考；"
            "最终资格、金额与材料要求以主管部门审核为准。"
        ),
    )
    if persist:
        stored_profile = profile.model_dump(mode="json")
        # 自由文本只用于当次抽取/解释，不进入持久化记录，降低敏感叙述泄露风险。
        stored_profile["user_statement"] = None
        manage_token = database.save_screening(
            screening_id=screening_id,
            query_date=profile.query_date.isoformat(),
            district=profile.district,
            policy_snapshot=snapshot.snapshot_id,
            request_payload=stored_profile,
            result_payload=response.model_dump(mode="json"),
            retention_days=settings.data_retention_days,
        )
        response.screening_token = manage_token
    return response


@app.get("/api/v1/screenings/{screening_id}", response_model=ScreeningResponse)
async def get_screening(
    screening_id: str,
    x_screening_token: str | None = Header(default=None, alias="X-Screening-Token"),
) -> ScreeningResponse:
    if not x_screening_token:
        raise HTTPException(status_code=403, detail="需要本次预筛记录的访问凭证")
    result = database.get_screening(screening_id, x_screening_token)
    if result is None:
        raise HTTPException(status_code=403, detail="记录不存在或访问凭证无效")
    if not safety_gate_passed(result.get("safety_validation", {})):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "STORED_RESULT_SAFETY_BLOCKED",
                "message": "该历史记录未通过当前安全发布门，禁止重新展示或导出。",
            },
        )
    return ScreeningResponse.model_validate(result)


@app.delete("/api/v1/screenings/{screening_id}")
async def delete_screening(
    screening_id: str,
    x_screening_token: str | None = Header(default=None, alias="X-Screening-Token"),
) -> dict[str, object]:
    if not x_screening_token or not database.delete_screening(screening_id, x_screening_token):
        raise HTTPException(status_code=403, detail="记录不存在或删除凭证无效")
    return {"deleted": True, "screening_id": screening_id}


@app.post("/api/v1/feedback", status_code=201)
async def create_feedback(
    request: FeedbackRequest,
    x_screening_token: str | None = Header(default=None, alias="X-Screening-Token"),
) -> dict[str, object]:
    if request.comment and request.comment.strip() and not request.consent_to_store_comment:
        raise HTTPException(status_code=400, detail="保存文字反馈前需要明确同意")
    if not x_screening_token or not database.screening_token_valid(
        request.screening_id, x_screening_token
    ):
        raise HTTPException(status_code=403, detail="记录不存在或反馈凭证无效")
    saved = database.save_feedback(request.model_dump())
    if not saved:
        raise HTTPException(status_code=404, detail="预筛记录不存在")
    return {"saved": True, "message": "感谢反馈，问题将进入人工复核队列。"}


@app.get("/api/v1/offices", response_model=list[Office])
async def offices(district: str | None = Query(default=None, max_length=20)) -> list[Office]:
    records = load_offices()
    if district:
        matched = [item for item in records if item.region == district]
        return matched or [item for item in records if item.region == "广州市"]
    return records


@app.get("/api/v1/policies", response_model=list[PolicySource])
async def policies(topic: str | None = Query(default=None, max_length=30)) -> list[PolicySource]:
    records = load_policy_sources()
    if topic:
        return [item for item in records if topic in item.topic or topic in item.title]
    return records


@app.get("/api/v1/evidence/search")
async def evidence_search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=5, ge=1, le=10),
    as_of: date | None = Query(default=None, description="政策生效日过滤，默认系统政策快照日"),
) -> dict[str, object]:
    return await _run_workload(
        "llm",
        search_evidence_result,
        q,
        limit=limit,
        as_of=as_of,
        timeout=settings.ollama_timeout_seconds + 5,
    )


@app.post("/api/v1/documents/precheck")
async def document_precheck(
    file: Annotated[UploadFile, File(description="JPG/PNG/WEBP/PDF，最大8MB")],
    material_type: Annotated[MaterialType, Form()] = MaterialType.AUTO,
    consent: Annotated[bool, Form()] = False,
) -> dict[str, object]:
    if not consent:
        raise HTTPException(status_code=400, detail="请先确认同意仅在本次请求中处理文件")
    content = await file.read(settings.max_upload_bytes + 1)
    try:
        result = await _run_workload(
            "document",
            check_document,
            filename=file.filename or "upload",
            content=content,
            declared_type=material_type.value,
            max_bytes=settings.max_upload_bytes,
            max_image_pixels=settings.max_image_pixels,
            timeout=settings.document_timeout_seconds,
        )
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return result.as_dict()


@app.post("/api/v1/documents/package-precheck")
async def document_package_precheck(
    files: Annotated[list[UploadFile], File(description="最多12份JPG/PNG/WEBP/PDF")],
    benefit_id: Annotated[BenefitId, Form()] = BenefitId.MINIMUM_LIVING,
    consent: Annotated[bool, Form()] = False,
) -> dict[str, object]:
    if not consent:
        raise HTTPException(status_code=400, detail="请先确认同意仅在本次请求中处理文件")
    if not files or len(files) > settings.max_package_files:
        raise HTTPException(
            status_code=400,
            detail=f"每次需上传1至{settings.max_package_files}份材料",
        )
    payloads: list[tuple[str, bytes]] = []
    total_bytes = 0
    try:
        for upload in files:
            content = await upload.read(settings.max_upload_bytes + 1)
            if len(content) > settings.max_upload_bytes:
                raise DocumentValidationError(
                    f"单个文件超过{settings.max_upload_bytes // 1024 // 1024}MB限制"
                )
            total_bytes += len(content)
            if total_bytes > settings.max_package_bytes:
                raise DocumentValidationError(
                    f"材料包总大小超过{settings.max_package_bytes // 1024 // 1024}MB限制"
                )
            payloads.append((upload.filename or "upload", content))

        async def check_payloads_in_order():
            # RapidOCR/ONNX can oversubscribe CPU threads when several pages from
            # one request start together. Keep a package ordered while the shared
            # bounded executor still controls concurrency across requests.
            results = []
            for filename, content in payloads:
                results.append(
                    await _run_workload(
                        "document",
                        check_document,
                        filename=filename,
                        content=content,
                        declared_type=None,
                        max_bytes=settings.max_upload_bytes,
                        max_image_pixels=settings.max_image_pixels,
                        timeout=settings.document_timeout_seconds,
                    )
                )
            return results

        checked = await asyncio.wait_for(
            check_payloads_in_order(), timeout=settings.package_timeout_seconds
        )
        total_pages = sum(item.page_count for item in checked)
        if total_pages > settings.max_package_pages:
            raise DocumentValidationError(
                f"材料包总页数超过{settings.max_package_pages}页限制"
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"材料包处理超过{settings.package_timeout_seconds:g}秒限制",
        ) from exc
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()
    return check_document_package(benefit_id=benefit_id.value, documents=checked)


@app.get("/api/v1/admin/dashboard", dependencies=[Depends(require_admin_token)])
async def admin_dashboard() -> dict[str, object]:
    database.purge_expired(settings.data_retention_days)
    stats = database.dashboard_stats()
    governance = registry_governance()
    readiness = await _run_workload(
        "llm",
        build_readiness_report,
        timeout=min(settings.ollama_timeout_seconds + 1, 5),
    )
    return {
        **stats,
        "rule_registry": governance,
        "benefit_relation_registry": benefit_relation_governance(),
        "living_assessment_model": assessment_model_governance(),
        "policy_health": {
            "verified_sources": len([item for item in load_policy_sources() if item.priority == "P0"]),
            "total_sources": len(load_policy_sources()),
            "dibao_rule_expires": CURRENT_DIBAO_END.isoformat(),
            "temporary_rule_expires": TEMPORARY_RESCUE_END.isoformat(),
            "alerts": [
                rule["name"] + "：" + rule["status"]
                for rule in governance["rules"]
                if rule["status"] != "verified"
            ],
        },
        "privacy": {
            "raw_documents_stored": False,
            "user_statement_persisted": False,
            "feedback_comment_persisted_with_consent": True,
            "audit_enabled": True,
            "retention_days": settings.data_retention_days,
            "audit_retention_days": settings.data_retention_days,
            "admin_token_required": not settings.demo_mode,
            "runtime_mode": "demo" if settings.demo_mode else "authenticated",
        },
        "system_readiness": readiness,
    }


@app.post(
    "/api/v1/admin/policy/compile",
    response_model=PolicyCompileResponse,
    dependencies=[Depends(require_admin_token)],
)
async def compile_policy_endpoint(request: PolicyCompileRequest) -> PolicyCompileResponse:
    """把政策文本编译为不可直接发布的候选规则，并执行静态校验。"""

    return await _run_workload(
        "llm",
        compile_policy,
        request,
        timeout=settings.ollama_timeout_seconds + 5,
    )


@app.post(
    "/api/v1/admin/policy/impact",
    response_model=PolicyImpactResponse,
    dependencies=[Depends(require_admin_token)],
)
async def policy_impact_endpoint(request: PolicyImpactRequest) -> PolicyImpactResponse:
    """用合成回归案例分析候选阈值变化，不估算真实人群规模。"""

    return await _run_workload(
        "llm",
        analyze_policy_impact,
        request.candidate,
        timeout=settings.ollama_timeout_seconds + 5,
    )


@app.get("/{path:path}", include_in_schema=False)
async def spa_fallback(path: str) -> FileResponse:
    requested = (settings.static_dir / path).resolve()
    static_root = settings.static_dir.resolve()
    if static_root in requested.parents and requested.is_file():
        return FileResponse(requested)
    return FileResponse(settings.static_dir / "index.html")

