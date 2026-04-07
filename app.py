from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, List
import csv
import io

app = FastAPI(title="UDS Parser Pro")

OEM_CONFIGS_DIR = Path("oem_configs")
OEM_CONFIGS_DIR.mkdir(exist_ok=True)

# ── UDS Service Registry ──────────────────────────────────────────────────────

UDS_REGISTRY = {
    # Requests
    "10": {"name": "DiagnosticSessionControl",   "cn": "诊断会话控制",   "type": "request"},
    "11": {"name": "ECUReset",                    "cn": "ECU 复位",       "type": "request"},
    "14": {"name": "ClearDiagnosticInformation",  "cn": "清除诊断信息",   "type": "request"},
    "19": {"name": "ReadDTCInformation",          "cn": "读取 DTC 信息",  "type": "request"},
    "22": {"name": "ReadDataByIdentifier",        "cn": "按标识符读数据", "type": "request"},
    "27": {"name": "SecurityAccess",              "cn": "安全访问",       "type": "request"},
    "28": {"name": "CommunicationControl",        "cn": "通信控制",       "type": "request"},
    "2E": {"name": "WriteDataByIdentifier",       "cn": "按标识符写数据", "type": "request"},
    "31": {"name": "RoutineControl",              "cn": "例程控制",       "type": "request"},
    "34": {"name": "RequestDownload",             "cn": "请求下载",       "type": "request"},
    "35": {"name": "RequestUpload",               "cn": "请求上传",       "type": "request"},
    "36": {"name": "TransferData",                "cn": "数据传输",       "type": "request"},
    "37": {"name": "RequestTransferExit",         "cn": "请求传输退出",   "type": "request"},
    "3E": {"name": "TesterPresent",               "cn": "测试仪在线",     "type": "request"},
    "85": {"name": "ControlDTCSetting",           "cn": "DTC 设置控制",   "type": "request"},
    # Positive Responses (request SID + 0x40)
    "50": {"name": "DiagnosticSessionControl",   "cn": "诊断会话控制",   "type": "positive"},
    "51": {"name": "ECUReset",                    "cn": "ECU 复位",       "type": "positive"},
    "54": {"name": "ClearDiagnosticInformation",  "cn": "清除诊断信息",   "type": "positive"},
    "59": {"name": "ReadDTCInformation",          "cn": "读取 DTC 信息",  "type": "positive"},
    "62": {"name": "ReadDataByIdentifier",        "cn": "按标识符读数据", "type": "positive"},
    "67": {"name": "SecurityAccess",              "cn": "安全访问",       "type": "positive"},
    "68": {"name": "CommunicationControl",        "cn": "通信控制",       "type": "positive"},
    "6E": {"name": "WriteDataByIdentifier",       "cn": "按标识符写数据", "type": "positive"},
    "71": {"name": "RoutineControl",              "cn": "例程控制",       "type": "positive"},
    "74": {"name": "RequestDownload",             "cn": "请求下载",       "type": "positive"},
    "75": {"name": "RequestUpload",               "cn": "请求上传",       "type": "positive"},
    "76": {"name": "TransferData",                "cn": "数据传输",       "type": "positive"},
    "77": {"name": "RequestTransferExit",         "cn": "请求传输退出",   "type": "positive"},
    "7E": {"name": "TesterPresent",               "cn": "测试仪在线",     "type": "positive"},
    "C5": {"name": "ControlDTCSetting",           "cn": "DTC 设置控制",   "type": "positive"},
    # Negative Response
    "7F": {"name": "NegativeResponse",            "cn": "否定响应",       "type": "negative"},
}

SESSION_TYPES = {
    "01": "defaultSession（默认会话）",
    "02": "programmingSession（编程会话）",
    "03": "extendedDiagnosticSession（扩展诊断会话）",
    "04": "safetySystemDiagnosticSession（安全系统诊断会话）",
}

RESET_TYPES = {
    "01": "hardReset（硬复位）",
    "02": "keyOffOnReset（断电复位）",
    "03": "softReset（软复位）",
}

COMM_CONTROL_TYPES = {
    "00": "enableRxAndTx（启用收发）",
    "01": "enableRxAndDisableTx（启用接收，禁用发送）",
    "02": "disableRxAndEnableTx（禁用接收，启用发送）",
    "03": "disableRxAndTx（禁用收发）",
}

