"""
修复 categories 表中错误的 path 字段。

问题：create_category 在 commit 前计算 path，缺少分类自身 id，
      导致同层子分类 path 完全相同，path LIKE 查询时会误匹配兄弟分类。

修复规则：
  根分类 (parent_id IS NULL): path = str(id)
  子分类:                      path = parent.path + "/" + str(id)

用法（在服务器上执行）：
  cd /app
  python scripts/fix_category_paths.py
"""

import asyncio
import os
import sys

# 确保能 import app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from server.app.config import get_settings
from server.app.models.database import Category


async def fix_paths():
    settings = get_settings()
    engine = create_async_engine(settings.database.url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # 按层级从低到高处理，确保父分类 path 先更新
        result = await session.execute(
            select(Category).order_by(Category.level, Category.id)
        )
        all_categories = result.scalars().all()

        # 建立 id → category 映射，方便查父级
        cat_map = {c.id: c for c in all_categories}

        fixed = 0
        for cat in all_categories:
            if cat.parent_id is None:
                # 根分类
                correct_path = str(cat.id)
            else:
                parent = cat_map.get(cat.parent_id)
                if parent is None:
                    print(f"  警告: 分类 {cat.id}({cat.name}) 的 parent_id={cat.parent_id} 不存在，跳过")
                    continue
                correct_path = f"{parent.path}/{cat.id}"

            if cat.path != correct_path:
                print(f"  修复: [{cat.id}] {cat.name}  '{cat.path}' → '{correct_path}'")
                cat.path = correct_path
                fixed += 1

        if fixed == 0:
            print("所有分类 path 均正确，无需修复。")
        else:
            await session.commit()
            print(f"\n共修复 {fixed} 条分类记录。")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix_paths())
