# L5-1 What Makes a Good Friend? 官方样本对标分析

> 反推来源：`\\SUPERCURFILE\Curriculum\Dino线下绘本馆\00. 各级别Books\Level 5\Book 1\01. Cur\`
> 反推时间：2026-06-01
> 提取产物：`assets/reference_l5_book1/` 下 8 张官方绘本图 + worksheet 7 张图

---

## 一、Anna 官方形象（重大修正！）

我之前在 `character_registry.py` 给 Anna 设的形象**完全是错的**（"双低马尾+琥珀色眼镜+黄色开衫+灰裙"是凭空脑补）。

基于官方 Book PPT 8 张图反推的真实形象：

| 项 | 官方设定 | 我之前错的 |
|---|---|---|
| 发型 | **黑色齐肩短发**，前额齐刘海 | 黑色双低马尾 |
| 头饰 | **白色塑料发箍**（每页都有，是 Anna 的辨识符号） | 无 |
| 眼镜 | **不戴眼镜** | 戴琥珀色细框 |
| 上衣 | **柔和草绿色长袖圆领卫衣**（每页颜色稳定） | 芥末黄长袖针织开衫 |
| 内搭 | 无（套头） | 白衬衫 |
| 下装 | **卡其色长裤**（不是裙子）| 灰色及膝裙 |
| 鞋 | 白色低帮运动鞋 | 黑色玛丽珍鞋 |
| 表情/特征 | 大眼睛 / 鼻子非常小 / 腮粉 / 圆脸 / 温和微笑 | — |
| 年龄外观 | 看起来约 8-10 岁（不是 12 岁） | 12 岁 |

**Mia 和 Tommy 在官方图里也确认了**：
- Mia: 棕色长发 + 单束高马尾 + 薄紫色长袖 polo + 白色长裤 + 白运动鞋 ✓（跟我之前的描述一致）
- Tommy: 棕色短发 + **蓝色短袖 polo**（不是长袖卫衣）+ 蓝色牛仔裤 + 白运动鞋

---

## 二、画风 / 构图标准（重大差距！）

| 维度 | 官方 | 我们当前生成 |
|---|---|---|
| 人物占画面比例 | **30-40%**（中景为主） | 50-65%（半身/大头照） |
| 环境细节 | **极丰富**：教室瓷砖反光、窗户云朵、布告栏装饰、远景 4-5 个玩耍小人、地板纹理、走廊远景门廊 | 背景虚化或几乎一片 |
| 留白 | **大量**（背景墙、地板大面积留白） | 几乎没有 |
| 视角 | 平视 / 俯视，能看到全身或半身 + 环境 | 几乎全是 close-up 头部 |
| 配角动作 | 具体动作（蹲下、俯身、伸手、转头、低头看） | 站着或大头照，无动作 |
| 笔触 | 真水彩感（淡彩 + 留白晕染） | 偏写实磨皮，有塑料感 |
| 高级技巧 | Page 7 **分屏构图**（左公园安慰 + 右教室帮忙）/ Page 8 **思维气泡**（Anna 在房间想象烤饼干场景） | 单一场景 |

**核心改造方向**：
1. 默认 SHOT 从 `medium` 改成 `medium-long`（人物占 30-40%）
2. prompt 强制要求一段「环境必须包含...」描述
3. 强制要求配角的具体动作动词
4. Page 7 / Page 8 类双场景或回忆类页面，允许 prompt 提示"split-screen" 或 "thought bubble"

---

## 三、Worksheet 出题质量标准

### 字号偏好（用户偏好，与官方实测不同 — 按用户）
- 大标题（Vocabulary/Sentence/Reading/Writing）= **40pt** Poppins Bold
- 副标题（Match the words to their definitions.）= **22pt** Poppins Regular
- 题目正文 / 词卡 / 定义 = 16pt
- Reading 长文 = 12-13pt
- 填空 `________` = Arial（避免 Poppins 下划线压扁）

### Vocabulary Match — 真定义示例（学这个标准！）

| word | 官方 def | 我们之前 |
|---|---|---|
| wooden | made of wood | meaning of wooden |
| shake | move quickly from side to side or up and down | meaning of shake |
| recess | a short break at school for students to play outside | meaning of recess |
| a pile of | many things lying one on top of another | meaning of a pile of |
| nervous | feeling worried and not calm | meaning of nervous |

→ 改 ai_extractor prompt 的 match_definition 部分，**严格要求 kid-friendly 真词典定义**。

### Fill Blank — 5 题示例（学这个出题风格）

| # | 句子（用 ____ 留空，长短匹配答案）| 答案 |
|---|---|---|
| 1 | `I feel ________ when I go to a new place.` | nervous |
| 2 | `My hands ________ when I feel scared.` | shake |
| 3 | `We play outside at ________ after class.` | recess |
| 4 | `There is ________________ books on the desk.` | a pile of（**横线明显更长**适配多词） |
| 5 | `The old ________ table is in our classroom.` | wooden |

**规律**：每题对应一个 vocab，句子是日常情境而非照抄故事原文。横线长度匹配答案长度。

### Sentence MC — 4 题二选一 + 配图
官方 sentence 页只有 4 道，每题 2 个选项（一对一错），配 page 2-5 的绘本图。我们已经这样做了。

### Reading MC — 8 题（你说可以调整，所以默认 4 也行）
官方是 8 题密铺一页：

```
1. How did Anna feel on her first day?  A. Happy  B. Nervous  C. Bored
2. What ran under the chair?  A. A hamster  B. A dog  C. A cat
3. What did Anna help the girl do at recess?  A. Clean the desk  B. Pick up books  C. Share pencils
4. What did Anna share with the quiet boy?  A. Pencils and glue  B. Books and erasers  C. Cookies and toys
5. Why did the classmates like Anna?  A. She told funny stories  B. She cared about and helped others  C. She had a lovely hamster
6. What did the hamster take?  A. A pencil  B. A glue stick  C. An eraser
7. What was Anna's plan?  A. She would bring cookies  B. She would get a new hamster  C. She would tell stories
8. Which is TRUE according to the passage?  A. Anna sat at a big metal desk  B. Anna asked polite questions  C. The quiet boy laughed loudly
```

→ 加一个 UI 控件：Reading 题数 `4 / 6 / 8` 单选，默认 4。

### Writing — 提示语
官方：`Write about Anna's first day.`（短、具体、指向故事）
我们：要让 AI 根据故事主题生成类似的 prompt（不是 "Write about your friend"）。

