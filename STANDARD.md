# 绘本制作标准 v1.8.2（4 件套全量总表）

> **v1.8.2 升级（2026-06-01 晚上 — 角色识别透明化 + 必填精简 + 蓝思自动）**：
>
> ### 必填字段精简到 3 项
>
> 网页端只有 3 项必填：① Book Title  ② Level  ③ 故事原文。
> 其余字段（CEFR / 蓝思 Lexile / 字数 / 故事类型 / 主题 / Phonics / 语法 / 词表）**全部 AI 自动**，用户可在「⚙️ 选填字段」里覆盖任意一项。
>
> ### 蓝思 Lexile 按 Level 自动映射
>
> | Level | Lexile |
> |---|---|
> | Smart | BR (Beginning Reader) |
> | L0 | BR-100L |
> | L1 | 100L-200L |
> | L2 | 200L-300L |
> | L3 | 300L-450L |
> | L4 | 450L-600L |
> | L5 | 600L-750L |
> | L6 | 750L-900L |
>
> Reading Report 词汇难度行同时显示：`CEFR B1 / Lexile 600L-750L`
>
> ### 故事类型 (Fiction / Non-Fiction) 自动推断
>
> AI 按文本启发式判断：
> - 含已注册 IP 人名 → Fiction
> - 含 said/asked/felt/... 叙事词 ≥ 2 → Fiction
> - 含 are/have/many/around the world 等知识词 ≥ 3 且无叙事词 → Non-Fiction
> - 默认 Fiction（绘本绝大多数）
>
> 用户可在「⚙️ 选填字段」里手动覆盖。
>
> ### 🎭 主角识别透明化（v1.8.2 重点）
>
> AI 抽取后立即显示「主角识别面板」，让老师在生图前能审核：
> 1. **官方 IP 匹配列表**：故事里出现的 Mia / Tommy / Anna / Teacher Kim / Mom / Dad / Grandma / Grandpa 等，每个显示参考图 + 类别 + 性别 + 年龄
> 2. **未命名角色 → 默认 IP 建议**：
>    - 故事里的 "girl" → 默认套 Mia 形象
>    - 故事里的 "boy" → 默认套 Tommy 形象
>    - 故事里的 "woman" → 默认套 Teacher Kim 形象
>    - 故事里的 "cat" → 默认套 Winnie 形象
> 3. **新人物注册入口**：如果识别错了，去「⚙️ 选填字段」→ 「🆕 新人物注册」加一行 `name | description` 即可
>
> ### 主题 (Theme) 自动推断
>
> AI 按 10 大主题词典扫描故事 + 标题，挑命中数最高的 1-2 个主题（如 "school, growing up"）。

> **v1.8 升级（2026-06-01 晚上 — Reader Type / Phonics / 美式 / 答案格式回炉）**：
>
> ### Reading Report — Reader Type 强制按 Level 映射
>
> | Level | 类型（第一行 "类型："） |
> |---|---|
> | Smart / L0 | `Concept & Knowledge - Building Readers` |
> | L1 | `Patterned Narrative & Informational Readers` |
> | L2 | `Early Independent Genre-Exposure Readers` |
> | L3 - L6 | `Fiction` 或 `Non-Fiction`（取 `outline.fiction_type` / `reader_type`，没填默认 Fiction）|
>
> ### Reading Report — 词汇难度按 Level 自动映射
>
> | Level | 词汇难度 |
> |---|---|
> | Smart / L0 / L1 | CEFR Pre-A1 |
> | L2 | CEFR A1 |
> | L3 | CEFR A1+ |
> | L4 | CEFR A2 |
> | L5 | CEFR B1 |
> | L6 | CEFR B1+ |
>
> ### Reading Report — Phonics 格式（不是句子，是词组）
>
> - 全小写（CEFR / PBL 等术语保留大写）
> - 英文直双引号 `"..."`（自动把 curly quote 转回 straight）
> - 例词放括号 `(friendship)`
> - **不带句号**
> - 标准示例：
>     - `consonant blend "fr" (friendship)`
>     - `long "oy" (toy)`
>     - `diphthong "ea+r" (bear)`
>     - `long "o" (snow ow)`
>     - `long "a" (day)`
>
> ### Reading Report — 其他
> - **阅读字数** = **故事正文** word count（不含题目 / 答案 / 标题）
> - **语法难度** = 具体时态名（"Simple present" / "Simple past + adjective" 等），保留用户大纲填写
> - **词汇掌握** = mastery 4 词（不够补空格，全部小写无标点 + 美式）
>
> ### Worksheet — 美式拼写 + 答案格式强制
>
> - **所有英文一律美式拼写**：colour→color, favourite→favorite, centre→center, theatre→theater, realise→realize, grey→gray, neighbour→neighbor 等
> - **单词类答案**：全小写、无句号、无引号 → `red`、`apple`、`a pile of`
> - **句子类答案**：首字母大写、句末加句号 → `Anna helped pick up the books.`
> - **题干** = 问句，自动补 `?`
> - **顶部题易、底部题难**（启发式按题长升序排）
>
> ### Worksheet — 移除无效活动类型
>
> 以下题型一律剔除（color 只是手段，没有明确语言输出）：
> - `color the ...` / `colour the ...`
> - `color in ...`
> - `circle the picture`（仅涂圈）
>
> 所有题必须落到具体输出：**写词 / 写句 / 填空 / 多选**
>
> ### Worksheet — Match 页加 visual cue
>
> P1 Vocabulary Match 三列布局：左侧绘本小图（vocab cue）→ 中粉色词卡 → 右白底定义卡

