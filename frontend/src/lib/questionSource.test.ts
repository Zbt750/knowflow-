import { describe, expect, it } from "vitest";
import { questionSourceLabel } from "./questionSource";

describe("question provenance", () => {
  it("hides original numbering on the generated practice paper", () => {
    expect(questionSourceLabel({ source_type: "exam", content_status: "unknown", year: 2025,
      question_number: 19, subject: "数学二", paper_title: "2025 数学二" }, false))
      .toBe("2025 年 · 数学二真题");
  });
  it("shows explicit exam year and number", () => {
    expect(questionSourceLabel({ source_type: "exam", content_status: "unknown", year: 2024, question_number: 8, subject: "数学二", paper_title: "2024 数学二" })).toBe("2024 年 · 数学二真题 · 第 8 题");
  });
  it("does not confuse mock with real exams", () => {
    expect(questionSourceLabel({ source_type: "mock", content_status: "unknown", year: 2025, question_number: 3, subject: "408", paper_title: "合成隔离模拟卷" })).toBe("2025 年 · 合成隔离模拟卷 · 模拟题 · 第 3 题");
  });
  it("does not turn publication years or legacy missing sources into exams", () => {
    expect(questionSourceLabel({ source_type: "unknown", content_status: "unknown", year: 2024 })).toBe("来源未登记");
    expect(questionSourceLabel(null)).toBe("来源未登记");
    expect(questionSourceLabel({ source_type: "exam", content_status: "unknown", year: 2024 })).toBe("来源待确认");
    expect(questionSourceLabel({ source_type: "original", content_status: "unknown" })).toBe("原创练习（非真题）");
  });
  it("labels transcribed references without claiming verified answers", () => {
    expect(questionSourceLabel({ source_type: "exam", content_status: "source_transcribed", year: 2026,
      question_number: 8, subject: "数学二", paper_title: "本地原卷", edition: "第三方汇编" }))
      .toBe("2026 年 · 数学二真题 · 第 8 题 · 第三方汇编 · 原卷转录");
  });
});