---

## 四、Reading Report 标准

### 字段值标准（中文 + 短码）
- 类型：`Fiction` / `Non-Fiction`（英文）
- 阅读字数：167（纯数字）
- 词汇难度：`A2`（**短码**，不是 "CEFR B1" 全称！）
- 语法难度：`一般过去时态`（**中文**）
- 构词法（L5+）：`suffix -ous (= having/full of quality)` 简洁明确

### 阅读表达 5 题（L5）
- 1 道 ⭐
- 3 道 ⭐⭐
- 1 道 ⭐⭐⭐（最后，PBL/open-ended）
- **L5+ 不需要标 P#**（已对）

### 课堂参与度
- 单元格内容：`😆Excellent   😄 Great   🙂 Good`（emoji + 3 个等级）

### 关键改动
- 词汇难度从 `CEFR B1 / Lexile ...` 改成短码 `A2`
- Phonics → Morphology 自动切换（L5+）

---

## 五、必须改的事（优先级）

| # | 改 | 文件 | ROI |
|---|---|---|---|
| 1 | Anna 形象完全重写 | `scripts/character_registry.py` + `cn_prompt_builder.py` 的 `_en_to_cn_desc` 和 `_key_lock_phrase` | ★★★ |
| 2 | 把官方 image2 复制为 Anna 参考图 | `assets/characters/anna_age10_official.png` | ★★★ |
| 3 | prompt v2：人物占比降到 30-40% + 强制环境描述段 + 配角动作 | `cn_prompt_builder.py` | ★★★ |
| 4 | AI prompt 强化 vocab match 真定义 | `ai_extractor.py` system prompt | ★★ |
| 5 | Reading 题数 UI 选项 4/6/8 | `web_app.py` | ★★ |
| 6 | Worksheet 预览后加"AI 反馈式重生" | `web_app.py` + `ai_extractor.refine_worksheet()` | ★★ |
| 7 | RR 词汇难度改短码 A2/B1 | `reading_report_builder.py` | ★ |
| 8 | RR 构词法默认表达式（基于 vocab 自动推） | `reading_report_builder.py` | ★ |
