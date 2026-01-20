-- VoiceGrow 数据库初始化脚本

-- 创建数据库 (如果不存在)
CREATE DATABASE IF NOT EXISTS voicegrow
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE voicegrow;

-- 内容表
CREATE TABLE IF NOT EXISTS contents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type ENUM('story', 'music', 'english', 'sound') NOT NULL,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    minio_path VARCHAR(500) NOT NULL,
    cover_path VARCHAR(500),
    duration INT,
    file_size INT,
    format VARCHAR(20) DEFAULT 'mp3',
    tags TEXT,
    age_min INT DEFAULT 0,
    age_max INT DEFAULT 12,
    play_count INT DEFAULT 0,
    like_count INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_content_type_category (type, category),
    INDEX idx_content_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 英语单词表
CREATE TABLE IF NOT EXISTS english_words (
    id INT AUTO_INCREMENT PRIMARY KEY,
    word VARCHAR(100) NOT NULL UNIQUE,
    phonetic VARCHAR(100),
    translation VARCHAR(500) NOT NULL,
    audio_us_path VARCHAR(500),
    audio_uk_path VARCHAR(500),
    level VARCHAR(20) DEFAULT 'basic',
    category VARCHAR(50),
    example_sentence TEXT,
    example_translation TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_word_level (level),
    INDEX idx_word_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 播放历史表
CREATE TABLE IF NOT EXISTS play_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(100) NOT NULL,
    content_id INT NOT NULL,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    duration_played INT,
    completed BOOLEAN DEFAULT FALSE,
    INDEX idx_history_device_time (device_id, played_at),
    FOREIGN KEY (content_id) REFERENCES contents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 设备会话表
CREATE TABLE IF NOT EXISTS device_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(100) NOT NULL UNIQUE,
    device_model VARCHAR(50),
    device_sn VARCHAR(100),
    is_connected BOOLEAN DEFAULT FALSE,
    last_connected_at TIMESTAMP,
    last_disconnected_at TIMESTAMP,
    current_content_id INT,
    playing_state VARCHAR(20) DEFAULT 'idle',
    session_data JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (current_content_id) REFERENCES contents(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入示例数据

-- 故事
INSERT INTO contents (type, category, title, description, minio_path, duration, tags) VALUES
('story', 'fairy_tale', '小红帽', '经典童话故事，讲述小红帽和大灰狼的故事', 'stories/fairy_tale/little_red_riding_hood.mp3', 300, '童话,经典,小红帽'),
('story', 'fairy_tale', '三只小猪', '三只小猪建房子的故事', 'stories/fairy_tale/three_little_pigs.mp3', 240, '童话,经典,小猪'),
('story', 'bedtime', '晚安小熊', '温馨的睡前故事', 'stories/bedtime/goodnight_bear.mp3', 180, '睡前,温馨,小熊'),
('story', 'science', '为什么天是蓝色的', '科普故事，解释天空为什么是蓝色', 'stories/science/why_sky_is_blue.mp3', 200, '科普,天空,颜色');

-- 音乐
INSERT INTO contents (type, category, title, description, minio_path, duration, tags) VALUES
('music', 'nursery_rhyme', '小星星', '经典儿歌 Twinkle Twinkle Little Star', 'music/nursery_rhyme/twinkle_star.mp3', 120, '儿歌,经典,星星'),
('music', 'nursery_rhyme', '两只老虎', '经典中文儿歌', 'music/nursery_rhyme/two_tigers.mp3', 90, '儿歌,经典,老虎'),
('music', 'lullaby', '摇篮曲', '舒缓的摇篮曲', 'music/lullaby/lullaby_01.mp3', 180, '摇篮曲,睡前,舒缓'),
('music', 'classical', '小夜曲', '莫扎特小夜曲', 'music/classical/serenade.mp3', 240, '古典,莫扎特,小夜曲');

-- 英语单词
INSERT INTO english_words (word, phonetic, translation, level, category, example_sentence, example_translation) VALUES
('apple', '/ˈæpl/', '苹果', 'basic', 'food', 'I like to eat apples.', '我喜欢吃苹果。'),
('dog', '/dɒɡ/', '狗', 'basic', 'animal', 'The dog is running.', '狗在跑。'),
('cat', '/kæt/', '猫', 'basic', 'animal', 'The cat is sleeping.', '猫在睡觉。'),
('red', '/red/', '红色', 'basic', 'color', 'The apple is red.', '苹果是红色的。'),
('blue', '/bluː/', '蓝色', 'basic', 'color', 'The sky is blue.', '天空是蓝色的。'),
('hello', '/həˈləʊ/', '你好', 'basic', 'greeting', 'Hello, how are you?', '你好，你好吗？'),
('thank you', '/θæŋk juː/', '谢谢', 'basic', 'greeting', 'Thank you very much.', '非常感谢。'),
('water', '/ˈwɔːtər/', '水', 'basic', 'food', 'I want some water.', '我想要一些水。');
