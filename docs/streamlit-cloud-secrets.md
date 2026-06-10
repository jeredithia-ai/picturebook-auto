# Streamlit Cloud Secrets 配置指南

## 操作步骤

1. 打开 https://share.streamlit.io ，进入 picturebook-auto 应用。
2. 右上角菜单 → **Settings** → **Secrets**。
3. 打开本机 **`.streamlit/secrets-cloud-paste.toml`**（已 gitignore，含真实 Key），**整文件复制**粘贴到 Cloud 编辑框（勿提交该文件到 Git）。
4. 点击 **Save**，等待约 3–5 分钟自动重新部署。
5. 分享 URL：https://picturebook-auto-43fmumu7yf9lk5tfv2piug.streamlit.app

Suqianxue 及同事账号仅写在 Cloud Secrets 或本机 gitignore 的 secrets 文件中，不要写入 Git 仓库。

## 登录账号（密码均为 VIPKID@2026，区分大小写）

| 用户名 | 用途 |
|--------|------|
| Suqianxue | 你的账号 |
| Sally | 同事 |
| Jeffrey | 同事 |
| Cola | 同事 |

## Cloud Secrets 结构（占位符示例）

完整可粘贴内容请用本机 `.streamlit/secrets-cloud-paste.toml`（由 `.env` 生成，不入库）。

**重要（TOML 语法）**：`[APP_USERS]` 会开启一张表；若把 API Key 写在 `[APP_USERS]` **下面**，它们会被当成用户表里的字段，`st.secrets["IMAROUTER_API_KEY"]` 会读不到。正确做法是：**所有 API / 模型配置写在文件最前面（顶层）**，**最后**再放 `[APP_USERS]`，且该段内只保留 4 个用户名。

```toml
IMAROUTER_API_KEY = "sk-替换为你的-imarouter-key"

TEXT_MODEL = "claude-opus-4-7"
EXTRACT_MODEL = "claude-opus-4-7"

IMAGE_MODEL = "gpt-image-2"
IMAGE_SIZE = "1536x1024"

ARK_API_KEY = "ark-替换为你的-ark-key"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
JIMENG_SEEDREAM_MODEL = "doubao-seedream-4-5-251128"
JIMENG_SEEDREAM_SIZE = "2304x1728"

DOUBAO_API_KEY = "ark-替换为你的-doubao-key-或与-ARK-相同"
DOUBAO_MODEL = "doubao-1-5-pro-32k-250115"
DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

IMAGE_SELF_REVIEW = "true"
VISION_REVIEW_MODEL = "claude-sonnet-4-6"

[APP_USERS]
Suqianxue = "VIPKID@2026"
Sally = "VIPKID@2026"
Jeffrey = "VIPKID@2026"
Cola = "VIPKID@2026"
```

## 本地

复制 `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`（已在 `.gitignore`），或与本机 `.env` 对齐后本地运行；**不要** `git add` `secrets.toml` 或 `secrets-cloud-paste.toml`。
