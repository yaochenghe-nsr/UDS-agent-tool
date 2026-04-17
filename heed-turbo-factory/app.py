"""
HEED AI 自动化工厂控制台
Streamlit 应用 — 四阶段流水线：需求定义 → 代码生成 → 测试验证 → 追溯矩阵
"""

import json
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ── 常量 ──────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "output"
REPORTS_DIR = Path(__file__).parent / "reports"
OUTPUT_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

REQ_JSON_PATH = OUTPUT_DIR / "requirements.json"
CODE_PATH = OUTPUT_DIR / "generated_code.py"
TEST_PATH = OUTPUT_DIR / "test_generated.py"
TEST_REPORT_PATH = REPORTS_DIR / "test_report.txt"
TEST_OUTLINE_PATH = REPORTS_DIR / "test_outline.md"

# ── Gemini 工具函数 ───────────────────────────────────────────────────────────

GEMINI_MODEL_DEFAULT = "gemini-2.5-flash-lite"


def get_selected_model() -> str:
    """返回当前选中的 Gemini 模型名，优先读取 session_state。"""
    return st.session_state.get("selected_gemini_model", GEMINI_MODEL_DEFAULT)


def list_gemini_models(api_key: str) -> list[str]:
    """查询 API Key 对应的可用 Gemini 模型列表。"""
    try:
        from google import genai
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        models = client.models.list()
        names = [
            m.name.replace("models/", "")
            for m in models
            if "generateContent" in (m.supported_actions or [])
            and "gemini" in m.name.lower()
        ]
        return sorted(names) if names else [GEMINI_MODEL_DEFAULT]
    except Exception:
        return [GEMINI_MODEL_DEFAULT]


def get_gemini_client(api_key: str, probe: bool = False):
    """初始化 google.genai Client，probe=True 时发一条测试请求验证连通性。"""
    try:
        from google import genai
    except ImportError:
        st.error("缺少依赖：请运行 `pip install google-genai`")
        return None

    try:
        client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )
        if probe:
            client.models.generate_content(
                model=get_selected_model(), contents="test"
            )
            # probe 请求不计入冷却计时
        return client
    except Exception as e:
        st.error(f"模型初始化失败：{e}")
        return None


def call_gemini(client, prompt: str, max_retries: int = 3, json_mode: bool = False) -> str:
    """调用 Gemini 1.5 Flash，带最优 Token 配置，遇到 429 自动退避重试。

    Args:
        client:      google.genai Client 实例。
        prompt:      用户 prompt 字符串。
        max_retries: 最大重试次数（默认 3）。
        json_mode:   True 时强制返回 application/json，适用于结构化数据生成。
    """
    from google.genai import types  # 延迟导入，避免未安装时崩溃

    model = get_selected_model()

    # ── 最优性价比参数配置 ────────────────────────────────────────────────────
    config_kwargs: dict = {
        "temperature": 0.2,        # 代码/数据生成稳定性
        "top_p": 0.8,              # 减少随机发散
        "max_output_tokens": 2048, # 控制单次输出上限
    }
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"

    gen_config = types.GenerateContentConfig(**config_kwargs)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=gen_config,
            )
            return response.text.strip()
        except Exception as exc:
            err = str(exc)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait_match = re.search(r"retry[^\d]*(\d+)s", err, re.IGNORECASE)
                wait = int(wait_match.group(1)) + 2 if wait_match else 20 * (attempt + 1)
                if attempt < max_retries - 1:
                    st.warning(
                        f"配额限制（429），{wait} 秒后自动重试 "
                        f"（{attempt + 1}/{max_retries}）…"
                    )
                    time.sleep(wait)
                    continue
                st.error(
                    f"配额已耗尽：当前 API Key 对模型 **{model}** 的付费配额不足。\n\n"
                    "**解决方案**：\n"
                    "1. 前往 [Google AI Studio](https://aistudio.google.com) 确认付费账单已开启\n"
                    "2. 检查 API Key 是否绑定了正确的 GCP 项目\n"
                    "3. 或等待配额重置（通常次日）"
                )
            else:
                st.error(f"Gemini API 调用失败：{exc}")
            return ""
    return ""


# ── Claude 工具函数 ───────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-6"


def call_claude(api_key: str, prompt: str) -> str:
    """调用 Claude API 生成内容。"""
    try:
        import anthropic
    except ImportError:
        st.error("缺少依赖：请运行 `pip install anthropic`")
        return ""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        st.error(f"Claude API 调用失败：{e}")
        return ""


def extract_json_block(text: str) -> str:
    """从 Gemini 返回文本中提取第一个 JSON 代码块（或原始文本）。"""
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    return match.group(1).strip() if match else text.strip()