> **v1.7 升级（2026-06-01 晚上）**：用户实物检视后回炉调整：
>
> - **Worksheet 大标题恢复 40pt Poppins Bold #333333**（v1.6 的 20pt 太小，参考真实样本看是因为样本字号实际偏小，但用户偏好更大气）
> - **Worksheet 副标题 / 题目说明 = 22pt Poppins Regular #666666**（区间 20–24pt，统一取 22pt）
> - **下划线占位符 `________` 强制用 Arial 字体**（Poppins 下 underscore 字形被压扁不清晰）
> - **Reading 页 MC 题数从 8 减到 4**（2x2 排版，避免拥挤；题干+选项字号同步放大到 16pt）
> - **Logo 改用 `dino_head_icon.png`**（从 `dino_reading_logo.png` 裁出的纯 Dino 头），不再用设定卡 `dino_logo.png`
> - **Sentence 页图片必须按原长宽比适配**（PIL 读尺寸后等比缩放居中，不再强制 wxh 压扁）

> **v1.6 升级（2026-06-01 下午）**：参照真实 worksheet 样本（`L5-1 Worksheet 5.27.pptx`）回归实测：
>
> - **Worksheet 改回 6 页结构**（v1.5 的"4 页写作内嵌"是误读，真实样本 6 页拆分更清晰）
> - ~~**Worksheet 字号改小**：大标题 20pt / 副标题 12pt 灰~~ → **被 v1.7 推翻**
> - **Worksheet 大标题颜色** = #333333 深炭灰（不是纯黑，更柔和）
> - **Sentence 题图复用绘本插画**（page_02/03/04/05.png），不另出图
> - Mind Map / Writing 采取 **简洁版**（题目骨架 + 写作区），不堆装饰贴纸

> **v1.5 升级（2026-06-01）**：用户重新梳理，新增 / 修订：
> 
> - **统一命名规范**：`Level X_BookXX_品类_标题.后缀`
> - **页面结构定调**：绘本固定 `封面 + 7 页正文 + 封底`，每页一句话
> - **IP 人物扩充**：新增 `TEACHER KIM`（成年女老师，Ms. Frizzle 风格）、`WINNIE`（常驻猫）
> - **Worksheet 减为 4 页**：2 vocab + 1 sentences + 1 reading（写作内嵌在 reading）
> - **Reading Report**：**L4–L6 不标注绘本页码**；阅读难度类型按 Level 自动映射；L5–L6 自然拼读 → **构词法 morphology**
> - **画风口径**：精致墨水轮廓 + 纹理纸背景 + 自然手绘笔触 + 莫兰迪色系
> - 全部英文 = Poppin / Poppins 家族；中文 = 阿里巴巴普惠体 2.0 55 Regular

---

## 一、全项目通用基础规则（所有交付物 100% 强制）

