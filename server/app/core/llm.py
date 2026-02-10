"""
LLM 大语言模型服务

使用外部 ai-manager AI API (支持多模型)
特点: 多模型支持、智能缓存、自动容错
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, List, AsyncGenerator

import httpx

from ..config import LLMConfig
from ..utils.auth import generate_hmac_signature

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str   # user, assistant, system
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResult:
    """LLM 调用结果"""
    response: str
    model_used: str
    provider: str
    cached: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_time_ms: int


class ContentFilter:
    """
    内容安全过滤器

    过滤不适合儿童的内容
    """

    # 敏感词列表 (简化版)
    SENSITIVE_KEYWORDS = [
        "暴力", "血腥", "恐怖", "色情", "赌博", "毒品",
        "自杀", "自残", "政治", "宗教争议",
    ]

    def is_safe(self, text: str) -> bool:
        """检查内容是否安全"""
        text_lower = text.lower()
        for keyword in self.SENSITIVE_KEYWORDS:
            if keyword in text_lower:
                return False
        return True

    def filter(self, text: str) -> tuple[bool, str]:
        """
        过滤内容

        Returns:
            (is_safe, filtered_text) 元组
        """
        if not self.is_safe(text):
            return False, self._get_safe_response()

        # 长度限制 (适合语音播放)
        if len(text) > 500:
            text = text[:500] + "..."

        return True, text

    def _get_safe_response(self) -> str:
        """返回安全的默认回复"""
        import random
        responses = [
            "这个问题有点难，我们换一个话题吧",
            "我不太确定这个答案，要不我们聊点别的",
            "嗯...让我想想，我们先听个故事吧",
            "我们聊点别的话题吧！"
        ]
        return random.choice(responses)


class LLMService:
    """
    LLM 对话服务

    调用外部 ai-manager AI API (支持多模型)
    特点:
    - 多模型支持: Gemini、GPT-4、DeepSeek、Claude 等
    - 智能缓存: 相同 prompt 直接返回缓存结果
    - 自动容错: 模型失败时自动切换到备选模型
    """

    def __init__(self, config: LLMConfig):
        """
        初始化 LLM 服务

        Args:
            config: LLM 配置
        """
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self.content_filter = ContentFilter()

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端 (懒加载，线程安全)"""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        base_url=self.config.base_url,
                        timeout=httpx.Timeout(
                            connect=5.0,
                            read=self.config.timeout,
                            write=10.0,
                            pool=5.0,
                        ),
                    )
        return self._client

    def _sign(self, method: str, path: str) -> tuple[str, str]:
        """生成请求签名"""
        return generate_hmac_signature(
            self.config.api_key, self.config.secret_key, method, path,
        )

    async def initialize(self):
        """初始化 LLM 客户端 (兼容旧接口)"""
        await self._get_client()
        logger.info(f"LLM 服务初始化完成: {self.config.model_preference}")

    async def chat(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None,
        system_message: Optional[str] = None,
    ) -> str:
        """
        对话 (简化接口，返回文本)

        Args:
            message: 用户消息
            history: 对话历史
            system_message: 系统提示覆盖 (可选，不传则使用配置默认值)

        Returns:
            AI 回复文本 (已过滤)
        """
        result = await self.chat_with_details(message, history, system_message=system_message)
        return result.response

    async def chat_with_details(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None,
        temperature: Optional[float] = None,
        system_message: Optional[str] = None,
        use_cache: bool = True,
    ) -> LLMResult:
        """
        对话 (完整接口，返回详细结果)

        Args:
            message: 用户消息
            history: 历史对话 (可选，用于上下文)
            temperature: 温度覆盖 (可选，不传则使用配置值)

        Returns:
            LLMResult 包含 response, model_used, cached 等信息
        """
        # 检查输入安全性
        if not self.content_filter.is_safe(message):
            logger.warning(f"检测到不安全内容: {message[:50]}...")
            return LLMResult(
                response="我们聊点别的话题吧！",
                model_used="content_filter",
                provider="local",
                cached=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time_ms=0
            )

        # 构建 prompt (包含历史上下文)
        prompt = message
        if history:
            # 取最近 5 轮对话作为上下文
            context_parts = []
            for msg in history[-10:]:
                prefix = "用户: " if msg.role == "user" else "助手: "
                context_parts.append(f"{prefix}{msg.content}")
            context = "\n".join(context_parts)
            prompt = f"对话历史:\n{context}\n\n当前用户问题: {message}"

        # 构建请求
        path = "/api/v1/ai-services/prompt"
        timestamp, signature = self._sign("POST", path)

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature
        }

        data = {
            "prompt": prompt,
            "system_message": system_message if system_message is not None else self.config.system_prompt,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "use_cache": use_cache,
        }

        # 指定首选模型 (可选)
        if self.config.model_preference:
            data["model_preference"] = self.config.model_preference

        # 发送请求
        client = await self._get_client()

        try:
            response = await client.post(path, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()

            if not result.get("success"):
                raise Exception(result.get("error", "Unknown error"))

            resp_data = result["data"]
            reply = resp_data["response"]

            # 内容安全过滤
            is_safe, filtered_reply = self.content_filter.filter(reply)

            logger.info(
                f"LLM response: model={resp_data.get('model_used')}, "
                f"cached={resp_data.get('cached', False)}, "
                f"tokens={resp_data.get('usage', {}).get('total_tokens', 0)}"
            )

            usage = resp_data.get("usage", {})
            return LLMResult(
                response=filtered_reply,
                model_used=resp_data.get("model_used", "unknown"),
                provider=resp_data.get("provider_name", "unknown"),
                cached=resp_data.get("cached", False),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                response_time_ms=int(resp_data.get("response_time_ms", 0))
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error: {e.response.status_code} - {e.response.text}")
            return LLMResult(
                response="抱歉，我现在有点忙，稍后再试试吧",
                model_used="error",
                provider="error",
                cached=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time_ms=0
            )

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            return LLMResult(
                response="抱歉，我现在有点累了，稍后再聊好吗？",
                model_used="error",
                provider="error",
                cached=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_time_ms=0
            )

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式对话 (兼容旧接口)

        注意: ai-manager 目前不支持流式，此方法会一次性返回结果

        Args:
            message: 用户消息
            history: 对话历史

        Yields:
            助手回复片段
        """
        # ai-manager 不支持流式，直接返回完整结果
        result = await self.chat(message, history)
        yield result

    async def complete(self, prompt: str) -> str:
        """
        文本补全

        Args:
            prompt: 提示文本

        Returns:
            补全结果
        """
        result = await self.chat_with_details(prompt, temperature=0.3)
        return result.response

    async def close(self):
        """关闭 HTTP 客户端"""
        async with self._lock:
            if self._client:
                await self._client.aclose()
                self._client = None


class ChildChatService:
    """
    儿童对话服务

    基于 LLM 的儿童友好对话，包含:
    - 简化语言
    - 安全过滤
    - 教育引导
    """

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    async def answer_question(self, question: str) -> str:
        """
        回答儿童问题

        Args:
            question: 问题

        Returns:
            简洁、儿童友好的回答
        """
        prompt = f"""作为一个儿童AI助手，请用简单易懂的语言回答这个问题。
回答要求：
1. 不超过 80 个字
2. 使用儿童能理解的词汇
3. 可以用比喻或故事来解释

问题：{question}"""

        return await self.llm.chat(prompt, [])

    async def tell_joke(self) -> str:
        """讲一个儿童笑话"""
        prompt = "请讲一个适合5-10岁儿童的、健康有趣的小笑话，不超过 60 个字。"
        return await self.llm.chat(prompt, [])

    async def encourage(self) -> str:
        """给予鼓励"""
        prompt = "请用温暖的语言鼓励一个小朋友，不超过 50 个字。可以表扬他/她的好奇心或学习精神。"
        return await self.llm.chat(prompt, [])