def extract_code_block(text: str, lang: str = "python") -> str:
    """从 Gemini 返回文本中提取指定语言的代码块。"""
    match = re.search(rf"```(?:{lang})?\s*([\s\S]+?)```", text, re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()

# ── Session State 初始化 ──────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "requirements": [],       # List[dict]: 当前需求列表
        "generated_code": "",     # str: 生成的 Python 代码
        "test_outline": "",       # str: 测试大纲 Markdown
        "test_code": "",          # str: 测试代码
        "test_report": "",        # str: pytest 输出
        "trace_data": [],         # List[dict]: 追溯矩阵
        "claude_cmd": "",         # str: 生成的 Claude Code CLI 命令
        "test_cmd": "",           # str: 生成的测试引导命令
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

# ── 需求分解 Prompt ───────────────────────────────────────────────────────────

REQ_PROMPT_TEMPLATE = textwrap.dedent("""
    你是一名资深需求分析师。请将以下一句话描述的功能拆解为结构化的软件需求列表。

    要求：
    1. 每条需求必须有唯一 ID（格式：REQ-001, REQ-002, ...）
    2. 每条需求包含：id、title（简短标题）、description（详细描述）、priority（High/Medium/Low）
    3. 输出纯 JSON 数组，不要任何额外说明，格式如下：
    ```json
    [
      {{
        "id": "REQ-001",
        "title": "...",
        "description": "...",
        "priority": "High"
      }}
    ]
    ```

    用户输入：{user_input}
""").strip()

# ── Tab 1：需求定义 ───────────────────────────────────────────────────────────

def tab_requirements(api_key: str):
    st.html("""
<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:12px;">
  <span style="font-family:'Orbitron',monospace;font-size:1.3rem;font-weight:900;
               color:#2d3f8a;letter-spacing:0.04em;">需求定义</span>
  <span style="font-family:'Share Tech Mono',monospace;font-size:0.75rem;
               color:#7c8fc2;letter-spacing:0.03em;">
    输入一句话功能描述，由 HEED-Turbo-Factory 自动拆解为结构化需求，并支持手动校准。
  </span>
</div>
""")

    # 用户输入区
    user_input = st.text_area(
        "功能描述",
        placeholder="例：开发一个 UDS 诊断报文解析库，支持读取 DID、安全访问和否定响应解码",
        height=100,
        key="req_input",
    )

    _btn_col, _warn_col = st.columns([1, 3])
    with _btn_col:
        analyze_btn = st.button(
            "AI 拆解需求",
            type="primary",
            disabled=not api_key,
            use_container_width=True,
        )
    with _warn_col:
        if not api_key:
            st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;letter-spacing:0.03em;">请先在 API Key 配置区输入 Gemini API Key</span>')

    # 调用 Gemini 拆解需求
    if analyze_btn and user_input.strip():
        with st.spinner("HEED-Turbo-Factory 正在分析需求..."):
            model = get_gemini_client(api_key, probe=True)
            if model:
                prompt = REQ_PROMPT_TEMPLATE.format(user_input=user_input.strip())
                raw = call_gemini(model, prompt, json_mode=True)
                if raw:
                    json_str = extract_json_block(raw)
                    try:
                        reqs = json.loads(json_str)
                        st.session_state["requirements"] = reqs
                        # 持久化到文件
                        REQ_JSON_PATH.write_text(
                            json.dumps(reqs, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        st.success(f"已生成 {len(reqs)} 条需求，请在下方校准后保存。")
                    except json.JSONDecodeError as e:
                        st.error(f"JSON 解析失败：{e}")
                        with st.expander("原始响应"):
                            st.code(raw)

    # 从文件加载（仅当输入框有内容时才恢复）
    if user_input.strip() and not st.session_state["requirements"] and REQ_JSON_PATH.exists():
        try:
            loaded = json.loads(REQ_JSON_PATH.read_text(encoding="utf-8"))
            st.session_state["requirements"] = [
                r for r in loaded if r.get("id") and str(r.get("id")) not in ("nan", "None", "")
            ]
        except Exception:
            pass

    # 可编辑需求表格：输入框为空时不显示
    if st.session_state["requirements"] and user_input.strip():
        st.subheader("需求校准")
        st.caption("可直接在表格中修改 ID、标题、描述和优先级，完成后点击「保存校准结果」。")

        df = pd.DataFrame(st.session_state["requirements"])
        # 确保列顺序固定
        for col in ["id", "title", "description", "priority"]:
            if col not in df.columns:
                df[col] = ""
        df = df[["id", "title", "description", "priority"]]

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.TextColumn("需求 ID", width="small"),
                "title": st.column_config.TextColumn("标题", width="medium"),
                "description": st.column_config.TextColumn("详细描述", width="large"),
                "priority": st.column_config.SelectboxColumn(
                    "优先级",
                    options=["High", "Medium", "Low"],
                    width="medium",
                ),
            },
            key="req_editor",
        )

        save_col, dl_col = st.columns([1, 1])
        with save_col:
            if st.button("保存校准结果", type="primary"):
                calibrated = [
                    r for r in edited_df.to_dict(orient="records")
                    if r.get("id") and str(r.get("id")) not in ("nan", "None", "")
                ]
                st.session_state["requirements"] = calibrated
                REQ_JSON_PATH.write_text(
                    json.dumps(calibrated, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                st.success(f"已保存 {len(calibrated)} 条需求至 {REQ_JSON_PATH}")

        with dl_col:
            st.download_button(
                label="下载需求 JSON",
                data=json.dumps(st.session_state["requirements"], ensure_ascii=False, indent=2),
                file_name="requirements.json",
                mime="application/json",
            )

        # 需求统计卡片
        st.divider()
        total = len(st.session_state["requirements"])
        pri_counts = pd.Series(
            [r.get("priority", "Unknown") for r in st.session_state["requirements"]]
        ).value_counts()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("总需求数", total)
        m2.metric("High", pri_counts.get("High", 0))
        m3.metric("Medium", pri_counts.get("Medium", 0))
        m4.metric("Low", pri_counts.get("Low", 0))

    elif not analyze_btn:
        st.info("请输入功能描述并点击「AI 拆解需求」开始分析。")

# ── Tab 2：代码生成 ───────────────────────────────────────────────────────────

CODE_PROMPT_TEMPLATE = textwrap.dedent("""
    你是一名 Python 高级工程师。请根据以下软件需求列表，生成对应的 Python 核心模块代码。

    规范：
    1. 每条需求对应一个或多个函数，函数 docstring 中注明需求 ID（如 REQ-001）
    2. 代码须有类型注解，结构清晰，包含必要的注释
    3. 只输出 Python 代码块，不要任何额外说明

    需求列表（JSON）：
    {requirements_json}
""").strip()


def tab_code_generation(claude_key: str):
    st.html("""
<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:12px;">
  <span style="font-family:'Orbitron',monospace;font-size:1.3rem;font-weight:900;
               color:#2d3f8a;letter-spacing:0.04em;">代码生成</span>
  <span style="font-family:'Share Tech Mono',monospace;font-size:0.75rem;
               color:#7c8fc2;letter-spacing:0.03em;">
    根据校准后的需求，由 HEED-Turbo-Factory 自动生成 Python 核心模块。
  </span>
</div>
""")

    if not st.session_state["requirements"]:
        st.warning("请先在「需求定义」Tab 完成需求分析并保存。")
        return

    # ── 需求选择 ──
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">SELECT REQUIREMENTS</span>')
    all_reqs = st.session_state["requirements"]
    req_options = {f"{r['id']} · {r['title']}": r for r in all_reqs}
    selected_labels = st.multiselect(
        "选择要开发的需求",
        options=list(req_options.keys()),
        default=list(req_options.keys()),
        label_visibility="collapsed",
    )
    selected_reqs = [req_options[l] for l in selected_labels]

    if selected_reqs:
        df = pd.DataFrame(selected_reqs)[["id", "title", "priority"]]
        st.dataframe(df, hide_index=True, use_container_width=True)

    st.divider()

    # ── 工程名 + 生成代码命令 ──
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">GENERATE CODE COMMAND · HEED-TURBO-FACTORY</span>')
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.72rem;color:#7c8fc2;">由 HEED-Turbo-Factory 生成可直接粘贴到 Codespace 终端的开发引导命令</span>')

    # 工程名 + 生成按钮同行
    _pn_col, _btn_col, _warn_col = st.columns([3, 1, 2])
    with _pn_col:
        project_name_raw = st.text_input(
            "PROJECT NAME",
            value=st.session_state.get("project_name_val", "heed-dev-project"),
            help="工程名称（英文），支持修改。空格会自动转为连字符。",
            key="project_name",
        )
        # 自动清理：小写 + 空格/下划线转连字符 + 去除非法字符
        project_name = re.sub(r"[^a-z0-9\-]", "",
                              project_name_raw.strip().lower().replace(" ", "-").replace("_", "-"))
        project_name = project_name or "heed-dev-project"
        st.session_state["project_name_val"] = project_name_raw
        if project_name != project_name_raw.strip():
            st.html(f'<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.68rem;color:#6378dc;">自动规范化为：<b>{project_name}</b></span>')

    gemini_key_gc = st.session_state.get("k_gemini", "")
    with _btn_col:
        st.markdown("<div style='padding-top:26px'></div>", unsafe_allow_html=True)
        gen_btn = st.button("生成代码", type="primary",
                            disabled=not (gemini_key_gc and selected_reqs),
                            use_container_width=True)
    with _warn_col:
        st.markdown("<div style='padding-top:30px'></div>", unsafe_allow_html=True)
        if not gemini_key_gc:
            st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请先在 API Key 配置区输入 Gemini API Key</span>')
        elif not selected_reqs:
            st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请先选择至少一条需求</span>')

    if gen_btn and gemini_key_gc and selected_reqs:
        proj = project_name.strip() or "heed-dev-project"
        reqs_text = "\n".join(
            f"- {r['id']}: {r['title']} — {r.get('description', '')}"
            for r in selected_reqs
        )
        proj_dir = f"/workspaces/UDS-agent-tool/{proj}"
        cmd_prompt = textwrap.dedent(f"""
            你是一名资深 AI 工程师，熟悉 Claude Code CLI（命令行工具）。
            请根据以下软件需求，生成一段可以直接粘贴到终端运行的 Claude Code 命令。

            要求：
            1. 命令以 `claude` 开头，使用双引号包裹 prompt 内容
            2. prompt 中必须包含：
               - 工程名称：{proj}
               - 每条需求的 ID、标题和详细描述
               - 要求基于 Streamlit 构建有页面展示的 Web 工程，代码含类型注解和 docstring
               - 要求在 web_app.py 中提供 Streamlit 页面入口，实现完整 UI 交互界面
               - 要求将所有代码保存到 {proj_dir}/ 目录下合理的文件结构中
            3. prompt 使用中文，简洁专业
            4. 只输出命令本身，不要任何额外解释

            需求列表：
            {reqs_text}
        """).strip()

        with st.spinner("HEED-Turbo-Factory 正在生成开发命令…"):
            client = get_gemini_client(gemini_key_gc)
            if client:
                result = call_gemini(client, cmd_prompt)
                if result:
                    m = re.search(r"```(?:bash|shell)?\s*([\s\S]+?)```", result)
                    cmd_text = m.group(1).strip() if m else result.strip()
                    st.session_state["claude_cmd"] = cmd_text

    if st.session_state.get("claude_cmd"):
        st.html('<div style="height:8px"></div>')
        st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#3b5bdb;font-weight:600;">▶ 复制下方命令，粘贴到 Codespace 终端执行：</span>')
        display_cmd = st.session_state["claude_cmd"].replace("claude ", "heed-turbo-factory ", 1)
        st.code(display_cmd, language="bash")
        st.download_button(
            "下载命令文件",
            data=display_cmd,
            file_name="heed_turbo_factory_cmd.sh",
            mime="text/plain",
        )

# ── Tab 3：测试验证 ───────────────────────────────────────────────────────────

TEST_OUTLINE_PROMPT = textwrap.dedent("""
    你是一名测试架构师。请根据以下需求列表，生成测试大纲（Markdown 格式）。

    每条需求至少包含：
    - 正向测试用例
    - 边界条件测试
    - 异常/错误路径测试

    需求列表（JSON）：
    {requirements_json}
""").strip()

TEST_CODE_PROMPT = textwrap.dedent("""
    你是一名 Python 测试工程师。请根据以下需求和对应的实现代码，生成 pytest 测试文件。

    规范：
    1. 每个测试函数的命名格式：test_<需求ID小写>_<简短描述>，例如 test_req001_parse_did
    2. 使用 pytest，可使用 pytest.mark.parametrize
    3. 如被测函数需要 import，请从 generated_code 模块导入
    4. 只输出 Python 代码块

    需求列表（JSON）：
    {requirements_json}

    实现代码：
    ```python
    {generated_code}
    ```
""").strip()


def _parse_outline_items(outline: str) -> list[str]:
    """从 Markdown 大纲中提取可选测试条目（标题行 + 列表项）。"""
    items = []
    for line in outline.splitlines():
        line = line.strip()
        if re.match(r"^#{1,4}\s+", line):
            items.append(re.sub(r"^#{1,4}\s+", "", line).strip())
        elif re.match(r"^[-*]\s+", line) and len(line) > 4:
            items.append(re.sub(r"^[-*]\s+", "", line).strip())
    return [i for i in items if i]


def tab_testing(api_key: str, claude_key: str):
    st.html("""
<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:12px;">
  <span style="font-family:'Orbitron',monospace;font-size:1.3rem;font-weight:900;
               color:#2d3f8a;letter-spacing:0.04em;">测试验证</span>
  <span style="font-family:'Share Tech Mono',monospace;font-size:0.75rem;
               color:#7c8fc2;letter-spacing:0.03em;">
    生成测试大纲，选择条目，引导 HEED-Turbo-Factory 完成测试并生成报告。
  </span>
</div>
""")

    if not st.session_state["requirements"]:
        st.warning("请先完成「需求定义」阶段。")
        return

    # ══════════════════════════════════════════
    # 阶段 A：生成测试大纲
    # ══════════════════════════════════════════
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">STAGE A · TEST OUTLINE</span>')

    _a_btn_col, _a_warn_col = st.columns([1, 3])
    with _a_btn_col:
        outline_btn = st.button("生成测试大纲", type="primary",
                                disabled=not api_key, use_container_width=True)
    with _a_warn_col:
        if not api_key:
            st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请先在 API Key 配置区输入 Gemini API Key</span>')

    if outline_btn and api_key:
        with st.spinner("HEED-Turbo-Factory 正在生成测试大纲…"):
            model = get_gemini_client(api_key)
            if model:
                prompt = TEST_OUTLINE_PROMPT.format(
                    requirements_json=json.dumps(
                        st.session_state["requirements"], ensure_ascii=False, indent=2
                    )
                )
                outline = call_gemini(model, prompt)
                if outline:
                    st.session_state["test_outline"] = outline
                    TEST_OUTLINE_PATH.write_text(outline, encoding="utf-8")
                    st.success("测试大纲已生成，请在下方选择测试条目。")

    if st.session_state["test_outline"]:
        with st.expander("查看完整测试大纲", expanded=False):
            st.markdown(st.session_state["test_outline"])
        st.download_button(
            "下载测试大纲 (Markdown)",
            data=st.session_state["test_outline"],
            file_name="test_outline.md",
            mime="text/markdown",
            key="dl_outline",
        )

    st.divider()

    # ══════════════════════════════════════════
    # 阶段 B：选择测试条目 → 生成 Claude Code 引导命令
    # ══════════════════════════════════════════
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">STAGE B · GENERATE TEST COMMAND</span>')

    if not st.session_state["test_outline"]:
        st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请先完成阶段 A，生成测试大纲。</span>')
    else:
        # ── 自动读取代码生成 Tab 的工程名 ──
        proj_name = re.sub(
            r"[^a-z0-9\-]", "",
            st.session_state.get("project_name_val", "heed-dev-project")
                .strip().lower().replace(" ", "-").replace("_", "-")
        ) or "heed-dev-project"
        proj_dir = f"/workspaces/UDS-agent-tool/{proj_name}"
        report_path = str(TEST_REPORT_PATH)

        st.html(
            f'<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;'
            f'color:#3b5bdb;">📁 目标工程：<b>{proj_name}</b> &nbsp;|&nbsp; '
            f'路径：<code>{proj_dir}</code></span>'
        )

        outline_items = _parse_outline_items(st.session_state["test_outline"])

        # ── 为每条条目分配 TC-ID ──
        tc_items = [
            {"tc_id": f"TC-{str(i+1).zfill(3)}", "desc": item}
            for i, item in enumerate(outline_items)
        ]

        # 展示带 ID 的条目供用户选择
        tc_options = {f"[{t['tc_id']}] {t['desc']}": t for t in tc_items}
        selected_labels = st.multiselect(
            "选择要纳入测试的条目",
            options=list(tc_options.keys()),
            default=list(tc_options.keys()),
            label_visibility="collapsed",
            key="selected_test_items",
        )
        selected_tc = [tc_options[l] for l in selected_labels]

        gemini_key = st.session_state.get("k_gemini", "")
        _b_btn_col, _b_warn_col = st.columns([1, 3])
        with _b_btn_col:
            test_cmd_btn = st.button(
                "生成测试命令", type="primary",
                disabled=not (gemini_key and selected_tc),
                use_container_width=True,
            )
        with _b_warn_col:
            if not gemini_key:
                st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请先在 API Key 配置区输入 Gemini API Key</span>')
            elif not selected_tc:
                st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#7c8fc2;">请至少选择一个测试条目</span>')

        if test_cmd_btn and gemini_key and selected_tc:
            # 生成带 TC-ID 的测试条目文本
            items_text = "\n".join(
                f"- {t['tc_id']}: {t['desc']}" for t in selected_tc
            )
            cmd_prompt = textwrap.dedent(f"""
                你是一名资深 AI 工程师，熟悉 Claude Code CLI 工具。
                请根据以下测试条目，生成一段可直接粘贴到终端运行的 claude 命令。

                要求：
                1. 命令以 `claude` 开头，双引号包裹 prompt
                2. prompt 中要求 Claude 完成以下全部步骤：
                   a. 读取工程目录 {proj_dir}/ 下的源代码，理解实现逻辑
                   b. 为每条测试条目编写 pytest 测试函数，函数命名格式：
                      test_<TC_ID小写无连字符>_<简短描述>，例如 test_tc001_valid_input
                   c. 每条测试条目的 TC-ID 必须体现在函数名和 docstring 中
                   d. 包含参数化用例（pytest.mark.parametrize）、边界值和异常路径
                   e. 将测试文件保存到 {proj_dir}/test_generated.py
                   f. 在 {proj_dir}/ 目录下执行 pytest test_generated.py -v
                   g. 将 pytest 完整输出保存到 {report_path}
                3. prompt 使用中文，专业简洁
                4. 只输出命令本身，不要任何额外说明

                测试条目（含 TC-ID）：
                {items_text}

                需求背景（JSON）：
                {json.dumps(st.session_state["requirements"], ensure_ascii=False, indent=2)}
            """).strip()

            with st.spinner("HEED-Turbo-Factory 正在生成测试命令…"):
                client = get_gemini_client(gemini_key)
                if client:
                    result = call_gemini(client, cmd_prompt)
                    if result:
                        m = re.search(r"```(?:bash|shell)?\s*([\s\S]+?)```", result)
                        cmd_text = m.group(1).strip() if m else result.strip()
                        st.session_state["test_cmd"] = cmd_text

        if st.session_state.get("test_cmd"):
            st.html('<div style="height:6px"></div>')
            st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.75rem;color:#3b5bdb;font-weight:600;">▶ 复制下方命令，粘贴到 Codespace 终端执行：</span>')
            display_cmd = st.session_state["test_cmd"].replace("claude ", "heed-turbo-factory ", 1)
            st.code(display_cmd, language="bash")
            st.download_button(
                "下载测试命令",
                data=display_cmd,
                file_name="heed_test_cmd.sh",
                mime="text/plain",
                key="dl_test_cmd",
            )

    st.divider()

    # ══════════════════════════════════════════
    # 阶段 C：导入 & 展示测试报告
    # ══════════════════════════════════════════
    st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">STAGE C · TEST REPORT</span>')

    _c1, _c2 = st.columns([1, 3])
    with _c1:
        import_btn = st.button("导入测试报告", type="primary", use_container_width=True)
    with _c2:
        st.html(f'<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.72rem;color:#7c8fc2;">从 {TEST_REPORT_PATH} 读取 HEED-Turbo-Factory 执行后生成的报告</span>')

    if import_btn:
        if TEST_REPORT_PATH.exists():
            report = TEST_REPORT_PATH.read_text(encoding="utf-8")
            st.session_state["test_report"] = report
            st.success("测试报告已导入。")
        else:
            st.warning(f"未找到报告文件：{TEST_REPORT_PATH}，请先在终端执行测试命令。")

    # 上传报告
    uploaded = st.file_uploader("或手动上传测试报告文件", type=["txt", "log"],
                                label_visibility="collapsed", key="upload_report")
    if uploaded:
        report = uploaded.read().decode("utf-8")
        st.session_state["test_report"] = report
        TEST_REPORT_PATH.write_text(report, encoding="utf-8")
        st.success("报告已上传并加载。")

    if st.session_state["test_report"]:
        passed = st.session_state["test_report"].count(" PASSED")
        failed = st.session_state["test_report"].count(" FAILED")
        error  = st.session_state["test_report"].count(" ERROR")

        m1, m2, m3 = st.columns(3)
        m1.metric("✅ 通过", passed)
        m2.metric("❌ 失败", failed)
        m3.metric("⚠️ 错误", error)

        with st.expander("完整测试报告", expanded=True):
            st.code(st.session_state["test_report"], language="text")

        st.download_button(
            "下载测试报告",
            data=st.session_state["test_report"],
            file_name="test_report.txt",
            mime="text/plain",
            key="dl_report",
        )

# ── Tab 4：追溯矩阵 ───────────────────────────────────────────────────────────

def _extract_test_statuses(report: str) -> dict[str, str]:
    """从 pytest 报告中提取所有 test_* 函数的状态。
    同时尝试将函数名反解出 REQ-ID，支持 test_req001 / test_req_001 / test_001 等命名风格。
    """
    statuses: dict[str, str] = {}
    for line in report.splitlines():
        # 匹配任意 test_ 函数名，兼容 pytest -v 输出（含路径前缀和百分比后缀）
        m = re.search(r"(test_\w+)\s+(PASSED|FAILED|ERROR)", line, re.IGNORECASE)
        if m:
            func_name = m.group(1)
            status = m.group(2).upper()
            statuses[func_name] = status
            # 尝试从函数名中提取 REQ-ID（支持 req001 / req_001 / req-001）
            rid_match = re.search(r"(?:req[-_]?)(\d+)", func_name, re.IGNORECASE)
            if rid_match:
                raw_id = "REQ-" + rid_match.group(1).zfill(3)
                statuses.setdefault(raw_id, status)
    return statuses


def _build_mermaid(trace_rows: list[dict]) -> str:
    """生成追溯矩阵 Mermaid 流程图。"""
    lines = ["flowchart LR"]
    lines.append("    REQ([需求]) --> CODE([代码]) --> TEST([测试])")
    lines.append("")
    for row in trace_rows:
        raw_req_id = str(row.get("req_id") or "UNKNOWN").strip()
        if not raw_req_id or raw_req_id in ("nan", "None"):
            raw_req_id = "UNKNOWN"
        req_id = raw_req_id.replace("-", "_")
        func_raw = str(row.get("function") or "no_test").strip()
        if not func_raw or func_raw in ("nan", "None", "—"):
            func_raw = "no_test"
        func = func_raw.replace(".", "_")
        status = row.get("status", "未测试")
        color = "#90EE90" if status == "PASSED" else ("#FFB6C1" if status == "FAILED" else "#D3D3D3")
        lines.append(f'    {req_id}["{raw_req_id}\\n{row.get("title","")}"]')
        lines.append(f'    {req_id} --> {func}["{func}\\n{status}"]')
        lines.append(f'    style {func} fill:{color}')
    return "\n".join(lines)


def tab_traceability():
    st.html("""
<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:12px;">
  <span style="font-family:'Orbitron',monospace;font-size:1.3rem;font-weight:900;
               color:#2d3f8a;letter-spacing:0.04em;">追溯矩阵</span>
  <span style="font-family:'Share Tech Mono',monospace;font-size:0.75rem;
               color:#7c8fc2;letter-spacing:0.03em;">
    自动关联需求 ID、函数名与测试状态，生成可视化追溯图。
  </span>
</div>
""")

    # ── 自动从文件恢复需求（session 刷新后也能正常工作）──────────────────────
    if not st.session_state["requirements"] and REQ_JSON_PATH.exists():
        try:
            loaded = json.loads(REQ_JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                st.session_state["requirements"] = loaded
                st.info("已从保存的需求文件自动恢复需求列表。")
        except Exception:
            pass

    if not st.session_state["requirements"]:
        st.warning("未找到需求数据，请先完成「需求定义」阶段或确保 output/requirements.json 存在。")
        return

    # ── 测试报告：可在本 Tab 直接上传，无需跳回 Tab 3 ────────────────────────
    if not st.session_state["test_report"]:
        st.html('<span style="font-family:\'Share Tech Mono\',monospace;font-size:0.8rem;color:#2d3f8a;font-weight:700;letter-spacing:0.06em;">UPLOAD TEST REPORT</span>')
        _r1, _r2 = st.columns([1, 3])
        with _r1:
            if st.button("导入测试报告", type="primary", use_container_width=True, key="trc_import_btn"):
                if TEST_REPORT_PATH.exists():
                    st.session_state["test_report"] = TEST_REPORT_PATH.read_text(encoding="utf-8")
                    st.success("测试报告已导入。")
                    st.rerun()
                else:
                    st.warning("未找到报告文件，请手动上传。")
        with _r2:
            up = st.file_uploader("上传测试报告", type=["txt", "log"],
                                  label_visibility="collapsed", key="trc_upload_report")
            if up:
                report = up.read().decode("utf-8")
                st.session_state["test_report"] = report
                TEST_REPORT_PATH.write_text(report, encoding="utf-8")
                st.success("报告已上传并加载。")
                st.rerun()

    statuses = (
        _extract_test_statuses(st.session_state["test_report"])
        if st.session_state["test_report"]
        else {}
    )

    if not statuses and st.session_state["test_report"]:
        st.warning("测试报告中未能解析出测试函数状态，请确认报告为 pytest -v 的输出格式（含 PASSED/FAILED/ERROR）。")

    # 构建追溯行
    trace_rows = []
    for req in st.session_state["requirements"]:
        req_id = req.get("id", "")
        # 提取 REQ-ID 中的数字部分，用于宽松匹配（兼容 req001 / req_001 / req-001）
        rid_digits = re.sub(r"\D", "", req_id).lstrip("0") or "0"
        matched_funcs = [
            k for k in statuses
            if re.search(rf"(?:req[-_]?)0*{re.escape(rid_digits)}(?:\D|$)", k, re.IGNORECASE)
        ]
        if matched_funcs:
            for func in matched_funcs:
                trace_rows.append({
                    "req_id": req_id,
                    "title": req.get("title", ""),
                    "priority": req.get("priority", ""),
                    "function": func,
                    "status": statuses[func],
                })
        else:
            trace_rows.append({
                "req_id": req_id,
                "title": req.get("title", ""),
                "priority": req.get("priority", ""),
                "function": "—",
                "status": "未测试",
            })

    st.session_state["trace_data"] = trace_rows

    # 追溯表格
    st.subheader("追溯表")
    df = pd.DataFrame(trace_rows)
    # 添加状态颜色
    def color_status(val):
        if val == "PASSED":
            return "background-color: #d4edda; color: #155724"
        if val == "FAILED":
            return "background-color: #f8d7da; color: #721c24"
        return "background-color: #e2e3e5; color: #383d41"

    st.dataframe(
        df.style.map(color_status, subset=["status"]),
        use_container_width=True,
        hide_index=True,
    )

    # Mermaid 流程图
    st.subheader("追溯流程图（Mermaid）")
    mermaid_code = _build_mermaid(trace_rows)
    with st.expander("查看 Mermaid 源码"):
        st.code(mermaid_code, language="text")

    # 用 st.markdown + HTML 渲染 Mermaid
    mermaid_html = f"""
    <div class="mermaid">
    {mermaid_code}
    </div>
    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      mermaid.initialize({{ startOnLoad: true }});
    </script>
    """
    st.components.v1.html(mermaid_html, height=max(300, len(trace_rows) * 60 + 100), scrolling=True)

    # 下载追溯矩阵 CSV
    st.download_button(
        "下载追溯矩阵 CSV",
        data=df.to_csv(index=False),
        file_name="traceability_matrix.csv",
        mime="text/csv",
    )

# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="NSR-HEED 极速智造工厂",
        page_icon="🏭",
        layout="wide",
    )
    _init_state()

    # ── 科技感顶部标识 Banner（全页宽固定置顶）──
    st.html("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&family=Noto+Sans+SC:wght@300;400&display=swap');

/* 隐藏 Streamlit 默认顶栏，腾出空间 */
header[data-testid="stHeader"] { display: none !important; }

/* 隐藏侧边栏 */
section[data-testid="stSidebar"] { display: none !important; }

/* 整体页面向下偏移，紧贴 Banner 底部 */
.stApp { margin-top: 92px !important; }
.main .block-container,
[data-testid="stMainBlockContainer"],
[data-testid="stAppViewBlockContainer"] {
    padding-top: 0 !important;
    margin-top: 0 !important;
    padding-bottom: 1rem !important;
}

/* ── 全局页面背景：浅色科技感 ── */
html, body,
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section.main {
    background: linear-gradient(160deg, #f0f5ff 0%, #f7f3ff 35%, #edf8ff 65%, #f0faf5 100%) !important;
    background-attachment: fixed !important;
}
/* 细网格底纹 */
[data-testid="stAppViewContainer"]::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(99,120,220,0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(99,120,220,0.045) 1px, transparent 1px);
    background-size: 32px 32px;
    pointer-events: none;
    z-index: 0;
}

/* ── API Key 配置区：与 Banner 同色系 ── */
[data-testid="stExpander"] {
    background: linear-gradient(135deg, #f0f6ff 0%, #e8f0fe 50%, #f5f0ff 100%) !important;
    border: 1px solid #c7d9f8 !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 10px rgba(99,120,220,0.09) !important;
    margin-bottom: 0.5rem !important;
    position: relative;
    overflow: hidden;
}
/* 扩展区顶部扫光条 */
[data-testid="stExpander"]::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, #6378dc66, #ae3ec966, #6378dc66, transparent);
}
/* 折叠标题行 */
[data-testid="stExpander"] summary,
[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {
    color: #3b5bdb !important;
}
[data-testid="stExpander"] > details > summary {
    background: transparent !important;
    border-bottom: 1px solid #dce8fb;
    padding: 10px 16px !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.04em;
    color: #3b5bdb !important;
}
[data-testid="stExpander"] > details > summary:hover {
    background: rgba(99,120,220,0.05) !important;
}
/* 内容区 */
[data-testid="stExpander"] > details > div {
    background: transparent !important;
    padding: 14px 20px 16px !important;
}
/* 小节标题（国际 / 中国） */
[data-testid="stExpander"] h5 {
    font-family: 'Share Tech Mono', monospace !important;
    color: #4a5fa8 !important;
    font-size: 0.8rem !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 10px 0 6px !important;
    border-left: 3px solid #6378dc;
    padding-left: 8px;
}
/* 模型标签（bold markdown） */
[data-testid="stExpander"] strong { color: #2d3f8a; }
/* caption */
[data-testid="stExpander"] [data-testid="stCaptionContainer"] p {
    color: #7c8fc2 !important;
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.7rem !important;
}
/* success / info 消息压缩 */
[data-testid="stExpander"] [data-testid="stAlert"] {
    padding: 4px 10px !important;
    font-size: 0.72rem !important;
}

.heed-banner {
    background: linear-gradient(135deg, #f0f6ff 0%, #e8f0fe 40%, #f5f0ff 70%, #f0f6ff 100%);
    border-bottom: 1px solid #c7d9f8;
    box-shadow: 0 2px 12px rgba(99,120,220,0.10);
    padding: 18px 48px;
    position: fixed;
    top: 0; left: 0; right: 0;
    z-index: 999999;
    overflow: hidden;
}
.heed-banner::before {
    content: '';
    position: absolute;
    top: 0; left: -60%;
    width: 50%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(99,120,220,0.07), transparent);
    animation: scan 5s linear infinite;
}
@keyframes scan {
    0%   { left: -60%; }
    100% { left: 120%; }
}
.heed-banner::after {
    content: '';
    position: absolute;
    inset: 0;
    background:
        radial-gradient(ellipse 55% 80% at 5% 50%, rgba(139,170,255,0.12) 0%, transparent 70%),
        radial-gradient(ellipse 40% 80% at 95% 30%, rgba(180,140,255,0.10) 0%, transparent 70%);
    pointer-events: none;
}
.heed-grid-overlay {
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(99,120,220,0.05) 1px, transparent 1px),
        linear-gradient(90deg, rgba(99,120,220,0.05) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
}
.heed-corner {
    position: absolute;
    width: 16px; height: 16px;
    border-color: #6378dc;
    border-style: solid;
    opacity: 0.5;
}
.heed-corner.tl { top: 10px; left: 10px;  border-width: 2px 0 0 2px; }
.heed-corner.tr { top: 10px; right: 10px; border-width: 2px 2px 0 0; }
.heed-corner.bl { bottom: 10px; left: 10px;  border-width: 0 0 2px 2px; }
.heed-corner.br { bottom: 10px; right: 10px; border-width: 0 2px 2px 0; }

.heed-inner {
    display: flex;
    align-items: center;
    gap: 24px;
    max-width: 1800px;
    margin: 0 auto;
}
.heed-logo-icon {
    font-size: 38px;
    filter: drop-shadow(0 2px 6px rgba(99,120,220,0.25));
    flex-shrink: 0;
}
.heed-brand {
    flex-shrink: 0;
    border-right: 1px solid #b8caf5;
    padding-right: 24px;
    margin-right: 4px;
}
.heed-title {
    font-family: 'Orbitron', monospace;
    font-size: 1.35rem;
    font-weight: 900;
    letter-spacing: 0.1em;
    background: linear-gradient(90deg, #3b5bdb 0%, #6741d9 40%, #ae3ec9 80%, #3b5bdb 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: shine 6s linear infinite;
    white-space: nowrap;
}
.heed-subtitle-cn {
    font-family: 'Noto Sans SC', sans-serif;
    font-size: 0.72rem;
    font-weight: 400;
    color: #7c8fc2;
    letter-spacing: 0.06em;
    margin-top: 2px;
    white-space: nowrap;
}
@keyframes shine {
    0%   { background-position: 0% center; }
    100% { background-position: 200% center; }
}
.heed-taglines {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
}
.heed-tag {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem;
    white-space: normal;
    overflow: visible;
    color: #3d4f8a;
    letter-spacing: 0.02em;
    line-height: 1.4;
}
.heed-badges {
    display: flex;
    flex-direction: column;
    gap: 5px;
    flex-shrink: 0;
    align-items: flex-end;
}
.heed-badge-row { display: flex; gap: 6px; }
.heed-badge {
    font-family: 'Share Tech Mono', monospace;
    font-size: 0.62rem;
    padding: 2px 9px;
    border-radius: 20px;
    letter-spacing: 0.05em;
    border: 1px solid;
    white-space: nowrap;
}
.badge-ai    { color: #1d6fa4; border-color: #93c5e8; background: #e8f4fc; }
.badge-aise  { color: #6741d9; border-color: #c4b0f5; background: #f3efff; }
.badge-auto  { color: #0f766e; border-color: #86d9d1; background: #e8f9f7; }
.badge-gemini{ color: #b45309; border-color: #fcd09a; background: #fef6ec; }
.badge-claude   { color: #166534; border-color: #86efac; background: #f0fdf4; }
.badge-deepseek { color: #9a3412; border-color: #fdba74; background: #fff7ed; }
.badge-qwen     { color: #86198f; border-color: #e879f9; background: #fdf4ff; }

/* ══════════════════════════════════════════
   Tab 科技感样式 v2
══════════════════════════════════════════ */

/* Tab 整体包裹 */
[data-testid="stTabs"] {
    margin-top: 6px;
    filter: drop-shadow(0 4px 24px rgba(99,120,220,0.10));
}

/* Tab 标签栏底层轨道 */
[data-testid="stTabs"] > div:first-child {
    background: linear-gradient(90deg,
        rgba(220,232,251,0.85) 0%,
        rgba(232,224,255,0.80) 50%,
        rgba(220,232,251,0.85) 100%) !important;
    border-radius: 12px 12px 0 0 !important;
    border: 1px solid #b8caf5 !important;
    border-bottom: 2px solid #3b5bdb44 !important;
    padding: 8px 12px 0 12px !important;
    gap: 3px !important;
    backdrop-filter: blur(12px);
    position: relative;
}

/* 标签栏顶部扫光线 */
[data-testid="stTabs"] > div:first-child::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%, #6378dc88 30%, #ae3ec988 60%, transparent 100%);
}

/* 单个 Tab 按钮 */
[data-testid="stTabs"] button[role="tab"] {
    font-family: 'Share Tech Mono', monospace !important;
    font-size: 0.8rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.08em !important;
    color: #6878b0 !important;
    background: rgba(255,255,255,0.25) !important;
    border: 1px solid transparent !important;
    border-bottom: none !important;
    border-radius: 8px 8px 0 0 !important;
    padding: 6px 22px !important;
    transition: all 0.18s ease !important;
    position: relative !important;
    text-transform: uppercase !important;
}

/* Tab hover */
[data-testid="stTabs"] button[role="tab"]:hover {
    color: #3b5bdb !important;
    background: rgba(255,255,255,0.55) !important;
    border-color: #c7d9f8 !important;
    box-shadow: 0 -2px 8px rgba(99,120,220,0.12) !important;
}

/* 激活 Tab */
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: #2d3f8a !important;
    background: linear-gradient(180deg,
        rgba(255,255,255,0.98) 0%,
        rgba(240,245,255,0.95) 100%) !important;
    border-color: #b8caf5 !important;
    border-bottom: 2px solid rgba(240,245,255,0.98) !important;
    box-shadow: 0 -3px 12px rgba(59,91,219,0.14), inset 0 1px 0 #fff !important;
}

/* 激活 Tab 顶部彩色光条（动画） */
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]::before {
    content: '';
    position: absolute;
    top: 0; left: 6px; right: 6px;
    height: 2px;
    border-radius: 0 0 2px 2px;
    background: linear-gradient(90deg, #3b5bdb, #6741d9, #ae3ec9, #6741d9, #3b5bdb);
    background-size: 200% auto;
    animation: tab-shine 3s linear infinite;
}
@keyframes tab-shine {
    0%   { background-position: 0% center; }
    100% { background-position: 200% center; }
}

/* 激活 Tab 左右各一个角标 */
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]::after {
    content: '◆';
    position: absolute;
    right: 8px; top: 50%; transform: translateY(-50%);
    font-size: 0.38rem;
    color: #6741d9;
    opacity: 0.6;
}

/* Tab 内容区 */
[data-testid="stTabs"] [role="tabpanel"] {
    background: linear-gradient(150deg,
        rgba(240,245,255,0.94) 0%,
        rgba(243,239,255,0.92) 50%,
        rgba(237,248,255,0.94) 100%) !important;
    border: 1px solid #b8caf5 !important;
    border-top: none !important;
    border-radius: 0 0 14px 14px !important;
    padding: 24px 28px !important;
    backdrop-filter: blur(12px);
    box-shadow:
        0 8px 36px rgba(99,120,220,0.10),
        inset 0 1px 0 rgba(255,255,255,0.6) !important;
    min-height: 320px;
    position: relative;
    overflow: hidden;
}

/* 内容区右下角装饰圆 */
[data-testid="stTabs"] [role="tabpanel"]::after {
    content: '';
    position: absolute;
    bottom: -60px; right: -60px;
    width: 200px; height: 200px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(103,65,217,0.06) 0%, transparent 70%);
    pointer-events: none;
}

/* 内容区顶部左侧彩色短线 */
[data-testid="stTabs"] [role="tabpanel"]::before {
    content: '';
    position: absolute;
    top: 0; left: 28px;
    width: 48px; height: 2px;
    background: linear-gradient(90deg, #3b5bdb, #ae3ec9);
    border-radius: 0 0 2px 2px;
}
</style>

<div class="heed-banner">
  <div class="heed-grid-overlay"></div>
  <div class="heed-corner tl"></div>
  <div class="heed-corner tr"></div>
  <div class="heed-corner bl"></div>
  <div class="heed-corner br"></div>

  <div class="heed-inner">
    <div class="heed-logo-icon">🏭</div>

    <div class="heed-brand">
      <div class="heed-title">NSR-HEED&nbsp;TURBO&nbsp;FACTORY</div>
      <div class="heed-subtitle-cn">极速智造工厂 · AI Software Engineering</div>
    </div>

    <div class="heed-taglines">
      <div class="heed-tag">
        NSR-HEED Turbo Factory: Pioneering a New Era of AISE Automation — One Requirement, One Hour, Full-Lifecycle Delivery.
      </div>
    </div>

    <div class="heed-badges">
      <div class="heed-badge-row">
        <span class="heed-badge badge-ai">AI-POWERED</span>
        <span class="heed-badge badge-aise">AISE</span>
        <span class="heed-badge badge-auto">FULL-LIFECYCLE</span>
      </div>
      <div class="heed-badge-row">
        <span class="heed-badge badge-gemini">⚡ Gemini</span>
        <span class="heed-badge badge-claude">✦ Claude</span>
        <span class="heed-badge badge-deepseek">◈ DeepSeek</span>
        <span class="heed-badge badge-qwen">❋ Qwen3</span>
      </div>
    </div>
  </div>
</div>
""")

    # ── API Key 配置区 ──
    with st.expander("🔑  AI 模型 API Key 配置", expanded=False):
        st.markdown("##### 🌐 国际主流模型")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Google Gemini**")
            st.caption(f"`{GEMINI_MODEL_DEFAULT}`")
            api_key = st.text_input("Gemini Key", type="password",
                placeholder="AIza...", label_visibility="collapsed", key="k_gemini")
            if api_key:
                if st.session_state.get("_verified_key") != api_key:
                    with st.spinner("验证中…"):
                        _cl = get_gemini_client(api_key, probe=True)
                        _models = list_gemini_models(api_key)
                    st.session_state["_verified_key"] = api_key
                    st.session_state["_conn_ok"] = bool(_cl)
                    st.session_state["_gemini_models"] = _models
                if st.session_state.get("_conn_ok"):
                    st.success("连接正常 ✓")
                    _avail = st.session_state.get("_gemini_models", [GEMINI_MODEL_DEFAULT])
                    _default_idx = _avail.index(GEMINI_MODEL_DEFAULT) if GEMINI_MODEL_DEFAULT in _avail else 0
                    _chosen = st.selectbox(
                        "选择模型",
                        options=_avail,
                        index=_default_idx,
                        key="selected_gemini_model",
                        label_visibility="collapsed",
                    )
                else:
                    st.error("连接失败")
        with c2:
            st.markdown("**Anthropic Claude**")
            st.caption(f"`{CLAUDE_MODEL}`")
            claude_key = st.text_input("Claude Key", type="password",
                placeholder="sk-ant-...", label_visibility="collapsed", key="k_claude")
            if claude_key:
                st.success("Key 已输入 ✓")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**OpenAI GPT**")
            st.caption("`gpt-4o / gpt-4.1`")
            openai_key = st.text_input("OpenAI Key", type="password",
                placeholder="sk-...", label_visibility="collapsed", key="k_openai")
            if openai_key:
                st.success("Key 已输入 ✓")
        with c4:
            st.markdown("**Meta Llama**")
            st.caption("`llama-3.3-70b (Groq)`")
            llama_key = st.text_input("Groq Key", type="password",
                placeholder="gsk_...", label_visibility="collapsed", key="k_llama")
            if llama_key:
                st.success("Key 已输入 ✓")

        st.markdown("##### 🇨🇳 中国主流模型")
        d1, d2 = st.columns(2)
        with d1:
            st.markdown("**DeepSeek 深度求索**")
            st.caption("`deepseek-chat / reasoner`")
            deepseek_key = st.text_input("DeepSeek Key", type="password",
                placeholder="sk-...", label_visibility="collapsed", key="k_deepseek")
            if deepseek_key:
                st.success("Key 已输入 ✓")
        with d2:
            st.markdown("**通义千问 Qwen**")
            st.caption("`qwen3-235b-a22b`")
            qwen_key = st.text_input("Qwen Key", type="password",
                placeholder="sk-...", label_visibility="collapsed", key="k_qwen")
            if qwen_key:
                st.success("Key 已输入 ✓")

        d3, d4 = st.columns(2)
        with d3:
            st.markdown("**智谱 GLM**")
            st.caption("`glm-4-plus / glm-z1`")
            glm_key = st.text_input("GLM Key", type="password",
                placeholder="...", label_visibility="collapsed", key="k_glm")
            if glm_key:
                st.success("Key 已输入 ✓")
        with d4:
            st.markdown("**百度文心 ERNIE**")
            st.caption("`ernie-4.5-turbo`")
            ernie_key = st.text_input("ERNIE Key", type="password",
                placeholder="...", label_visibility="collapsed", key="k_ernie")
            if ernie_key:
                st.success("Key 已输入 ✓")

        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Moonshot Kimi**")
            st.caption("`moonshot-v1-128k`")
            kimi_key = st.text_input("Kimi Key", type="password",
                placeholder="sk-...", label_visibility="collapsed", key="k_kimi")
            if kimi_key:
                st.success("Key 已输入 ✓")
        with e2:
            st.markdown("**豆包 Doubao**")
            st.caption("`doubao-pro-256k`")
            doubao_key = st.text_input("Doubao Key", type="password",
                placeholder="...", label_visibility="collapsed", key="k_doubao")
            if doubao_key:
                st.success("Key 已输入 ✓")

        e3, e4 = st.columns(2)
        with e3:
            st.markdown("**腾讯混元 Hunyuan**")
            st.caption("`hunyuan-turbos`")
            hunyuan_key = st.text_input("Hunyuan Key", type="password",
                placeholder="...", label_visibility="collapsed", key="k_hunyuan")
            if hunyuan_key:
                st.success("Key 已输入 ✓")
        with e4:
            st.markdown("**MiniMax**")
            st.caption("`MiniMax-Text-01`")
            minimax_key = st.text_input("MiniMax Key", type="password",
                placeholder="...", label_visibility="collapsed", key="k_minimax")
            if minimax_key:
                st.success("Key 已输入 ✓")

    # ── 流水线状态栏 ──
    stages = [
        ("REQ", "📋", "需求定义",  bool(st.session_state["requirements"])),
        ("GEN", "⚙️", "代码生成",  bool(st.session_state["generated_code"])),
        ("TST", "🧪", "测试验证",  bool(st.session_state["test_report"])),
        ("TRC", "🔗", "追溯矩阵",  bool(st.session_state["trace_data"])),
    ]

    def _stage_html(code, icon, label, done):
        if done:
            border = "#22c55e"
            bg     = "linear-gradient(135deg,#f0fdf4,#dcfce7)"
            badge  = '<span style="background:#22c55e;color:#fff;font-size:0.65rem;padding:2px 8px;border-radius:20px;letter-spacing:.06em;font-family:\'Share Tech Mono\',monospace;">DONE</span>'
            glow   = "box-shadow:0 0 0 1px #bbf7d0,0 2px 8px rgba(34,197,94,.15);"
            ccode  = f'<span style="color:#15803d;font-family:\'Share Tech Mono\',monospace;font-size:0.78rem;letter-spacing:.1em;font-weight:700;">{code}</span>'
        else:
            border = "#93c5fd"
            bg     = "linear-gradient(135deg,#f0f5ff,#e8f0fe)"
            badge  = ''
            glow   = "box-shadow:0 1px 6px rgba(99,120,220,.10);"
            ccode  = f'<span style="color:#6378dc;font-family:\'Share Tech Mono\',monospace;font-size:0.78rem;letter-spacing:.1em;font-weight:700;">{code}</span>'
        return f"""
        <div style="flex:1;min-width:0;background:{bg};border:1px solid {border};border-radius:8px;
                    padding:8px 12px;position:relative;{glow}">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:1.2rem;line-height:1;flex-shrink:0;">{icon}</span>
            <div style="min-width:0;">
              {ccode}
              <div style="font-family:'Noto Sans SC',sans-serif;font-size:0.95rem;
                           color:#1e3a5f;font-weight:700;letter-spacing:.02em;white-space:nowrap;">{label}</div>
            </div>
            {badge}
          </div>
        </div>"""

    def _arrow_html(active):
        color = "#22c55e" if active else "#93c5fd"
        anim  = "animation:pulse-arrow 1.6s ease-in-out infinite;" if active else ""
        return f"""
        <div style="display:flex;align-items:center;padding:0 2px;flex-shrink:0;">
          <svg width="22" height="12" viewBox="0 0 22 12" style="{anim}">
            <defs>
              <marker id="ah{color[1:]}" markerWidth="5" markerHeight="5"
                      refX="4" refY="2.5" orient="auto">
                <path d="M0,0 L5,2.5 L0,5 Z" fill="{color}"/>
              </marker>
            </defs>
            <line x1="1" y1="6" x2="17" y2="6"
                  stroke="{color}" stroke-width="1.5"
                  stroke-dasharray="4,2"
                  marker-end="url(#ah{color[1:]})"/>
          </svg>
        </div>"""

    nodes_html = ""
    for i, (code, icon, label, done) in enumerate(stages):
        nodes_html += _stage_html(code, icon, label, done)
        if i < len(stages) - 1:
            nodes_html += _arrow_html(done)

    # 重置按钮右对齐，独占一行，不挤占流水线
    # 流水线独占完整宽度
    st.html(f"""
<style>
@keyframes pulse-arrow {{
  0%,100% {{ opacity:1; }}
  50%      {{ opacity:.4; }}
}}
</style>
<div style="display:flex;align-items:center;gap:0;margin:0 0 4px 0;
            background:rgba(255,255,255,0.55);border:1px solid #dce8fb;
            border-radius:10px;padding:5px 10px;
            backdrop-filter:blur(8px);
            box-shadow:0 1px 8px rgba(99,120,220,0.07);">
  {nodes_html}
</div>
""")

    # 重置按钮在流水线下方右对齐
    _, _btn_col = st.columns([10, 1])
    with _btn_col:
        st.html("""<style>
div[data-testid="stButton"] button[kind="secondary"] {
    padding: 1px 6px !important;
    font-size: 0.65rem !important;
    height: 22px !important;
    min-height: 0 !important;
    line-height: 1 !important;
    border-radius: 6px !important;
}
</style>""")
        if st.button("↺ 重置", type="secondary", use_container_width=True):
            for key in ["requirements", "generated_code", "test_outline",
                        "test_code", "test_report", "trace_data"]:
                st.session_state[key] = [] if isinstance(
                    st.session_state[key], list) else ""
            st.rerun()

    st.html('<hr style="margin:4px 0 0 0;border:none;border-top:1px solid #dce8fb;">')

    # ── 主界面：四个 Tab ──
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 需求定义", "⚙️ 代码生成", "🧪 测试验证", "🔗 追溯矩阵"]
    )

    with tab1:
        tab_requirements(api_key)

    with tab2:
        tab_code_generation(claude_key)

    with tab3:
        tab_testing(api_key, claude_key)

    with tab4:
        tab_traceability()


if __name__ == "__main__":
    main()
