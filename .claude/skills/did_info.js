/**
 * did_info — UDS DID 信息查询 Skill
 *
 * 用法：/did_info <DID>
 * 示例：/did_info F190
 *       /did_info F188
 *
 * 将常见的 UDS DID 映射为可读名称，并给出解释。
 */

const DID_DATABASE = {
  F190: {
    name: "VIN 码",
    description: "Vehicle Identification Number，车辆识别码，17 位字符串，唯一标识车辆。",
    length: "17 字节（ASCII）",
  },
  F188: {
    name: "ECU 软件版本号",
    description: "ECU Software Version Number，标识当前 ECU 烧录的软件版本。",
    length: "可变长度",
  },
  F187: {
    name: "零件编号",
    description: "Spare Part Number，ECU 零件编号，通常为厂商内部编码。",
    length: "可变长度",
  },
  F189: {
    name: "ECU 软件版本",
    description: "ECU Software Version，细化版本标识，有时与 F188 配合使用。",
    length: "可变长度",
  },
  F191: {
    name: "ECU 硬件版本号",
    description: "ECU Hardware Version Number，标识 ECU 硬件电路板版本。",
    length: "可变长度",
  },
  F18C: {
    name: "ECU 序列号",
    description: "ECU Serial Number，唯一标识单个 ECU 硬件单元。",
    length: "可变长度",
  },
  F186: {
    name: "当前诊断会话",
    description: "Active Diagnostic Session，表示当前激活的 UDS 诊断会话类型（默认/编程/扩展）。",
    length: "1 字节",
  },
  F18A: {
    name: "系统供应商 ID",
    description: "System Supplier Identifier，ECU 系统供应商标识符。",
    length: "可变长度",
  },
};

/**
 * 查询 DID 信息
 * @param {string} did - 4 位十六进制 DID，如 "F190"
 * @returns {object} DID 信息对象，或未知提示
 */
function lookupDID(did) {
  const key = did.trim().toUpperCase();
  if (DID_DATABASE[key]) {
    return {
      did: key,
      ...DID_DATABASE[key],
      found: true,
    };
  }
  return {
    did: key,
    name: "未知 DID",
    description: `DID 0x${key} 不在内置数据库中，请查阅 ISO 14229 或 OEM 文档。`,
    length: "未知",
    found: false,
  };
}

/**
 * 格式化输出 DID 信息
 * @param {string} did
 * @returns {string}
 */
function formatDIDInfo(did) {
  const info = lookupDID(did);
  return [
    `DID: 0x${info.did}`,
    `名称: ${info.name}`,
    `说明: ${info.description}`,
    `数据长度: ${info.length}`,
  ].join("\n");
}

// 当作为 Claude Code Skill 被调用时，输出查询结果
// args 由 Claude Code harness 注入，第一个参数为 DID 值
const args = (typeof $args !== "undefined") ? $args : process.argv.slice(2);
const inputDID = args[0] || "";

if (inputDID) {
  console.log(formatDIDInfo(inputDID));
} else {
  console.log("用法: /did_info <DID>\n示例: /did_info F190\n\n已知 DID 列表:");
  Object.entries(DID_DATABASE).forEach(([did, info]) => {
    console.log(`  0x${did}  ${info.name}`);
  });
}

module.exports = { lookupDID, formatDIDInfo, DID_DATABASE };