NRC_MAP = {
    "10": "generalReject（通用拒绝）",
    "11": "serviceNotSupported（服务不支持）",
    "12": "subFunctionNotSupported（子功能不支持）",
    "13": "incorrectMessageLengthOrInvalidFormat（消息长度/格式错误）",
    "14": "responseTooLong（响应过长）",
    "21": "busyRepeatRequest（忙，请重试）",
    "22": "conditionsNotCorrect（条件不满足）",
    "24": "requestSequenceError（请求序列错误）",
    "25": "noResponseFromSubnetComponent（子网组件无响应）",
    "26": "failurePreventsExecution（故障阻止执行）",
    "31": "requestOutOfRange（请求超出范围）",
    "33": "securityAccessDenied（安全访问被拒绝）",
    "35": "invalidKey（无效密钥）",
    "36": "exceededNumberOfAttempts（超过尝试次数）",
    "37": "requiredTimeDelayNotExpired（时间延迟未到期）",
    "70": "uploadDownloadNotAccepted（上传/下载不接受）",
    "71": "transferDataSuspended（数据传输暂停）",
    "72": "generalProgrammingFailure（编程失败）",
    "73": "wrongBlockSequenceCounter（块序列计数错误）",
    "78": "requestCorrectlyReceivedResponsePending（已收到，响应待定）",
    "7E": "subFunctionNotSupportedInActiveSession（当前会话不支持子功能）",
    "7F": "serviceNotSupportedInActiveSession（当前会话不支持服务）",
}

BUILTIN_DID_MAP = {
    "F190": "VIN 码",
    "F188": "ECU 软件版本号",
    "F187": "零件编号",
    "F189": "ECU 软件版本",
    "F191": "ECU 硬件版本号",
    "F18C": "ECU 序列号",
}

# ── OEM Config Helpers ────────────────────────────────────────────────────────

def load_oem_did_map(oem_name: str) -> dict:
    csv_path = OEM_CONFIGS_DIR / f"{oem_name}.csv"
    if not csv_path.exists():
        return {}
    did_map = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            did = row.get("did", "").strip().upper()
            name = row.get("name", "").strip()
            if did and name:
                did_map[did] = name
    return did_map


def get_did_map(oem_name: Optional[str]) -> dict:
    merged = dict(BUILTIN_DID_MAP)
    if oem_name:
        merged.update(load_oem_did_map(oem_name))
    return merged


def count_oem_dids(path: Path) -> int:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return sum(1 for r in csv.DictReader(f) if r.get("did", "").strip())
    except Exception:
        return 0


# ── Parse Models ──────────────────────────────────────────────────────────────

class Segment(BaseModel):
    label: str
    hex_val: str
    meaning: str
    role: str  # sid | subfunction | did | data | nrc | reserved


class ParseRequest(BaseModel):
    data: str
    oem: Optional[str] = None


class ParseResponse(BaseModel):
    raw: str
    service_id: str
    service_name: str
    service_cn: str
    response_type: str   # request | positive | negative | unknown
    segments: List[Segment]
    summary: str
    # Legacy compat
    did: str = ""
    did_name: str = ""
    value_hex: str = ""
    description: str = ""


# ── Segment Builder ───────────────────────────────────────────────────────────

def seg(label: str, hex_val: str, meaning: str, role: str) -> Segment:
    return Segment(label=label, hex_val=hex_val, meaning=meaning, role=role)


# ── Service Parsers ───────────────────────────────────────────────────────────

def parse_10_50(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} DiagnosticSessionControl ({stype})", "sid")]
    session_name = "未知"
    if len(rest) >= 2:
        st = rest[:2]
        session_name = SESSION_TYPES.get(st, f"未知类型 0x{st}")
        segs.append(seg("会话类型", st, session_name, "subfunction"))
    if stype == "positive" and len(rest) >= 10:
        p2 = rest[2:6]
        p2s = rest[6:10]
        segs.append(seg("P2ServerMax", p2, f"{int(p2, 16)} ms", "data"))
        segs.append(seg("P2*ServerMax", p2s, f"{int(p2s, 16) * 10} ms", "data"))
    return segs, f"诊断会话控制 [{stype}]：{session_name}"