| 规则分类 | 标准要求 |
|---|---|
| 命名规范 | `Level X_BookXX_品类_标题.后缀`，非法字符自动替换为 `_`。<br>示例：`Level 5_Book01_绘本_What Makes a Good Friend.pptx` |
| 模板约束 | 严格套用原版模板，**Logo / 页眉页脚 / 页边距 / 配色 / 底色 / 装饰元素完全不动**；禁止私自改版式、字体、配色、结构 |
| 视觉统一 | 全系列绘本 & 练习册共用一套画风、固定 IP 人物，跨页、跨册、跨交付物 100% 一致 |
| 内容保真 | 所有文本内容优先取自大纲，无大纲内容不得编造；习题答案、教学内容跨交付物 100% 一致 |
| 新人物规则 | 故事中出现大纲外的新人物，必须先确认人物形象设定后再配图，禁止私自生成新人物形象 |

---

## 二、字体 / 画风 / 人物 IP 通用专项

### 1. 英文字体统一规范

| 应用场景 | 字体 | 字重 | 说明 |
|---|---|---|---|
| 绘本 PPT 封面标题 | Poppin | Bold | 适配封面留白，跨册风格一致 |
| 绘本 PPT 内页正文 | Poppins | Regular | 行高 1.2–1.5，不遮挡配图 |
| 绘本 PPT 封底信息 | Poppins | Regular / Bold | Level / CEFR 等关键字加粗 |
| Worksheet 页面大标题 | Poppin | Bold | **固定 40pt，居中，黑色** |
| Worksheet 页面小标题/题目说明 | Poppins | Regular | **20–24pt，居中，灰色**；题目文本左对齐 |
| 阅读报告 / 教师指南 标题 | Poppin | Bold | 主标题突出，层级清晰 |
| 阅读报告 / 教师指南 正文 | Poppins | Regular | 行高 1.5，保证打印可读性 |

> **全项目英文内容只用 Poppin / Poppins 家族；中文一律阿里巴巴普惠体 2.0 55 Regular**

### 2. 绘本画风 & 配色

| 项 | 标准 |
|---|---|
| 核心画风 | 经典儿童图画书插图：**精致的墨水轮廓 + 纹理纸背景 + 自然的手绘笔触** |
| 配色 | **低饱和度、高丰富度的高级莫兰迪色系** |
| 配图质量 | 分辨率 ≥ 1024×1024，无模糊、无变形，主体突出 |
| 留白 | 内页底部 **15%–20% 强制留白**，无主体/重要元素遮挡 |

### 3. 固定 IP 人物 & 年龄映射

| 角色 | 定位 / 性格 | 年龄设定 | 画风要点 |
|---|---|---|---|
| **MIA** | 主角，好奇、乐观 | L0–L3 = 8、L4 = 10、L5–L6 = 12 | 扎马尾、紫色上衣，跨页 100% 一致 |
| **TOMMY** | 主角，爱玩的伙伴 | L0–L3 = 8、L4 = 10、L5–L6 = 12 | 棕色短发、蓝色上衣 |
| **TEACHER KIM** | 成人，温暖创造力老师（Ms. Frizzle 风格） | 成年女性 | 成熟稳重、风格融合 |
| **WINNIE** | 常驻猫，偶尔客串 | 卡通猫咪 | 软萌、与主角画风匹配 |
| **Dino** | VIPKID 官方吉祥物 | 固定 | **严格官方形象，造型/配色/比例不得修改** |

> 同绘本内同一人物的**面部特征、发型、服饰、体型、画风必须 100% 跨页统一**

---

## 三、4 大交付物 详细标准

### 交付物 1 — 绘本 PPT

| 分类 | 明细 |
|---|---|
| 格式 | PPTX |
| 页数 | 总页数 = 4 的倍数；不足自动补空白页 |
| 固定结构 | `封面 + 7 页正文 + 封底`（用户给故事后由系统自动分配到 Page 2–8） |
| 页码 | 正文 Page 2 起，左下/右下交替；**封面、封底无页码** |
| 封面 | 标题靠上，顶部预留 VIPKID Dino 阅读馆 Logo 位 |
| 内页 | 每页 1 句适配故事的短句 + 对应插画 |
| 封底 | **必须包含 6 项**：Level / Book number / CEFR / Lexile / 总词数 / Vocabulary |
| 配图 | 模型 = **即梦 4.6**；遵循"画风 & 配色"；底部 15%–20% 留白；人物 = IP |

