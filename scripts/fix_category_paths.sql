-- 修复 categories.path 字段
-- 问题：同层子分类 path 相同，导致 LIKE 查询误匹配兄弟分类
-- 执行方式：mysql -h HOST -P PORT -u USER -pPASS DATABASE < fix_category_paths.sql

-- 第1步：根分类 (parent_id IS NULL) → path = id
UPDATE categories
SET path = CAST(id AS CHAR)
WHERE parent_id IS NULL;

-- 第2步：level 2 子分类 → path = 父path/自身id
UPDATE categories c
JOIN categories p ON c.parent_id = p.id
SET c.path = CONCAT(p.path, '/', c.id)
WHERE c.level = 2;

-- 第3步：level 3 子分类
UPDATE categories c
JOIN categories p ON c.parent_id = p.id
SET c.path = CONCAT(p.path, '/', c.id)
WHERE c.level = 3;

-- 第4步：level 4 子分类（如无可忽略）
UPDATE categories c
JOIN categories p ON c.parent_id = p.id
SET c.path = CONCAT(p.path, '/', c.id)
WHERE c.level = 4;

-- 验证结果
SELECT id, name, parent_id, level, path FROM categories ORDER BY level, id;
