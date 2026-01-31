-- VoiceGrow 数据库初始化脚本
-- 与 server/app/models/database.py ORM 模型完全对齐

-- 创建数据库 (如果不存在)
CREATE DATABASE IF NOT EXISTS voicegrow
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE voicegrow;

-- ============================================
-- 1. categories - 层级分类 (self-ref FK)
-- ============================================
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parent_id INT DEFAULT NULL,

    -- 分类信息
    name VARCHAR(50) NOT NULL,
    name_pinyin VARCHAR(100) DEFAULT NULL,
    type ENUM('story', 'music', 'english', 'sound') NOT NULL,

    -- 层级信息
    level INT DEFAULT 1,
    path VARCHAR(200) DEFAULT NULL,

    -- 显示信息
    sort_order INT DEFAULT 0,
    icon VARCHAR(50) DEFAULT NULL,
    description TEXT DEFAULT NULL,

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 外键
    FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE SET NULL,

    -- 索引
    INDEX idx_category_parent (parent_id),
    INDEX idx_category_type (type),
    INDEX idx_category_type_level (type, level),
    INDEX idx_category_path (path),
    INDEX idx_category_name_pinyin (name_pinyin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 2. artists - 艺术家/作者/讲述者
-- ============================================
CREATE TABLE IF NOT EXISTS artists (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 艺术家信息
    name VARCHAR(100) NOT NULL,
    name_pinyin VARCHAR(200) DEFAULT NULL,
    aliases VARCHAR(500) DEFAULT NULL,
    type ENUM('singer', 'author', 'narrator', 'composer', 'band') NOT NULL,

    -- 媒体信息
    avatar_path VARCHAR(500) DEFAULT NULL,
    description TEXT DEFAULT NULL,

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 索引
    INDEX idx_artist_name (name),
    INDEX idx_artist_name_pinyin (name_pinyin),
    INDEX idx_artist_type (type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 3. tags - 标签 (age/scene/mood/theme/feature)
-- ============================================
CREATE TABLE IF NOT EXISTS tags (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 标签信息
    name VARCHAR(50) NOT NULL UNIQUE,
    name_pinyin VARCHAR(100) DEFAULT NULL,
    type ENUM('age', 'scene', 'mood', 'theme', 'feature') NOT NULL,

    -- 显示信息
    sort_order INT DEFAULT 0,
    color VARCHAR(20) DEFAULT NULL,

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 索引
    INDEX idx_tag_type (type),
    INDEX idx_tag_name_pinyin (name_pinyin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 4. contents - 内容元数据 (FK → categories)
-- ============================================
CREATE TABLE IF NOT EXISTS contents (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 内容信息
    type ENUM('story', 'music', 'english', 'sound') NOT NULL,
    category_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    title_pinyin VARCHAR(500) DEFAULT NULL,
    subtitle VARCHAR(200) DEFAULT NULL,
    description TEXT DEFAULT NULL,

    -- 存储路径 (MinIO)
    minio_path VARCHAR(500) NOT NULL,
    cover_path VARCHAR(500) DEFAULT NULL,

    -- 音频信息
    duration INT DEFAULT NULL,
    file_size INT DEFAULT NULL,
    format VARCHAR(20) DEFAULT 'mp3',
    bitrate INT DEFAULT NULL,

    -- 适用范围
    age_min INT DEFAULT 0,
    age_max INT DEFAULT 12,

    -- 统计
    play_count INT DEFAULT 0,
    like_count INT DEFAULT 0,

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,
    is_vip BOOLEAN DEFAULT FALSE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    published_at TIMESTAMP DEFAULT NULL,

    -- 外键
    FOREIGN KEY (category_id) REFERENCES categories(id),

    -- 索引
    INDEX idx_content_type (type),
    INDEX idx_content_type_category (type, category_id),
    INDEX idx_content_title (title),
    INDEX idx_content_title_pinyin (title_pinyin),
    INDEX idx_content_play_count (play_count),
    INDEX idx_content_created_at (created_at),
    INDEX idx_content_active_type (is_active, type),
    INDEX idx_content_active_type_playcount (is_active, type, play_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 5. content_artists - 内容-艺术家关联
-- ============================================
CREATE TABLE IF NOT EXISTS content_artists (
    id INT AUTO_INCREMENT PRIMARY KEY,
    content_id INT NOT NULL,
    artist_id INT NOT NULL,
    role ENUM('singer', 'author', 'narrator', 'composer', 'lyricist') NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    sort_order INT DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 外键
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE,
    FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE,

    -- 唯一约束
    UNIQUE KEY uk_content_artist_role (content_id, artist_id, role),

    -- 索引
    INDEX idx_content_artist_content (content_id),
    INDEX idx_content_artist_artist (artist_id),
    INDEX idx_content_artist_artist_role (artist_id, role),
    INDEX idx_content_artist_primary (artist_id, is_primary, content_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 6. content_tags - 内容-标签关联
-- ============================================
CREATE TABLE IF NOT EXISTS content_tags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    content_id INT NOT NULL,
    tag_id INT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 外键
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,

    -- 唯一约束
    UNIQUE KEY uk_content_tag (content_id, tag_id),

    -- 索引
    INDEX idx_content_tag_content (content_id),
    INDEX idx_content_tag_tag (tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 7. english_words - 英语单词 (FK → categories)
-- ============================================
CREATE TABLE IF NOT EXISTS english_words (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 单词信息
    word VARCHAR(100) NOT NULL UNIQUE,
    phonetic_us VARCHAR(100) DEFAULT NULL,
    phonetic_uk VARCHAR(100) DEFAULT NULL,
    translation VARCHAR(500) NOT NULL,

    -- 音频路径
    audio_us_path VARCHAR(500) DEFAULT NULL,
    audio_uk_path VARCHAR(500) DEFAULT NULL,

    -- 分类
    category_id INT DEFAULT NULL,
    level ENUM('basic', 'intermediate', 'advanced') DEFAULT 'basic',

    -- 例句
    example_sentence TEXT DEFAULT NULL,
    example_translation TEXT DEFAULT NULL,
    example_audio_path VARCHAR(500) DEFAULT NULL,

    -- 扩展
    synonyms VARCHAR(500) DEFAULT NULL,
    antonyms VARCHAR(500) DEFAULT NULL,
    word_forms JSON DEFAULT NULL,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 外键
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,

    -- 索引
    INDEX idx_word (word),
    INDEX idx_word_category (category_id),
    INDEX idx_word_level (level),
    INDEX idx_word_category_level (category_id, level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 8. play_history - 播放历史 (id BIGINT)
-- ============================================
CREATE TABLE IF NOT EXISTS play_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- 关联
    device_id VARCHAR(100) NOT NULL,
    content_id INT NOT NULL,
    content_type ENUM('story', 'music', 'english', 'sound') NOT NULL,

    -- 播放信息
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_played INT DEFAULT 0,
    play_position INT DEFAULT 0,
    completed BOOLEAN DEFAULT FALSE,
    play_source VARCHAR(50) DEFAULT NULL,

    -- 外键
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE,

    -- 索引
    INDEX idx_history_device_time (device_id, played_at),
    INDEX idx_history_content (content_id),
    INDEX idx_history_device_content (device_id, content_id),
    INDEX idx_history_played_at (played_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 9. device_sessions - 设备会话
-- ============================================
CREATE TABLE IF NOT EXISTS device_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- 设备信息
    device_id VARCHAR(100) NOT NULL UNIQUE,
    device_model VARCHAR(50) DEFAULT NULL,
    device_sn VARCHAR(100) DEFAULT NULL,
    device_name VARCHAR(100) DEFAULT NULL,

    -- 会话状态
    is_connected BOOLEAN DEFAULT FALSE,
    last_connected_at TIMESTAMP DEFAULT NULL,
    last_disconnected_at TIMESTAMP DEFAULT NULL,

    -- 播放状态
    current_content_id INT DEFAULT NULL,
    playing_state ENUM('idle', 'playing', 'paused', 'loading') DEFAULT 'idle',
    play_position INT DEFAULT 0,
    volume INT DEFAULT 50,

    -- 会话数据 (JSON)
    session_data JSON DEFAULT NULL,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 外键
    FOREIGN KEY (current_content_id) REFERENCES contents(id) ON DELETE SET NULL,

    -- 索引
    INDEX idx_session_device_id (device_id),
    INDEX idx_session_connected (is_connected)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- 种子数据
-- ============================================

-- 分类: 故事
INSERT INTO categories (id, parent_id, name, name_pinyin, type, level, path, sort_order) VALUES
(1, NULL, '故事', 'gushi', 'story', 1, '/1/', 1),
(2, 1, '睡前故事', 'shuiqiangushi', 'story', 2, '/1/2/', 1),
(3, 1, '童话故事', 'tonghuagushi', 'story', 2, '/1/3/', 2),
(4, 1, '寓言故事', 'yuyangushi', 'story', 2, '/1/4/', 3),
(5, 1, '科普故事', 'kepugushi', 'story', 2, '/1/5/', 4);

-- 分类: 音乐
INSERT INTO categories (id, parent_id, name, name_pinyin, type, level, path, sort_order) VALUES
(6, NULL, '音乐', 'yinyue', 'music', 1, '/6/', 2),
(7, 6, '儿歌', 'erge', 'music', 2, '/6/7/', 1),
(8, 6, '摇篮曲', 'yaolanqu', 'music', 2, '/6/8/', 2),
(9, 6, '胎教音乐', 'taijiaoyinyue', 'music', 2, '/6/9/', 3),
(10, 6, '古典音乐', 'gudianyinyue', 'music', 2, '/6/10/', 4);

-- 分类: 英语
INSERT INTO categories (id, parent_id, name, name_pinyin, type, level, path, sort_order) VALUES
(11, NULL, '英语', 'yingyu', 'english', 1, '/11/', 3),
(12, 11, '基础词汇', 'jichucihui', 'english', 2, '/11/12/', 1),
(13, 11, '动物', 'dongwu', 'english', 2, '/11/13/', 2),
(14, 11, '颜色', 'yanse', 'english', 2, '/11/14/', 3),
(15, 11, '数字', 'shuzi', 'english', 2, '/11/15/', 4),
(16, 11, '食物', 'shiwu', 'english', 2, '/11/16/', 5);

-- 艺术家
INSERT INTO artists (id, name, name_pinyin, aliases, type, description) VALUES
(1, '小声姐姐', 'xiaoshengjiejie', '小声|姐姐', 'narrator', '小声姐姐是 VoiceGrow 的故事讲述者'),
(2, '欢乐童声', 'huanletongsheng', '童声合唱团', 'singer', '专注儿童歌曲演唱的合唱团'),
(3, '科普博士', 'kepuboshi', '博士|科普老师', 'narrator', '专注科普故事的讲述者');

-- 标签: 年龄段
INSERT INTO tags (id, name, name_pinyin, type, sort_order) VALUES
(1, '0-3岁', '0-3sui', 'age', 1),
(2, '3-6岁', '3-6sui', 'age', 2),
(3, '6-12岁', '6-12sui', 'age', 3);

-- 标签: 场景
INSERT INTO tags (id, name, name_pinyin, type, sort_order) VALUES
(4, '睡前', 'shuiqian', 'scene', 1),
(5, '早教', 'zaojiao', 'scene', 2),
(6, '车载', 'chezai', 'scene', 3);

-- 标签: 情绪
INSERT INTO tags (id, name, name_pinyin, type, sort_order) VALUES
(7, '欢快', 'huankuai', 'mood', 1),
(8, '舒缓', 'shuhuan', 'mood', 2),
(9, '温馨', 'wenxin', 'mood', 3);

-- 标签: 主题
INSERT INTO tags (id, name, name_pinyin, type, sort_order) VALUES
(10, '经典', 'jingdian', 'theme', 1),
(11, '国学', 'guoxue', 'theme', 2),
(12, '科普', 'kepu', 'theme', 3);

-- 内容: 故事
INSERT INTO contents (id, type, category_id, title, title_pinyin, description, minio_path, duration, age_min, age_max) VALUES
(1, 'story', 3, '小红帽', 'xiaohongmao', '经典童话故事，讲述小红帽和大灰狼的故事', 'stories/fairy_tale/little_red_riding_hood.mp3', 300, 3, 8),
(2, 'story', 3, '三只小猪', 'sanzhixiaozhu', '三只小猪建房子的故事', 'stories/fairy_tale/three_little_pigs.mp3', 240, 3, 8),
(3, 'story', 2, '晚安小熊', 'wananxiaoxiong', '温馨的睡前故事', 'stories/bedtime/goodnight_bear.mp3', 180, 0, 6),
(4, 'story', 5, '为什么天是蓝色的', 'weishenmotianshilansede', '科普故事，解释天空为什么是蓝色', 'stories/science/why_sky_is_blue.mp3', 200, 4, 10);

-- 内容: 音乐
INSERT INTO contents (id, type, category_id, title, title_pinyin, description, minio_path, duration, age_min, age_max) VALUES
(5, 'music', 7, '小星星', 'xiaoxingxing', '经典儿歌 Twinkle Twinkle Little Star', 'music/nursery_rhyme/twinkle_star.mp3', 120, 0, 6),
(6, 'music', 7, '两只老虎', 'liangzhilaohu', '经典中文儿歌', 'music/nursery_rhyme/two_tigers.mp3', 90, 0, 6),
(7, 'music', 8, '摇篮曲', 'yaolanqu', '舒缓的摇篮曲', 'music/lullaby/lullaby_01.mp3', 180, 0, 3),
(8, 'music', 10, '小夜曲', 'xiaoyequ', '莫扎特小夜曲', 'music/classical/serenade.mp3', 240, 3, 12);

-- 内容-艺术家关联
INSERT INTO content_artists (content_id, artist_id, role, is_primary, sort_order) VALUES
(1, 1, 'narrator', TRUE, 1),
(2, 1, 'narrator', TRUE, 1),
(3, 1, 'narrator', TRUE, 1),
(4, 3, 'narrator', TRUE, 1),
(5, 2, 'singer', TRUE, 1),
(6, 2, 'singer', TRUE, 1),
(7, 2, 'singer', TRUE, 1),
(8, 2, 'singer', TRUE, 1);

-- 内容-标签关联
INSERT INTO content_tags (content_id, tag_id) VALUES
(1, 2),   -- 小红帽 → 3-6岁
(1, 10),  -- 小红帽 → 经典
(2, 2),   -- 三只小猪 → 3-6岁
(2, 10),  -- 三只小猪 → 经典
(3, 1),   -- 晚安小熊 → 0-3岁
(3, 4),   -- 晚安小熊 → 睡前
(3, 9),   -- 晚安小熊 → 温馨
(4, 2),   -- 为什么天是蓝色的 → 3-6岁
(4, 12),  -- 为什么天是蓝色的 → 科普
(5, 1),   -- 小星星 → 0-3岁
(5, 7),   -- 小星星 → 欢快
(5, 10),  -- 小星星 → 经典
(6, 1),   -- 两只老虎 → 0-3岁
(6, 7),   -- 两只老虎 → 欢快
(7, 1),   -- 摇篮曲 → 0-3岁
(7, 4),   -- 摇篮曲 → 睡前
(7, 8),   -- 摇篮曲 → 舒缓
(8, 3),   -- 小夜曲 → 6-12岁
(8, 8);   -- 小夜曲 → 舒缓

-- 英语单词 (引用 category_id FK)
INSERT INTO english_words (word, phonetic_us, phonetic_uk, translation, category_id, level, example_sentence, example_translation) VALUES
('apple', '/ˈæpl/', '/ˈæpl/', '苹果', 16, 'basic', 'I like to eat apples.', '我喜欢吃苹果。'),
('dog', '/dɔːɡ/', '/dɒɡ/', '狗', 13, 'basic', 'The dog is running.', '狗在跑。'),
('cat', '/kæt/', '/kæt/', '猫', 13, 'basic', 'The cat is sleeping.', '猫在睡觉。'),
('red', '/red/', '/red/', '红色', 14, 'basic', 'The apple is red.', '苹果是红色的。'),
('blue', '/bluː/', '/bluː/', '蓝色', 14, 'basic', 'The sky is blue.', '天空是蓝色的。'),
('hello', '/həˈloʊ/', '/həˈləʊ/', '你好', 12, 'basic', 'Hello, how are you?', '你好，你好吗？'),
('water', '/ˈwɔːtər/', '/ˈwɔːtə/', '水', 16, 'basic', 'I want some water.', '我想要一些水。'),
('one', '/wʌn/', '/wʌn/', '一', 15, 'basic', 'I have one apple.', '我有一个苹果。');
