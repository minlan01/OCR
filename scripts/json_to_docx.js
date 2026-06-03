/**
 * 将 ScanStruct 结构化 JSON 转换为 Word 文档
 * 用法: node scripts/json_to_docx.js <input.json> [output.docx]
 */

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle,
  WidthType, ShadingType, PageNumber, PageBreak, LevelFormat,
  TabStopType, TabStopPosition,
} = require("docx");

// ─── 参数解析 ───────────────────────────────────────────────
const args = process.argv.slice(2);
if (args.length < 1) {
  console.error("用法: node json_to_docx.js <input.json> [output.docx]");
  process.exit(1);
}
const inputPath = args[0];
const outputPath = args[1] || inputPath.replace(/\.json$/, ".docx");

// ─── 读取 JSON ───────────────────────────────────────────────
const data = JSON.parse(fs.readFileSync(inputPath, "utf-8"));

// ─── 辅助函数 ───────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: "999999" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 120, right: 120 };

function infoTableRow(label, value, shading = "FFFFFF") {
  const cells = [
    new TableCell({
      borders,
      width: { size: 3000, type: WidthType.DXA },
      shading: { fill: "F0F4F8", type: ShadingType.CLEAR },
      margins: cellMargins,
      children: [new Paragraph({ children: [new TextRun({ text: label, bold: true, font: "Microsoft YaHei", size: 21 })] })],
    }),
    new TableCell({
      borders,
      width: { size: 6360, type: WidthType.DXA },
      shading: { fill: shading, type: ShadingType.CLEAR },
      margins: cellMargins,
      children: [new Paragraph({ children: [new TextRun({ text: String(value || "—"), font: "Microsoft YaHei", size: 21 })] })],
    }),
  ];
  return new TableRow({ children: cells });
}

function headingPara(text, level) {
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    spacing: { before: level === 1 ? 360 : 240, after: 120 },
    children: [new TextRun({ text, font: "Microsoft YaHei", bold: true })],
  });
}

function bodyPara(text, indent = 0) {
  return new Paragraph({
    spacing: { after: 80 },
    indent: { left: indent * 480 },
    children: [new TextRun({ text, font: "Microsoft YaHei", size: 21 })],
  });
}

// ─── 构建文档内容 ───────────────────────────────────────────
const children = [];

// ═══════ 封面标题 ═══════
children.push(
  new Paragraph({ spacing: { before: 2400 }, children: [] }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 120 },
    children: [new TextRun({ text: "ScanStruct 扫描件结构化处理报告", font: "Microsoft YaHei", size: 44, bold: true, color: "1F4E79" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: "文档结构化输出结果", font: "Microsoft YaHei", size: 28, color: "555555" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: "生成时间: " + data.pipeline.processed_at, font: "Microsoft YaHei", size: 20, color: "888888" })],
  }),
  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════ 一、流水线信息 ═══════
children.push(headingPara("一、处理流水线信息", 1));

children.push(
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      infoTableRow("引擎版本", data.pipeline.engine),
      infoTableRow("OCR 引擎", data.pipeline.ocr_engine),
      infoTableRow("处理时间", data.pipeline.processed_at),
      infoTableRow("处理步骤", data.pipeline.steps.join(" → ")),
    ],
  }),
);
children.push(bodyPara(""));

// ═══════ 二、文档基本信息 ═══════
children.push(headingPara("二、文档基本信息", 1));

children.push(
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      infoTableRow("文档 ID", data.document.id),
      infoTableRow("文档类别", data.document.category),
      infoTableRow("文档类型", data.document.doc_type),
      infoTableRow("分类置信度", (data.document.confidence * 100).toFixed(1) + "%"),
      infoTableRow("总页数", String(data.document.total_pages)),
    ],
  }),
);
children.push(bodyPara(""));

// ═══════ 三、文头信息 ═══════
children.push(headingPara("三、文头信息", 1));

children.push(
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      infoTableRow("发文机关", data.header.issuing_org),
      infoTableRow("发文字号", data.header.ref_number || data.header.ref_type + "〔" + data.header.ref_year + "〕" + data.header.ref_seq + "号"),
      infoTableRow("字号类型", data.header.ref_type),
      infoTableRow("年份", data.header.ref_year),
      infoTableRow("序号", data.header.ref_seq),
    ],
  }),
);
children.push(bodyPara(""));

// ═══════ 四、标题 ═══════
children.push(headingPara("四、标题", 1));

children.push(bodyPara(data.title.main, 0));
if (data.title.subtitle) {
  children.push(bodyPara(data.title.subtitle, 0));
}

children.push(
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [infoTableRow("主题", data.title.theme || data.title.main)],
  }),
);
children.push(bodyPara(""));

// ═══════ 五、正文内容 ═══════
children.push(headingPara("五、正文内容", 1));