def parse_11_51(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} ECUReset ({stype})", "sid")]
    reset_name = "未知"
    if len(rest) >= 2:
        rt = rest[:2]
        reset_name = RESET_TYPES.get(rt, f"未知类型 0x{rt}")
        segs.append(seg("复位类型", rt, reset_name, "subfunction"))
    return segs, f"ECU 复位 [{stype}]：{reset_name}"


def parse_27_67(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} SecurityAccess ({stype})", "sid")]
    access_desc = "未知"
    if len(rest) >= 2:
        at = rest[:2]
        at_val = int(at, 16)
        level = (at_val + 1) // 2 if at_val % 2 == 1 else at_val // 2
        access_desc = f"requestSeed（请求种子，级别 {level}）" if at_val % 2 == 1 else f"sendKey（发送密钥，级别 {level}）"
        segs.append(seg("访问类型", at, access_desc, "subfunction"))
        if len(rest) > 2:
            segs.append(seg("种子/密钥", rest[2:], f"0x{rest[2:]}", "data"))
    return segs, f"安全访问 [{stype}]：{access_desc}"


def parse_28_68(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} CommunicationControl ({stype})", "sid")]
    if len(rest) >= 2:
        ct = rest[:2]
        ct_name = COMM_CONTROL_TYPES.get(ct, f"未知控制类型 0x{ct}")
        segs.append(seg("控制类型", ct, ct_name, "subfunction"))
        if len(rest) >= 4:
            segs.append(seg("通信类型", rest[2:4], f"0x{rest[2:4]}", "data"))
    return segs, f"通信控制 [{stype}]"


def parse_22_62(sid_byte: str, rest: str, stype: str, did_map: dict):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} ReadDataByIdentifier ({stype})", "sid")]
    did_val = did_name_val = data_val = ""
    if len(rest) >= 4:
        did_val = rest[:4]
        did_name_val = did_map.get(did_val, "未知 DID")
        segs.append(seg("DID", did_val, f"0x{did_val} — {did_name_val}", "did"))
        if len(rest) > 4:
            data_val = rest[4:]
            segs.append(seg("数据", data_val, f"0x{data_val}", "data"))
    suffix = f"，数据：0x{data_val}" if data_val else ""
    summary = f"读取 DID [{stype}]：0x{did_val}（{did_name_val}）{suffix}"
    return segs, summary, did_val, did_name_val, data_val


def parse_31_71(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} RoutineControl ({stype})", "sid")]
    ctrl_types = {"01": "startRoutine（启动例程）", "02": "stopRoutine（停止例程）", "03": "requestRoutineResults（请求结果）"}
    if len(rest) >= 2:
        ct = rest[:2]
        segs.append(seg("控制类型", ct, ctrl_types.get(ct, f"未知 0x{ct}"), "subfunction"))
        if len(rest) >= 6:
            rid = rest[2:6]
            segs.append(seg("例程ID", rid, f"0x{rid}", "did"))
            if len(rest) > 6:
                segs.append(seg("状态/参数", rest[6:], f"0x{rest[6:]}", "data"))
    return segs, f"例程控制 [{stype}]"


def parse_3e_7e(sid_byte: str, rest: str, stype: str):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} TesterPresent ({stype})", "sid")]
    if len(rest) >= 2:
        sf = rest[:2]
        sf_name = "suppressPosRspMsgIndicationBit（抑制肯定响应）" if sf == "80" else "zeroSubFunction（响应使能）"
        segs.append(seg("子功能", sf, sf_name, "subfunction"))
    return segs, f"测试仪在线 [{stype}]"


def parse_7f(sid_byte: str, rest: str):
    segs = [seg("SID", sid_byte, "0x7F NegativeResponse（否定响应）", "sid")]
    req_sid = nrc_val = ""
    if len(rest) >= 2:
        req_sid = rest[:2]
        req_cn = UDS_REGISTRY.get(req_sid, {}).get("cn", f"未知服务 0x{req_sid}")
        segs.append(seg("拒绝的服务", req_sid, f"0x{req_sid} — {req_cn}", "subfunction"))
    if len(rest) >= 4:
        nrc_val = rest[2:4]
        segs.append(seg("NRC", nrc_val, NRC_MAP.get(nrc_val, f"未知 NRC 0x{nrc_val}"), "nrc"))
    nrc_desc = NRC_MAP.get(nrc_val, "未知") if nrc_val else "—"
    return segs, f"否定响应：服务 0x{req_sid}，NRC = 0x{nrc_val}（{nrc_desc}）"