### 交付物 2 — Worksheet PPT（**v1.6：6 页固定，对齐真实样本 L5-1**）

#### 2.1 固定页面结构（6 页，PPT 比例 10.83 × 7.50 英寸 / A4 横向）

| 页 | 大标题 | 副标题 | 题型 | 内容要求 |
|---|---|---|---|---|
| 1 | **Vocabulary** | Match the words to their definitions. | 连线题 | 左列粉色实心词卡 ↔ 右列白底粉边定义卡，5 对 |
| 2 | **Vocabulary** | Use the words / phrase to fill each blank. | 填空题 | 顶部粉条词库（5 词水平排列）+ 5 个填空句 |
| 3 | **Sentence** | Choose the correct sentence. | 二选一 | 4 题，每题左侧绘本图（**复用 page_02/03/04/05.png**）+ 右侧 2 选项 ☐ |
| 4 | **Reading** | Choose the correct answer for each question. | 阅读 + 单选 | 顶部红色虚线框装绘本全文 + 下方两列 8 道 3 选项 MC |
| 5 | **Writing** | Write about [theme/protagonist]. | 写作（简洁版）| 中部黄色虚线框装 5 步导图（Title + Beginning/First event/Second event/Funny event/Ending），下方蓝色横线写作区（80 字） |
| 6 | **Reading** | Filling the mind map. | 思维导图（简洁版）| 紫粉/黄/绿三列表（Character / Problem / Solution），5 行内容 |

> **总页数 = 6**（不再自动补 4 的倍数；worksheet 单独印刷，跟绘本对页规则解耦）

#### 2.2 字体强制（与真实样本一致）

| 文字 | 字体 | 字重 | 字号 | 颜色 | 对齐 |
|---|---|---|---|---|---|
| 页面大标题 (Vocabulary/Sentence/Reading/Writing) | Poppins | Bold | **40pt** | #333333 深炭灰 | 居中 |
| 页面副标题 / 题目说明 | Poppins | Regular | **22pt** | #666666 中灰 | 居中 |
| 下划线占位 `________` | **Arial** | Regular | 同上下文 | 黑色 | — |
| Reading 页 MC 题数 | — | — | — | — | **4 道**（2x2 排版，不要 8 道挤一起）|
| 副标题/说明 (Match the words ... / Use the words ... ) | Poppins | Regular | **12pt** | #666666 中灰 | 居中 |
| 题号 (1/2/3/4) | Poppins | Bold | 16pt | 白色（圆形粉底）| 圆心 |
| 题目文本 | Poppins | Regular | 16pt（短题）/ 12pt（Reading 长文）| 黑色 | 左对齐 |
| 选项 (A./B./C.) | Poppins | Regular | 16pt | 黑色 | 左对齐，前置 ☐ 复选框 |
| Reading 长文（顶部红框）| Poppins | Regular | 12pt | 黑色 | 左对齐，行距 1.3 |
| Name 角标（右上五角形）| Poppins | Regular | 14.5pt | 白色 | 居中 |
| Footer (右下 "Level X - <Title>") | Poppins | Regular | 14.5pt | 白色 | 右对齐 |
| Mind Map 表头 (Character/Problem/Solution) | Poppins | Bold | 18pt | 黑色 | 居中 |
| VIPKID Dino Reading Club logo（左上）| Poppins | Bold | 22pt | 白色（+小 Dino 头像图）| 左对齐 |

#### 2.3 品牌外框（所有 6 页统一）

| 元素 | 位置 | 颜色 | 说明 |
|---|---|---|---|
| 外背景 | 整页 | **#E54B7C** 品牌粉色（按 Level 取 `BRAND_COLORS[level]`，L5=粉色）| 4 边各留约 0.3 inch 内边距 |
| 内容白底 | 居中 | 白色，圆角 r≈0.15 inch | 占内容区 100% |
| VIPKID Dino Reading Club | 左上，背景内（露在粉色区上方）| Dino 头像 + 白色文字 | 离左边距 0.3、上边距 0.25 |
| Name 角标 | 右上 | 浅粉 #F8C8DC + 品牌粉色边框 | 五角形向下指 |
| Footer | 右下 | 白字 | "Level X - <绘本标题>" |

#### 2.4 分级题型适配（共用 6 页模板，题型按级别微调）

