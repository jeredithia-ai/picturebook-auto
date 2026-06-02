# picturebook-auto

英文启蒙绘本自动化流水线 v2 — 一段故事原文 → AI 抽取 → 老师微调 → **4 件套 ZIP**（Picture Book PPT + Worksheet PPTX + Reading Report DOCX + Teacher's Guide DOCX）。

> **基线**：以 2026-05-26 完整跑通的 L4《Visiting Scotland》流程为冻结基线。
> **v2 升级（2026-05-31）**：Streamlit Web App + Doubao 文本抽取 + Worksheet/RR/TG 三个 builder。
> **标准**：所有 L0–L6 + 4 件套必须遵守 [`STANDARD.md`](STANDARD.md)（v1.4）。

---

## 必读文档（按顺序）

| 文档 | 用途 |
|---|---|
| [`STANDARD.md`](STANDARD.md) | **核心规范**——版式、字体、画风、IP、prompt、Level 适配、4 件套 |
| [`docs/LESSONS_LEARNED.md`](docs/LESSONS_LEARNED.md) | 历次踩坑沉淀 |
| [`PIPELINE.md`](PIPELINE.md) | 流程图与模块职责 |
| [`CHECKLIST.md`](CHECKLIST.md) | 出书验收单 |
| [`inputs/TEMPLATE_OUTLINE.md`](inputs/TEMPLATE_OUTLINE.md) | 新书大纲模板（CLI 用） |
| [`INSTALL_FONT.txt`](INSTALL_FONT.txt) | 字体安装（Poppins） |

---

## 两条入口

### A. Web 模式（推荐 — 给老师用）

```powershell
cd C:\Users\Jered\picturebook-auto
.\.venv\Scripts\Activate.ps1
streamlit run scripts\web_app.py
```

打开 http://localhost:8501，按 3 步走：
1. 填表（Title / Level / 故事原文）
2. 点 **AI 抽取**（Doubao 自动抽词、拆段、出题）
3. 微调后点 **Generate All** → 4 件套 ZIP 下载

### B. CLI 模式（只生成绘本 PPT，老路径）

```powershell
python scripts\run.py --outline inputs\L4_Book13_Visiting_Scotland.md --real-images
```

---

## 4 件套对照官方样本

