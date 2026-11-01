import { describe, expect, it } from "vitest";
import { questionSourceLabel } from "./questionSource";
import type { QuestionTrustView } from "../types/practice";

describe("question provenance", () => {
  it("uses a distinct label for personal AI practice", () => {
    const trust = { bank_scope: "personal", question_provenance: "ai_generated_practice" } as QuestionTrustView;
    expect(questionSourceLabel(null, false, trust)).toBe("AI练习题");
  });
  it("uses the specific public source label instead of the broad AI provenance", () => {
    const trust = { bank_scope: "public", question_provenance: "ai_generated_practice", practice_eligible: true } as unknown as QuestionTrustView;
    expect(questionSourceLabel(null, false, trust, false)).toBe("原创");
    expect(questionSourceLabel(null, false, trust, true)).toBe("真题改编");
  });
  it("normalizes explicit presentation labels to the product's concise categories", () => {
    const trust = { bank_scope: "public", question_provenance: "ai_generated_practice", presentation_label: "真题改编题" } as QuestionTrustView;
    expect(questionSourceLabel(null, false, trust)).toBe("真题改编");
    trust.presentation_label = "AI原创练习题";
    expect(questionSourceLabel(null, false, trust)).toBe("原创");
  });
  it("does not present legacy source declarations as confirmed exams", () => {
    const trust = { question_provenance: "legacy_unknown" } as QuestionTrustView;
    expect(questionSourceLabel({ source_type: "exam", content_status: "source_transcribed", year: 2024,
      question_number: 7, subject: "数学二", paper_title: "本地整理" }, false, trust)).toBe("练习题");
  });
  it("labels traceable exam organization without promising facsimile or verified answer", () => {
    const trust = { question_provenance: "real_exam", source_attestation_current: true, source_status: "traceable" } as QuestionTrustView;
    expect(questionSourceLabel({ source_type: "exam", content_status: "source_transcribed", year: 2024,
      question_number: 7, subject: "数学二", paper_title: "本地整理" }, false, trust)).toBe("2024 年 · 数学二 · 真题整理");
  });
  it("keeps AI practice distinct from exam metadata", () => {
    expect(questionSourceLabel(null, false, { bank_scope: "personal", question_provenance: "ai_generated_practice" } as QuestionTrustView)).toBe("AI练习题");
  });
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
    expect(questionSourceLabel({ source_type: "unknown", content_status: "unknown", year: 2024 })).toBe("练习题");
    expect(questionSourceLabel(null)).toBe("练习题");
    expect(questionSourceLabel({ source_type: "exam", content_status: "unknown", year: 2024 })).toBe("练习题");
    expect(questionSourceLabel({ source_type: "original", content_status: "unknown" })).toBe("原创");
  });
  it("labels transcribed references without claiming verified answers", () => {
    expect(questionSourceLabel({ source_type: "exam", content_status: "source_transcribed", year: 2026,
      question_number: 8, subject: "数学二", paper_title: "本地原卷", edition: "第三方汇编" }))
      .toBe("2026 年 · 数学二真题 · 第 8 题 · 第三方汇编 · 原卷转录");
  });
  it.each(["来源待核练习", "来源待核", "来源未登记", "来源待确认"])("shows %s as a neutral practice label", (label) => {
    const trust = { bank_scope: "public", presentation_label: label } as QuestionTrustView;
    expect(questionSourceLabel({ source_type: "unknown", content_status: "unknown", year: 2024 }, false, trust)).toBe("练习题");
  });
  it("does not change an unconfirmed exam into an original or verified exam", () => {
    const trust = { question_provenance: "real_exam", source_attestation_current: false, source_status: "traceable" } as QuestionTrustView;
    expect(questionSourceLabel(null, false, trust)).toBe("练习题");
  });
});