| 级别 | Page 1 连线 | Page 2 填空 | Page 3 句型 | Page 4 阅读 | Page 5 写作 | Page 6 思维导图 |
|---|---|---|---|---|---|---|
| L0–L2 | 词图连线 4 对 | 词图填空 4 题 | 选词成句 3 题 | 短文 + 4 道 2 选 | True/False 排序 | 简化导图（角色 + 喜好）|
| L3 | 词义连线 4–5 对 | 词义填空 4–5 题 | 句型重写 4 题 | 短文 + 5 道 3 选 | 写一段 30-50 词 | Character/Setting/Action |
| L4 | 词义连线 5 对 | 词义填空 5 题 | 句型选择 4 题（+ 配图）| 全文 + 5 道 3 选 | 5 步骨架 + 30-50 词 | Character/Problem/Solution |
| **L5–L6** | **词义连线 5 对** | **词义填空 5 题** | **句型选择 4 题（+ 绘本图）** | **全文 + 8 道 3 选** | **5 步骨架 + 50-80 词** | **Character/Problem/Solution** |

#### 2.5 题目内容来源规则

| 页 | 内容来源 | 编造规则 |
|---|---|---|
| Page 1 / 2 词汇 | `outline.vocabulary_mastery` (L0-2 双行) 或 `outline.vocabulary_simple` (L3-6 单行) | 定义/填空句由 AI 抽取生成，必须能解释回 mastery 词 |
| Page 3 句型 | 大纲 `grammar_focus` + 7 页故事句 | A/B 选项一对一错，错项是常见语法陷阱（is/are, V/Ving, ed/ing 等） |
| Page 4 阅读 | **绘本全文 7 句** + AI 生成 8 道题 | 5 题事实题（含正确答案） + 3 题推断题 |
| Page 5 写作 | 故事主题 + 主角名 | 5 步骨架按 Beginning / First event / Second event / Funny event / Ending |
| Page 6 思维导图 | 故事中 4-5 个主体（主角 + 配角 + 关键道具）| 每行 (角色, 问题, 解决) 三栏 |

#### 2.6 模板/品牌严格度

| 项 | 标准 |
|---|---|
| 品牌色 | 按 Level 取 `BRAND_COLORS[level]`，L5 = `#E54B7C` |
| Logo | 必须包含 VIPKID Dino 头像（`assets/brand/dino_logo.png`）+ 白色文字 "VIPKID Dino Reading Club" |
| 跨页一致 | 6 页所有外框/Logo/Name/Footer 像素级一致 |

### 交付物 3 — Reading Report DOCX

| 分类 | 明细 |
|---|---|
| 格式 | DOCX |
| 模板约束 | 完全沿用官方模板，**表格 / Logo / 页眉页脚 / 占位符 / 选项框一律不改不删** |
| 输出模式 | 空白版（教师手填）/ 示例答案版（演示） |
| 报告标题 | `阅读报告 绘本标题`，与大纲一致 |
| 姓名/日期 | `姓名: _______ 日期: ____年__月__日`，占位符完整保留 |
| **阅读难度** | 1) 类型：按 Level 自动映射<br>　• L0 / Smart：**Concept & Knowledge-Building Readers**<br>　• L1：**Patterned Narrative & Informational Readers**<br>　• L2：**Early Independent Genre-Exposure Readers**<br>　• L3+：默认 Patterned Narrative（大纲显式指定则优先）<br>2) 阅读字数：绘本全文总词数（**不含标题/问题**）<br>3) 词汇难度：CEFR 等级<br>4) 语法难度：核心语法时态 |
| **词汇掌握** | 仅填 Mastery 列 4–6 词，每词右侧留空单元格 |
| **自然拼读 / 构词法** | L0–L4：来自大纲 `Primary Phonics Focus`，格式 `ai → /eɪ/ (day, stay, play)`<br>**L5–L6：替换为构词法 morphology**（前缀/后缀/词根） |
| **阅读流利度** | 与大纲 `Reader` 栏 100% 一致**一字不改**；L4–L6 仅加粗核心句型 |
| **阅读表达** | 1) 问题来自大纲 `Questions` 栏<br>2) 按难度标星：⭐基础文本简答 / ⭐⭐信息定位提取 / ⭐⭐⭐生活场景拓展<br>3) **L4–L6 不标页码**；L0–L3 在 ⭐ / ⭐⭐ 题后标 `(P#)`，⭐⭐⭐ 永远无页码<br>4) 数量：L0–L2 = 4 题（1⭐+2⭐⭐+1⭐⭐⭐），L3–L6 = 5 题（1⭐+3⭐⭐+1⭐⭐⭐） |
| **课堂参与度** | `😆 Excellent ☐  😄 Great ☐  🙂 Good ☐`，三选项居中保留 |
| 排版硬指标 | **1 页 A4**，底下不能留白；中文阿里巴巴普惠体 2.0 55 Regular，英文 Poppins，行距 1.2 |