| 件 | 输出 | 对照样本 |
|---|---|---|
| Picture Book PPT | 9 页 = 封面 + 7 故事 + 元信息 | `L4_Book13.pptx` |
| Worksheet PPTX | 6 页活动（Vocab×2 + Sentence×2 + Reading + PBL） | `L4-13 Worksheet.pptx` |
| Reading Report DOCX | 一页表格 + 题量梯度（L0-2=4题 / L3-6=5题） | `L4-13 Reading report.docx` |
| Teacher's Guide DOCX | 9 大段长文 | `L4-B13 Teacher's Guide.docx` |

---

## 仓库结构（v2）

```
picturebook-auto/
├── STANDARD.md                       # ⭐ 标准规范 v1.4
├── docs/LESSONS_LEARNED.md           # 踩坑沉淀
├── PIPELINE.md / CHECKLIST.md
├── README.md / INSTALL_FONT.txt
├── requirements.txt / .env.example
├── inputs/
│   ├── TEMPLATE_OUTLINE.md
│   ├── L4_Book13_Visiting_Scotland.md
│   └── L5_Book01_What_Makes_a_Good_Friend.md
├── templates/
│   └── worksheet_a4.pptx             # VIPKID Dino A4 模板（7 Level 母版）
├── assets/
│   ├── characters/                   # Mia/Tommy/Anna 8/10/12 三档参考图
│   ├── brand/dino_logo.png           # Dino mascot
│   ├── fonts/Poppins/                # 19 weight ttf
│   └── style/
├── scripts/
│   ├── config.py                     # 配置 + brand color + RR 题量分布
│   ├── parser.py                     # outline.md → BookOutline (v1.4 字段扩展)
│   ├── prompt_builder.py             # 五段式 prompt + 参考图
│   ├── seedream_client.py            # 即梦 4.6 (Seedream)
│   ├── ai_extractor.py               # 🆕 Doubao 文本抽词/拆段/出题
│   ├── ppt_builder.py                # 9 页绘本 PPT
│   ├── worksheet_builder.py          # 🆕 6 页 worksheet (brand 色 + Poppins)
│   ├── reading_report_builder.py     # 🆕 1 页 RR (题量梯度 + P# + 星级)
│   ├── teacher_guide_builder.py      # 🆕 9 段 TG
│   ├── web_app.py                    # 🆕 Streamlit 单页表单
│   └── run.py                        # CLI 入口
├── outputs/<slug>_<timestamp>/       # 每次运行一个子目录
│   ├── images/                       # 8 张 AI 图
│   ├── <Title>.pptx                  # 绘本 PPT
│   ├── <slug>_Worksheet.pptx
│   ├── <slug>_ReadingReport.docx
│   ├── <slug>_TeachersGuide.docx
│   └── <slug>_全套.zip
└── .github/workflows/build_book.yml
```

---

## 本地安装

```powershell
cd C:\Users\Jered\picturebook-auto
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
# 编辑 .env：
#   ARK_API_KEY=<volcengine 方舟 key, Doubao + 即梦共用>
#   DOUBAO_MODEL=ep-xxxxx-xxxxx   # 你自己的 endpoint id
#   JIMENG_MODEL=doubao-seedream-4-5-251128
```

---

## CLI 选项（绘本 PPT 单独）

| 参数 | 作用 |
|---|---|
| `-i, --outline` | 大纲文件路径（必填） |
| `-o, --output` | 输出目录（默认 `outputs/<slug>/`） |
| `--real-images` | 强制调即梦 API 真实生图 |
| `--mock-images` | 占位图模式（秒出，调试版式用） |
| `--pages 0,4,5` | 仅重生指定页，其余沿用已有 png |
| `--no-images` | 完全跳过生图，只重组 PPT |

---

## GitHub Actions

1. 仓库 push 到 GitHub
2. Settings → Secrets → Actions → New: `ARK_API_KEY` = 火山方舟 Key
3. Actions → "Build Picture Book" → Run workflow → 填大纲文件名
4. 完成后下方 Artifacts 下载 zip

---

## 部署到 Streamlit Community Cloud（免费）

1. 把仓库推到 GitHub（`git push`）
2. 打开 https://share.streamlit.io，登录 → New App
3. 选这个 repo / 分支 / `scripts/web_app.py`
4. Advanced settings → Secrets：
   ```toml
   ARK_API_KEY = "ark-xxxxx"
   DOUBAO_MODEL = "ep-xxxxx-xxxxx"
   ```
5. Deploy → 5 分钟后给老师拿到 https://xxxx.streamlit.app/ 链接

> **注意**：Streamlit Cloud 出公网调用即梦图生成需 ≤2 min/次（默认超时 30s 太短），建议在云端跑 mock 模式做内容审核，真实生图本地跑。

---

## 4 件套规则速查

* **年龄**：Smart-L3 = 8 岁 / **L4 = 10 岁** / **L5/L6 = 12 岁**
* **绘本 Vocab 页**：L0-L2 双行（Mastery + Exposure）/ **L3-L6 单行 4 词**
* **RR 题量**：L0-L2 = 4 题（1+2+2+3）/ **L3-L6 = 5 题（1+2+2+2+3）**；P# 必带，末尾 ⭐⭐⭐ 不带 P#
* **Worksheet**：6 页 = 题型池随机；大标题 40pt Bold / 说明 22pt Italic Gray / 题干 18pt 黑
* **品牌色**：Smart=`#5E9F49` / L1=`#F18200` / L2=`#54C2F0` / L3=`#E94653` / L4=`#00B0C4` / **L5=`#E95283`** / L6=`#0677B7`
* **词汇形式**：必须 lemma 原型 + 小写 + 无标点（`walk`，不是 `walks/walking`）

> 完整细节见 [`STANDARD.md`](STANDARD.md) v1.4。
