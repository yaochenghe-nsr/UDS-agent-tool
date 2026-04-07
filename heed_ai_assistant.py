"""
HEED AI 助手 — 多模型多厂商版
支持：Google / Anthropic / OpenAI / Meta(Groq) / DeepSeek / 豆包 / 千问 / Kimi
"""

import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="HEED AI 助手",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 全局样式 ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html, body, [data-testid="stApp"] {
    background-color: #ffffff !important;
    color: #1f1f1f !important;
    font-family: "Google Sans", "Helvetica Neue", Arial, sans-serif !important;
}
[data-testid="stSidebar"] { background-color: #f8f9fa !important; border-right: 1px solid #e8eaed !important; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] span, [data-testid="stSidebar"] div { color: #1f1f1f !important; }
[data-testid="stMain"], .main, .block-container { background-color: #ffffff !important; }
[data-testid="stChatMessage"] { background: transparent !important; border: none !important; padding: 4px 0 !important; }
[data-testid="stChatInput"] textarea {
    border-radius: 24px !important; border: 1.5px solid #dadce0 !important;
    background: #ffffff !important; color: #1f1f1f !important;
}
[data-testid="stChatInput"]:focus-within { border-color: #1a73e8 !important; }
.stButton button {
    border-radius: 20px !important; border: 1px solid #dadce0 !important;
    background: #ffffff !important; color: #1a73e8 !important;
    font-weight: 500 !important; font-size: 0.83em !important;
}
.stButton button:hover { background: #e8f0fe !important; border-color: #1a73e8 !important; }
hr { border-color: #e8eaed !important; margin: 6px 0 !important; }
pre { background: #f8f9fa !important; border-radius: 8px !important; }
pre code { font-size: 0.82em !important; color: #1f1f1f !important; }
footer, #MainMenu { visibility: hidden !important; }

.heed-header { display: flex; align-items: center; gap: 10px; padding: 8px 0 4px 0; }
.heed-logo {
    width: 34px; height: 34px;
    background: linear-gradient(135deg, #4285f4, #a142f4);
    border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 17px; color: white; flex-shrink: 0;
}
.heed-title { font-size: 1.4em; font-weight: 600; color: #1f1f1f; margin: 0; }
.heed-model-badge {
    font-size: 0.72em; background: #e8f0fe; color: #1a73e8;
    border-radius: 20px; padding: 2px 10px; font-weight: 500;
    margin-left: auto; white-space: nowrap;
}
.heed-ctx-badge {
    font-size: 0.72em; background: #e6f4ea; color: #137333;
    border-radius: 20px; padding: 2px 10px; font-weight: 500; white-space: nowrap;
}

/* 右上角模型速查 */
.model-ref-wrap {
    position: fixed; top: 56px; right: 20px; z-index: 999;
    font-family: "Google Sans", Arial, sans-serif;
    background: #ffffff; border: 1px solid #e8eaed; border-radius: 14px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08); padding: 12px 14px;
    width: 320px; font-size: 0.77em; line-height: 1.55; color: #1f1f1f;
}
.model-ref-wrap summary {
    cursor: pointer; font-size: 0.83em; font-weight: 600; color: #1a73e8;
    padding-bottom: 8px; border-bottom: 1px solid #e8eaed; margin-bottom: 8px;
    user-select: none; list-style: none; display: flex;
    align-items: center; justify-content: space-between;
}
.model-ref-wrap summary:hover { color: #1557b0; }
.model-ref-wrap summary::-webkit-details-marker { display: none; }
.model-ref-wrap summary::after { content: "▲"; font-size: 0.7em; color: #5f6368; }
.model-ref-wrap details:not([open]) summary::after { content: "▼"; }
.model-ref-wrap h4 {
    margin: 8px 0 2px 0; font-size: 0.8em; font-weight: 700;
    color: #5f6368; text-transform: uppercase; letter-spacing: 0.05em;
}
.model-ref-wrap h4:first-of-type { margin-top: 0; }
.model-ref-wrap table { width: 100%; border-collapse: collapse; margin-bottom: 2px; }
.model-ref-wrap td { padding: 2px 4px; vertical-align: top; border-bottom: 1px solid #f1f3f4; }
.model-ref-wrap td:first-child { font-family: monospace; color: #1a73e8; white-space: nowrap; width: 44%; }
.provider-section { margin-bottom: 6px; }
.provider-label {
    font-size: 0.75em; font-weight: 700; color: #ffffff;
    border-radius: 4px; padding: 1px 7px; display: inline-block; margin-bottom: 3px;
}
.model-ref-tip {
    margin-top: 8px; background: #fef9c3; border-radius: 8px;
    padding: 5px 9px; color: #7a5f00; font-size: 0.9em;
}
</style>
""", unsafe_allow_html=True)

# ── 厂商配置 ──────────────────────────────────────────────────────────────────
PROVIDERS = {
    "🌐 Google — Gemini": {
        "id": "google",
        "key_label": "Google API Key",
        "key_placeholder": "AIza...",
        "key_help": "前往 https://aistudio.google.com/app/apikey 获取",
        "models": [],  # 动态加载
        "color": "#4285f4",
    },
    "🟣 Anthropic — Claude": {
        "id": "anthropic",
        "key_label": "Anthropic API Key",
        "key_placeholder": "sk-ant-...",
        "key_help": "前往 https://console.anthropic.com/settings/keys 获取",
        "models": [
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-5-20251022",
            "claude-haiku-4-5-20251001",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "color": "#7c3aed",
    },
    "🟢 OpenAI — GPT": {
        "id": "openai",
        "key_label": "OpenAI API Key",
        "key_placeholder": "sk-...",
        "key_help": "前往 https://platform.openai.com/api-keys 获取",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "o1",
            "o1-mini",
            "o3-mini",
        ],
        "color": "#10a37f",
    },
    "🦙 Meta — Llama (Groq)": {
        "id": "groq",
        "key_label": "Groq API Key",
        "key_placeholder": "gsk_...",
        "key_help": "前往 https://console.groq.com/keys 获取（免费托管 Llama）",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "mixtral-8x7b-32768",
        ],
        "base_url": "https://api.groq.com/openai/v1",
        "color": "#0064e0",
    },
    "🔵 DeepSeek": {
        "id": "deepseek",
        "key_label": "DeepSeek API Key",
        "key_placeholder": "sk-...",
        "key_help": "前往 https://platform.deepseek.com/api_keys 获取",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "base_url": "https://api.deepseek.com/v1",
        "color": "#1677ff",
    },
    "🟠 字节跳动 — 豆包": {
        "id": "doubao",
        "key_label": "火山引擎 API Key",
        "key_placeholder": "...",
        "key_help": "前往 https://console.volcengine.com/ark 获取",
        "models": [
            "doubao-pro-256k",
            "doubao-pro-32k",
            "doubao-pro-4k",
            "doubao-lite-32k",
            "doubao-lite-4k",
        ],
        "base_url": "https://ark.volces.com/api/v3",
        "color": "#ff6900",
    },
    "🔷 阿里巴巴 — 通义千问": {
        "id": "qwen",
        "key_label": "DashScope API Key",
        "key_placeholder": "sk-...",
        "key_help": "前往 https://dashscope.console.aliyun.com/apiKey 获取",
        "models": [
            "qwen-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen-long",
            "qwen2.5-72b-instruct",
            "qwen2.5-32b-instruct",
        ],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "color": "#ff6a00",
    },
    "🌙 月之暗面 — Kimi": {
        "id": "kimi",
        "key_label": "Moonshot API Key",
        "key_placeholder": "sk-...",
        "key_help": "前往 https://platform.moonshot.cn/console/api-keys 获取",
        "models": [
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
        "base_url": "https://api.moonshot.cn/v1",
        "color": "#6366f1",
    },
}


# ── 侧边栏 ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("#### ✦ HEED AI 配置")
    st.divider()

    # 厂商选择
    provider_name = st.selectbox("AI 厂商", list(PROVIDERS.keys()), index=0)
    provider = PROVIDERS[provider_name]
    provider_id = provider["id"]

    st.divider()

    # API Key（按厂商独立存储）
    api_key = st.text_input(
        provider["key_label"],
        type="password",
        placeholder=provider["key_placeholder"],
        help=provider["key_help"],
        key=f"apikey_{provider_id}",
    )

    st.divider()

    # 模型选择
    if provider_id == "google":
        def fetch_google_models(key):
            try:
                from google import genai
                client = genai.Client(api_key=key)
                return sorted([
                    m.name.replace("models/", "")
                    for m in client.models.list()
                    if "generateContent" in (m.supported_actions or []) and "gemini" in m.name
                ])
            except Exception:
                return []

        if api_key:
            cache_key = f"gmodels_{api_key[:8]}"
            if cache_key not in st.session_state:
                with st.spinner("加载可用模型..."):
                    st.session_state[cache_key] = fetch_google_models(api_key)
            model_list = st.session_state[cache_key]
        else:
            model_list = []

        if model_list:
            default_idx = next((i for i, m in enumerate(model_list)
                                if "2.0-flash" in m and "lite" not in m and "exp" not in m), 0)
            selected_model = st.selectbox("模型（已验证可用）", model_list, index=default_idx)
        else:
            st.caption("填入 API Key 后自动加载可用模型")
            selected_model = "gemini-2.0-flash"
    else:
        selected_model = st.selectbox("模型", provider["models"], index=0)

    st.divider()
    temperature = st.slider("创意度 (Temperature)", 0.0, 1.0, 0.7, 0.05)
    max_tokens  = st.slider("最大输出 Token", 512, 8192, 4096, 128)

    st.divider()
    st.markdown("**🔍 UDS 工程感知**")
    analyze_btn = st.button("分析当前 UDS 工程", use_container_width=True)
    if st.button("清空对话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.project_context = ""
        st.rerun()

    st.caption(f"HEED AI v2.0 · {provider_name.split('—')[-1].strip()}")

# ── Session State ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "project_context" not in st.session_state:
    st.session_state.project_context = ""

# ── 工程分析 ──────────────────────────────────────────────────────────────────
def load_project_context() -> str:
    sections = []
    base = Path(__file__).parent
    app_py = base / "app.py"
    if app_py.exists():
        content = app_py.read_text(encoding="utf-8")
        sections.append(f"## 文件：app.py\n```python\n{content}\n```")
    skills_dir = base / ".claude" / "skills"
    if skills_dir.exists():
        for fpath in sorted(skills_dir.rglob("*")):
            if fpath.is_file():
                try:
                    content = fpath.read_text(encoding="utf-8")
                    rel = fpath.relative_to(base)
                    ext = fpath.suffix.lstrip(".") or "text"
                    sections.append(f"## 文件：{rel}\n```{ext}\n{content}\n```")
                except Exception:
                    pass
    if not sections:
        return ""
    return (
        "以下是当前 UDS 工程的关键文件内容，请在回答时将其作为背景知识：\n\n"
        + "\n\n---\n\n".join(sections)
    )

if analyze_btn:
    with st.spinner("读取工程文件中..."):
        ctx = load_project_context()
    if ctx:
        st.session_state.project_context = ctx
        st.sidebar.success("✅ 工程上下文已加载")
    else:
        st.sidebar.warning("⚠️ 未找到工程文件")

# ── 主界面：左列聊天 + 右列模型速查 ─────────────────────────────────────────
col_chat, col_ref = st.columns([3, 1], gap="medium")

# ── 右列：模型速查 ────────────────────────────────────────────────────────────
with col_ref:
    with st.expander("📖 全平台模型速查", expanded=False):
        st.markdown("""
<style>
.mr-badge {
    display:inline-block; color:#fff; border-radius:4px;
    padding:1px 7px; font-size:0.68em; font-weight:700; margin:5px 0 2px 0;
}
.mr-tbl { width:100%; border-collapse:collapse; margin-bottom:2px; }
.mr-tbl td { padding:2px 3px; border-bottom:1px solid #f1f3f4; font-size:0.75em; vertical-align:top; }
.mr-tbl td:first-child { font-family:monospace; color:#1a73e8; width:46%; white-space:nowrap; }
.mr-tip { background:#fef9c3; border-radius:6px; padding:5px 8px; color:#7a5f00; font-size:0.72em; margin-top:6px; }
</style>
<span class="mr-badge" style="background:#4285f4">Google Gemini</span>
<table class="mr-tbl">
<tr><td>2.5-pro</td><td>最强推理</td></tr>
<tr><td>2.0-flash ⭐</td><td>日常首选</td></tr>
<tr><td>1.5-flash</td><td>额度备选</td></tr>
</table>
<span class="mr-badge" style="background:#7c3aed">Anthropic Claude</span>
<table class="mr-tbl">
<tr><td>claude-opus-4-5</td><td>最强推理</td></tr>
<tr><td>claude-sonnet-4-5</td><td>均衡推荐</td></tr>
<tr><td>claude-haiku-4-5</td><td>极速低耗</td></tr>
</table>
<span class="mr-badge" style="background:#10a37f">OpenAI GPT</span>
<table class="mr-tbl">
<tr><td>gpt-4o</td><td>多模态旗舰</td></tr>
<tr><td>gpt-4o-mini</td><td>轻量快速</td></tr>
<tr><td>o3-mini</td><td>深度推理</td></tr>
</table>
<span class="mr-badge" style="background:#0064e0">Meta Llama (Groq)</span>
<table class="mr-tbl">
<tr><td>llama-3.3-70b</td><td>开源旗舰</td></tr>
<tr><td>llama-3.1-8b</td><td>极速轻量</td></tr>
</table>
<span class="mr-badge" style="background:#1677ff">DeepSeek</span>
<table class="mr-tbl">
<tr><td>deepseek-chat</td><td>V3 综合强</td></tr>
<tr><td>deepseek-reasoner</td><td>R1 深度推理</td></tr>
</table>
<span class="mr-badge" style="background:#ff6900">豆包 / 千问 / Kimi</span>
<table class="mr-tbl">
<tr><td>doubao-pro-32k</td><td>字节长文本</td></tr>
<tr><td>qwen-max</td><td>阿里旗舰</td></tr>
<tr><td>moonshot-v1-128k</td><td>超长上下文</td></tr>
</table>
<div class="mr-tip">💡 国内推荐：<br>DeepSeek · 千问 · 豆包 · Kimi</div>
""", unsafe_allow_html=True)

# ── 左列：顶栏 + 聊天 ────────────────────────────────────────────────────────
with col_chat:
    ctx_badge = (
        '<span class="heed-ctx-badge">📂 UDS 上下文已激活</span>'
        if st.session_state.project_context else ""
    )
    st.markdown(f"""
<div class="heed-header">
  <div class="heed-logo">✦</div>
  <span class="heed-title">HEED AI 助手</span>
  {ctx_badge}
  <span class="heed-model-badge">{provider_name.split()[0]} {selected_model}</span>
</div>
""", unsafe_allow_html=True)
    st.divider()

    if not st.session_state.messages:
        st.markdown("""
<div style="text-align:center; padding: 60px 0 40px 0; color: #5f6368;">
  <div style="font-size:3em; margin-bottom:14px;">✦</div>
  <div style="font-size:1.25em; font-weight:500; color:#1f1f1f; margin-bottom:10px;">
    有什么可以帮你？
  </div>
  <div style="font-size:0.88em; line-height:2;">
    UDS 协议解析 &nbsp;·&nbsp; CAN 总线调试 &nbsp;·&nbsp; ECU 开发咨询<br>
    代码生成 &nbsp;·&nbsp; 工程文件分析 &nbsp;·&nbsp; 技术文档查询
  </div>
</div>
""", unsafe_allow_html=True)

    for msg in st.session_state.messages:
        avatar = "🧑" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

# ── 输入框（页面底部，跨越全宽）────────────────────────────────────────────────
user_input = st.chat_input("向 HEED AI 提问…")

# ── 系统提示 ──────────────────────────────────────────────────────────────────
def build_system_prompt(project_ctx: str) -> str:
    base = (
        "你是 HEED AI 助手，一个专业的汽车诊断与嵌入式系统顾问，"
        "擅长 UDS (ISO 14229) 协议、CAN 总线、ECU 开发。"
        "请用中文回答，代码部分保持英文。"
    )
    return base + ("\n\n" + project_ctx if project_ctx else "")

# ── 错误处理 ──────────────────────────────────────────────────────────────────
def handle_error(err: str) -> str:
    import re
    if "API_KEY_INVALID" in err or "api key not valid" in err.lower() or "invalid api key" in err.lower() or "authentication" in err.lower():
        return "❌ API Key 无效，请检查填写是否正确。"
    if "RESOURCE_EXHAUSTED" in err or "quota" in err.lower() or "rate limit" in err.lower() or "429" in err:
        retry = re.search(r'retry[^0-9]*(\d+)', err)
        wait = f"，约 {retry.group(1)} 秒后可重试" if retry else ""
        return f"⏳ 当前模型额度已用尽{wait}，请稍等片刻或切换其他模型。"
    if "NOT_FOUND" in err or "model_not_found" in err.lower() or "404" in err:
        return "❌ 模型不可用，请切换其他模型后重试。"
    return f"❌ 调用出错：{err}"

# ── 各厂商 API 调用 ───────────────────────────────────────────────────────────
def call_google(api_key, model, messages, system_prompt, temperature, max_tokens):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "❌ 缺少依赖：pip install google-genai"
    try:
        client = genai.Client(api_key=api_key)
        contents = []
        for m in messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=messages[-1]["content"])]))
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        return client.models.generate_content(model=model, contents=contents, config=config).text
    except Exception as e:
        return handle_error(str(e))


def call_anthropic(api_key, model, messages, system_prompt, temperature, max_tokens):
    try:
        import anthropic
    except ImportError:
        return "❌ 缺少依赖：pip install anthropic"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        hist = [{"role": m["role"], "content": m["content"]} for m in messages]
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=hist,
            temperature=temperature,
        )
        return resp.content[0].text
    except Exception as e:
        return handle_error(str(e))


def call_openai_compat(api_key, model, messages, system_prompt, temperature, max_tokens, base_url=None):
    try:
        from openai import OpenAI
    except ImportError:
        return "❌ 缺少依赖：pip install openai"
    try:
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        hist = [{"role": "system", "content": system_prompt}]
        hist += [{"role": m["role"], "content": m["content"]} for m in messages]
        resp = client.chat.completions.create(
            model=model,
            messages=hist,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return handle_error(str(e))


def get_response(provider_id, provider_cfg, api_key, model, messages, project_ctx, temperature, max_tokens):
    if not api_key:
        return f"❌ 请在左侧侧边栏填入 {provider_cfg['key_label']}。"
    system_prompt = build_system_prompt(project_ctx)
    if provider_id == "google":
        return call_google(api_key, model, messages, system_prompt, temperature, max_tokens)
    elif provider_id == "anthropic":
        return call_anthropic(api_key, model, messages, system_prompt, temperature, max_tokens)
    else:
        base_url = provider_cfg.get("base_url")
        return call_openai_compat(api_key, model, messages, system_prompt, temperature, max_tokens, base_url)

# ── 处理输入 ──────────────────────────────────────────────────────────────────
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(user_input)

    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner(""):
            reply = get_response(
                provider_id=provider_id,
                provider_cfg=provider,
                api_key=api_key,
                model=selected_model,
                messages=st.session_state.messages,
                project_ctx=st.session_state.project_context,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