def parse_generic(sid_byte: str, rest: str, svc: dict):
    segs = [seg("SID", sid_byte, f"0x{sid_byte} {svc['name']}（{svc['cn']}）[{svc['type']}]", "sid")]
    if rest:
        segs.append(seg("数据", rest, f"0x{rest}", "data"))
    return segs, f"{svc['cn']} [{svc['type']}]"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    oem_configs = [
        {"name": p.stem, "count": count_oem_dids(p)}
        for p in sorted(OEM_CONFIGS_DIR.glob("*.csv"))
    ]
    return {"status": "ok", "oem_configs": oem_configs}


@app.post("/parse", response_model=ParseResponse)
def parse_uds(req: ParseRequest):
    raw = req.data.strip().upper().replace(" ", "")

    if len(raw) < 2 or len(raw) % 2 != 0:
        raise HTTPException(status_code=400, detail="数据格式错误：需要偶数个十六进制字符（至少 2 个）")
    try:
        bytes.fromhex(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="包含无效的十六进制字符")

    sid = raw[:2]
    rest = raw[2:]
    svc = UDS_REGISTRY.get(sid)
    did = did_name = value_hex = ""

    if svc is None:
        segs = [seg("SID", sid, f"0x{sid} — 未知服务", "sid")]
        if rest:
            segs.append(seg("数据", rest, f"0x{rest}", "data"))
        return ParseResponse(
            raw=raw, service_id=sid, service_name="Unknown", service_cn="未知服务",
            response_type="unknown", segments=segs, summary=f"未知服务 0x{sid}",
        )

    stype = svc["type"]
    did_map = get_did_map(req.oem)

    if sid in ("10", "50"):
        segs, summary = parse_10_50(sid, rest, stype)
    elif sid in ("11", "51"):
        segs, summary = parse_11_51(sid, rest, stype)
    elif sid in ("27", "67"):
        segs, summary = parse_27_67(sid, rest, stype)
    elif sid in ("28", "68"):
        segs, summary = parse_28_68(sid, rest, stype)
    elif sid in ("22", "62"):
        segs, summary, did, did_name, value_hex = parse_22_62(sid, rest, stype, did_map)
    elif sid in ("31", "71"):
        segs, summary = parse_31_71(sid, rest, stype)
    elif sid in ("3E", "7E"):
        segs, summary = parse_3e_7e(sid, rest, stype)
    elif sid == "7F":
        segs, summary = parse_7f(sid, rest)
    else:
        segs, summary = parse_generic(sid, rest, svc)

    return ParseResponse(
        raw=raw,
        service_id=sid,
        service_name=svc["name"],
        service_cn=svc["cn"],
        response_type=stype,
        segments=segs,
        summary=summary,
        did=did,
        did_name=did_name,
        value_hex=value_hex,
        description=summary,
    )


@app.post("/oem_configs/upload")
async def upload_oem_config(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="只支持 .csv 文件")

    oem_name = Path(file.filename).stem
    if not oem_name or any(c in oem_name for c in r"/\.."):
        raise HTTPException(status_code=400, detail="无效的文件名")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码错误，请使用 UTF-8 编码")

    reader = csv.DictReader(io.StringIO(text))
    if "did" not in (reader.fieldnames or []) or "name" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV 必须包含 'did' 和 'name' 列")

    rows = [r for r in reader if r.get("did", "").strip()]
    (OEM_CONFIGS_DIR / f"{oem_name}.csv").write_bytes(content)
    return {"message": f"已上传 OEM 配置：{oem_name}，共 {len(rows)} 条 DID 定义"}


@app.get("/oem_configs")
def list_oem_configs():
    return {"configs": [p.stem for p in sorted(OEM_CONFIGS_DIR.glob("*.csv"))]}


@app.get("/")
def index():
    return FileResponse("index.html")
