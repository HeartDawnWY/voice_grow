"""
VoiceGrow Server - 主应用入口

基于 FastAPI 的语音交互服务器
"""

import asyncio
import os
import uuid
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .config import get_settings
from .api import websocket_router, http_router
from .api.websocket import set_pipeline
from .core.asr import ASRService
from .core.nlu import NLUService
from .core.tts import create_tts_service
from .core.llm import LLMService
from .core.pipeline import VoicePipeline
from .services.minio_service import MinIOService
from .services.content_service import ContentService
from .services.session_service import SessionService
from .services.redis_service import init_redis_service, close_redis_service
from .services.play_queue_service import PlayQueueService
from .handlers import HandlerRouter
from .services.youtube_service import YouTubeService
from .models.response import ErrorCode, BusinessException, error_response
from .utils.logger import setup_logging

# 配置日志
setup_logging(level="INFO", structured=False)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()

    logger.info("=" * 50)
    logger.info("VoiceGrow Server 启动中...")
    logger.info("=" * 50)

    # 1. 初始化数据库连接
    logger.info("初始化数据库连接...")
    engine = create_async_engine(
        settings.database.url,
        pool_size=settings.database.pool_size,
        pool_recycle=settings.database.pool_recycle,
        echo=settings.server.debug
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # 2. 初始化 Redis 缓存服务
    logger.info("初始化 Redis 缓存服务...")
    redis_service = await init_redis_service(settings.redis)

    # 3. 初始化 MinIO 服务
    logger.info("初始化 MinIO 服务...")
    minio_service = MinIOService(settings.minio)

    # 设置 bucket 公开只读 (VPS Nginx 反代访问无需签名)
    if settings.minio.public_base_url:
        await minio_service.set_public_read()

    # 4. 初始化核心服务
    logger.info("初始化 ASR 服务...")
    asr_service = ASRService(settings.asr)
    await asr_service.initialize()

    logger.info(f"初始化 TTS 服务 (backend={settings.tts.backend})...")
    tts_service = create_tts_service(settings.tts, minio_service)

    logger.info("初始化 LLM 服务...")
    llm_service = LLMService(settings.llm)
    await llm_service.initialize()

    logger.info("初始化 NLU 服务...")
    nlu_service = NLUService(llm_service)

    # 5. 初始化会话服务
    logger.info("初始化会话服务...")
    session_service = SessionService(settings.redis, redis_client=redis_service.client)

    # 6. 初始化播放队列服务
    logger.info("初始化播放队列服务...")
    play_queue_service = PlayQueueService(redis_service)

    # 7. 初始化业务服务
    logger.info("初始化内容服务...")
    content_service = ContentService(session_factory, minio_service, redis_service)

    # 8. 初始化 YouTube 下载服务
    logger.info("初始化 YouTube 下载服务...")
    youtube_service = YouTubeService(minio_service, content_service)

    logger.info("初始化处理器路由...")
    handler_router = HandlerRouter(
        content_service, tts_service, llm_service, session_service,
        play_queue_service=play_queue_service,
    )

    # 9. 创建语音处理流水线
    logger.info("创建语音处理流水线...")
    pipeline = VoicePipeline(
        asr_service=asr_service,
        nlu_service=nlu_service,
        tts_service=tts_service,
        handler_router=handler_router,
        play_queue_service=play_queue_service,
        content_service=content_service,
    )
    set_pipeline(pipeline)

    # 保存到 app.state
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis_service = redis_service
    app.state.minio_service = minio_service
    app.state.asr_service = asr_service
    app.state.tts_service = tts_service
    app.state.llm_service = llm_service
    app.state.nlu_service = nlu_service
    app.state.content_service = content_service
    app.state.session_service = session_service
    app.state.play_queue_service = play_queue_service
    app.state.pipeline = pipeline
    app.state.youtube_service = youtube_service

    logger.info("=" * 50)
    logger.info(f"VoiceGrow Server 启动完成!")
    logger.info(f"WebSocket 端口: {settings.server.websocket_port}")
    logger.info(f"HTTP 端口: {settings.server.http_port}")
    logger.info("=" * 50)

    yield

    # 清理资源
    logger.info("VoiceGrow Server 关闭中...")
    await asr_service.close()
    await tts_service.close()
    await llm_service.close()
    await session_service.close()
    await close_redis_service()
    await engine.dispose()
    logger.info("VoiceGrow Server 已关闭")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    settings = get_settings()

    app = FastAPI(
        title="VoiceGrow Server",
        description="儿童语音交互服务器",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.server.debug
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # request_id 中间件
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # 全局异常处理器
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=200,
            content=error_response(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code_map = {
            400: ErrorCode.INVALID_PARAMS,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.RESOURCE_NOT_FOUND,
            409: ErrorCode.DUPLICATE_RESOURCE,
            429: ErrorCode.REQUEST_TOO_FREQUENT,
            500: ErrorCode.INTERNAL_ERROR,
            503: ErrorCode.SERVICE_UNAVAILABLE,
        }
        error_code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(error_code, str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_response(
                ErrorCode.INVALID_PARAMS,
                "请求参数校验失败",
                detail=[
                    {"field": ".".join(str(l) for l in e["loc"]), "msg": e["msg"]}
                    for e in exc.errors()
                ],
            ),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=error_response(ErrorCode.INTERNAL_ERROR, "服务内部错误"),
        )

    # 注册路由
    app.include_router(websocket_router, tags=["WebSocket"])
    app.include_router(http_router, tags=["HTTP API"])

    return app


# 创建应用实例
app = create_app()


def run_http_server():
    """运行 HTTP 服务器"""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server.host,
        port=settings.server.http_port,
        reload=settings.server.debug
    )


def run_websocket_server():
    """运行 WebSocket 服务器 (独立端口)"""
    settings = get_settings()

    # 创建专门的 WebSocket 应用
    ws_app = FastAPI()
    ws_app.include_router(websocket_router)

    uvicorn.run(
        ws_app,
        host=settings.server.host,
        port=settings.server.websocket_port
    )


async def run_dual_server():
    """同时运行 HTTP 和 WebSocket 服务器"""
    settings = get_settings()

    # HTTP 服务器配置
    http_config = uvicorn.Config(
        app,
        host=settings.server.host,
        port=settings.server.http_port,
        log_level="info"
    )
    http_server = uvicorn.Server(http_config)

    # WebSocket 服务器配置 (使用相同的 app)
    ws_config = uvicorn.Config(
        app,
        host=settings.server.host,
        port=settings.server.websocket_port,
        log_level="info"
    )
    ws_server = uvicorn.Server(ws_config)

    # 并行运行
    await asyncio.gather(
        http_server.serve(),
        ws_server.serve()
    )


if __name__ == "__main__":
    settings = get_settings()

    # 默认使用单端口模式 (HTTP 和 WebSocket 在同一端口)
    # 如果需要双端口模式，可以使用 asyncio.run(run_dual_server())
    uvicorn.run(
        "app.main:app",
        host=settings.server.host,
        port=settings.server.websocket_port,  # 默认使用 4399 端口
        reload=settings.server.debug,
        log_level="info"
    )