### 交付物 4 — Teacher's Guide DOCX

| 分类 | 明细 |
|---|---|
| 格式 | DOCX |
| 语言 | 100% 英文，无中文、无 AI 元评论 |
| 排版 | 模块标签/标题加粗，段落间空行分隔 |
| 固定 8 模块（顺序不可改）| 1) Lesson Guide (Overview)：Basic Info + Vocabulary & Phonics Goal + Key Objectives（SWBAT 开头）<br>2) Pre-Reading Support：Warm-up + 四步 Phonics + Vocabulary Preview<br>3) During Reading：逐页 Picture Walk（Page 2 起）+ Detailed Reading + Comprehension Qs + Rereading<br>4) Post-Reading Practice：Book Activities + Worksheet Activities（每个含 Goal / I Do + You Do / Expected Response / Reinforces Language / Answer Key）<br>5) Reading Check：固定三段原文<br>6) Portfolio Creation Task：固定 3 选项<br>7) Independent Reading：固定文本<br>8) Lesson Close：SWBAT 课堂总结 + 目标词汇收尾 |
| 内容匹配 | 教学内容/词汇/句型/问题 100% 来自大纲；**Answer Key 与 Worksheet 逐题一致** |

---

## 四、批量生产 & 异常处理

| 项 | 标准 |
|---|---|
| 数据隔离 | 多大纲并行处理时严格隔离，无交叉污染 |
| 交付物数量 | 输入 N 个大纲 → 输出 N×4 件，无缺失 |
| 失败重跑 | 单大纲失败不影响其他大纲；支持自动重试 / 单独重跑；保留处理日志 |
| 资源管理 | 顺序/并发可配置；单大纲超时 ≤30 分钟 |
| 输出格式 | 1) 每大纲一个子文件夹；2) 平铺 + 规范命名 + 可选 ZIP |

---

## 五、当前实现状态对照表（v1.5 vs 现有代码）

| 规范点 | 现状 | 备注 |
|---|---|---|
| 命名规范 `Level X_BookXX_品类_标题` | ✅ 已实现（`scripts/web_app.py: _name_prefix`） | |
| 绘本固定 `封面 + 7 页 + 封底` | ✅ 已实现 | `ppt_builder` 中 9 页结构 |
| 即梦 4.6 真图 | ✅ 已实现（`scripts/seedream_client.py`）| **默认不勾占位图**，UI 会显示预估时长 |
| RR L4–L6 不标页码 | ✅ 已实现（`_no_page_numbers`）| |
| RR Reader Type 自动映射 | ✅ 已实现（`_default_reader_type`）| |
| RR 1 页 A4 | ✅ 已实现 | 行距 1.2，10–11pt 自适应 |
| RR ⭐ 大写橙色 | ✅ 已实现 | |
| RR 课堂参与度 emoji + ☐ 居中 | ✅ 已实现 | |
| 字体 Poppins (en) + 阿里巴巴普惠体 (zh) | ✅ 已实现 | |
| Worksheet 4 页结构 | ⏳ **待改造**（当前 6 页） | 下一步重点 |
| TEACHER KIM 角色 | ⏳ **待制作**（参考图 + prompt 规则） | |
| WINNIE 角色 | ⏳ **待制作** | |
| L5–L6 自然拼读 → morphology | ⏳ **待加 AI 抽取分支** | UI 字段名也可改 |
| TG 8 模块顺序 / SWBAT 表述 | ⚠️ 部分实现（当前 9 段） | 需对齐 8 模块 |
| Worksheet Answer Key ↔ TG 一致性校验 | ⏳ 待加 | |
