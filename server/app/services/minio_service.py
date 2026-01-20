"""
MinIO 对象存储服务

管理音频文件的存储和访问
"""

import asyncio
import io
import logging
from typing import Optional, BinaryIO
from datetime import timedelta

from ..config import MinIOConfig

logger = logging.getLogger(__name__)


class MinIOService:
    """
    MinIO 对象存储服务

    用于存储和访问音频文件 (故事、音乐、TTS 输出等)
    """

    def __init__(self, config: MinIOConfig):
        """
        初始化 MinIO 服务

        Args:
            config: MinIO 配置
        """
        self.config = config
        self._client = None

    def _get_client(self):
        """获取 MinIO 客户端 (懒加载)"""
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                self.config.endpoint,
                access_key=self.config.access_key,
                secret_key=self.config.secret_key,
                secure=self.config.secure
            )

            # 确保 bucket 存在
            if not self._client.bucket_exists(self.config.bucket):
                self._client.make_bucket(self.config.bucket)
                logger.info(f"创建 MinIO bucket: {self.config.bucket}")

        return self._client

    async def upload_file(
        self,
        file_path: str,
        object_name: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        上传文件到 MinIO

        Args:
            file_path: 本地文件路径
            object_name: 对象名称 (在 bucket 中的路径)
            content_type: 内容类型

        Returns:
            对象名称
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._upload_file_sync,
            file_path,
            object_name,
            content_type
        )
        logger.info(f"上传文件到 MinIO: {object_name}")
        return object_name

    def _upload_file_sync(
        self,
        file_path: str,
        object_name: str,
        content_type: str
    ):
        """同步上传文件"""
        client = self._get_client()
        client.fput_object(
            self.config.bucket,
            object_name,
            file_path,
            content_type=content_type
        )

    async def upload_bytes(
        self,
        data: bytes,
        object_name: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """
        上传字节数据到 MinIO

        Args:
            data: 字节数据
            object_name: 对象名称
            content_type: 内容类型

        Returns:
            对象名称
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._upload_bytes_sync,
            data,
            object_name,
            content_type
        )
        logger.debug(f"上传数据到 MinIO: {object_name}, size={len(data)}")
        return object_name

    def _upload_bytes_sync(
        self,
        data: bytes,
        object_name: str,
        content_type: str
    ):
        """同步上传字节数据"""
        client = self._get_client()
        data_stream = io.BytesIO(data)
        client.put_object(
            self.config.bucket,
            object_name,
            data_stream,
            length=len(data),
            content_type=content_type
        )

    async def download_file(
        self,
        object_name: str,
        file_path: str
    ):
        """
        从 MinIO 下载文件

        Args:
            object_name: 对象名称
            file_path: 本地保存路径
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._download_file_sync,
            object_name,
            file_path
        )
        logger.debug(f"从 MinIO 下载文件: {object_name} -> {file_path}")

    def _download_file_sync(self, object_name: str, file_path: str):
        """同步下载文件"""
        client = self._get_client()
        client.fget_object(self.config.bucket, object_name, file_path)

    async def download_bytes(self, object_name: str) -> bytes:
        """
        从 MinIO 下载数据

        Args:
            object_name: 对象名称

        Returns:
            字节数据
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._download_bytes_sync,
            object_name
        )

    def _download_bytes_sync(self, object_name: str) -> bytes:
        """同步下载数据"""
        client = self._get_client()
        response = client.get_object(self.config.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def get_presigned_url(
        self,
        object_name: str,
        expires: Optional[int] = None
    ) -> str:
        """
        获取预签名 URL

        Args:
            object_name: 对象名称
            expires: 过期时间 (秒)，默认使用配置值

        Returns:
            预签名 URL
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._get_presigned_url_sync,
            object_name,
            expires
        )

    def _get_presigned_url_sync(
        self,
        object_name: str,
        expires: Optional[int] = None
    ) -> str:
        """同步获取预签名 URL"""
        client = self._get_client()
        expiry = timedelta(seconds=expires or self.config.presign_expiry)
        return client.presigned_get_object(
            self.config.bucket,
            object_name,
            expires=expiry
        )

    async def presigned_put_url(
        self,
        object_name: str,
        expires: Optional[int] = None
    ) -> str:
        """
        获取预签名上传 URL

        Args:
            object_name: 对象名称
            expires: 过期时间 (秒)，默认使用配置值

        Returns:
            预签名上传 URL
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._presigned_put_url_sync,
            object_name,
            expires
        )

    def _presigned_put_url_sync(
        self,
        object_name: str,
        expires: Optional[int] = None
    ) -> str:
        """同步获取预签名上传 URL"""
        client = self._get_client()
        expiry = timedelta(seconds=expires or 3600)  # 默认 1 小时
        return client.presigned_put_object(
            self.config.bucket,
            object_name,
            expires=expiry
        )

    async def exists(self, object_name: str) -> bool:
        """
        检查对象是否存在

        Args:
            object_name: 对象名称

        Returns:
            是否存在
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._exists_sync,
            object_name
        )

    def _exists_sync(self, object_name: str) -> bool:
        """同步检查对象是否存在"""
        try:
            client = self._get_client()
            client.stat_object(self.config.bucket, object_name)
            return True
        except Exception:
            return False

    async def delete(self, object_name: str):
        """
        删除对象

        Args:
            object_name: 对象名称
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._delete_sync,
            object_name
        )
        logger.info(f"从 MinIO 删除: {object_name}")

    def _delete_sync(self, object_name: str):
        """同步删除对象"""
        client = self._get_client()
        client.remove_object(self.config.bucket, object_name)

    async def list_objects(
        self,
        prefix: str = "",
        recursive: bool = True
    ) -> list:
        """
        列出对象

        Args:
            prefix: 前缀过滤
            recursive: 是否递归

        Returns:
            对象列表
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._list_objects_sync,
            prefix,
            recursive
        )

    def _list_objects_sync(self, prefix: str, recursive: bool) -> list:
        """同步列出对象"""
        client = self._get_client()
        objects = client.list_objects(
            self.config.bucket,
            prefix=prefix,
            recursive=recursive
        )
        return [
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified,
            }
            for obj in objects
        ]