// 递归渲染章节
function renderSections(sections, level) {
  const result = [];
  for (const sec of sections) {
    // 标题行
    result.push(
      new Paragraph({
        spacing: { before: level === 2 ? 200 : 120, after: 60 },
        indent: { left: (level - 2) * 480 },
        children: [new TextRun({ text: sec.heading, font: "Microsoft YaHei", size: level === 2 ? 22 : 21, bold: true })],
      }),
    );
    // 内容
    if (sec.content) {
      const lines = sec.content.split("\n").filter(Boolean);
      for (const line of lines) {
        result.push(bodyPara(line.trim(), level - 1));
      }
    }
    // 子章节
    if (sec.sub_sections && sec.sub_sections.length > 0) {
      for (const r of renderSections(sec.sub_sections, level + 1)) {
        result.push(r);
      }
    }
  }
  return result;
}

for (const elem of renderSections(data.body.sections, 2)) {
  children.push(elem);
}

// 全文文本（可折叠参考）
children.push(
  new Paragraph({ spacing: { before: 200 }, children: [] }),
  new Paragraph({
    spacing: { after: 60 },
    children: [new TextRun({ text: "【全文文本（原始提取）】", font: "Microsoft YaHei", size: 18, color: "999999", italics: true })],
  }),
);
const fullLines = data.body.full_text.split("\n").filter(Boolean);
for (const line of fullLines) {
  children.push(
    new Paragraph({
      spacing: { after: 40 },
      children: [new TextRun({ text: line.trim(), font: "Microsoft YaHei", size: 18, color: "888888" })],
    }),
  );
}

// ═══════ 六、签名与落款 ═══════
children.push(headingPara("六、签名与落款", 1));

children.push(
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [3000, 6360],
    rows: [
      infoTableRow("署名机关", data.signature.org, "FFF9E6"),
      infoTableRow("日期", data.signature.date, "FFF9E6"),
      infoTableRow("通报/分发", data.signature.distribution || "—"),
    ],
  }),
);
children.push(bodyPara(""));

// 抄送
if (data.signature.cc && data.signature.cc.length > 0) {
  children.push(
    new Paragraph({
      spacing: { after: 40 },
      children: [new TextRun({ text: "抄送:", font: "Microsoft YaHei", size: 21, bold: true })],
    }),
  );
  for (const c of data.signature.cc) {
    children.push(bodyPara("  " + c, 1));
  }
}

// 收件人
if (data.signature.recipients && data.signature.recipients.length > 0) {
  children.push(
    new Paragraph({
      spacing: { before: 120, after: 40 },
      children: [new TextRun({ text: "收件人:", font: "Microsoft YaHei", size: 21, bold: true })],
    }),
  );
  for (const r of data.signature.recipients) {
    children.push(bodyPara("  " + r, 1));
  }
}

// ═══════ 七、附件 ═══════
if (data.attachments && data.attachments.length > 0) {
  children.push(headingPara("七、附件", 1));

  for (const att of data.attachments) {
    children.push(
      new Paragraph({
        spacing: { before: 120, after: 60 },
        children: [new TextRun({ text: att.name, font: "Microsoft YaHei", size: 22, bold: true, color: "2E75B6" })],
      }),
    );

    // 附件内容以缩进段落呈现
    for (const line of att.content_lines) {
      if (line === ":") {
        children.push(bodyPara(line, 0));
      } else if (line.startsWith("兹") || line.startsWith("同学") || line.startsWith("盼")) {
        children.push(bodyPara(line, 0));
      } else {
        children.push(bodyPara(line, 1));
      }
    }

    // 分隔线
    children.push(
      new Paragraph({
        spacing: { before: 160, after: 160 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 1 } },
        children: [],
      }),
    );
  }
}

// ═══════ 页脚 ═══════
children.push(
  new Paragraph({ spacing: { before: 600 }, children: [] }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "— 报告结束 —", font: "Microsoft YaHei", size: 18, color: "AAAAAA" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 120 },
    children: [new TextRun({ text: "由 ScanStruct v0.1.0 自动生成", font: "Microsoft YaHei", size: 16, color: "BBBBBB" })],
  }),
);

// ─── 构建文档 ───────────────────────────────────────────────
const doc = new Document({
  styles: {
    default: {
      document: {
        run: { font: "Microsoft YaHei", size: 21 },
      },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Microsoft YaHei", color: "1F4E79" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Microsoft YaHei", color: "2E75B6" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Microsoft YaHei" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 },
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1440, right: 1260, bottom: 1440, left: 1260 },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              alignment: AlignmentType.RIGHT,
              border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E75B6", space: 4 } },
              children: [
                new TextRun({ text: "ScanStruct 结构化处理报告", font: "Microsoft YaHei", size: 16, color: "888888" }),
                new TextRun("\t"),
                new TextRun({ text: data.document.id, font: "Microsoft YaHei", size: 16, color: "BBBBBB", italics: true }),
              ],
              tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [
                new TextRun({ text: "第 ", font: "Microsoft YaHei", size: 16, color: "999999" }),
                new TextRun({ children: [PageNumber.CURRENT], font: "Microsoft YaHei", size: 16, color: "999999" }),
                new TextRun({ text: " 页", font: "Microsoft YaHei", size: 16, color: "999999" }),
              ],
            }),
          ],
        }),
      },
      children,
    },
  ],
});

// ─── 生成文件 ───────────────────────────────────────────────
Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log("DOCX 已生成: " + outputPath);
  console.log("文件大小: " + (buffer.length / 1024).toFixed(1) + " KB");
}).catch((err) => {
  console.error("生成失败:", err);
  process.exit(1);
});
