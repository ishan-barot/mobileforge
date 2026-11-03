import { describe, expect, it } from "vitest";
import { redact } from "../src/redact";

describe("bare phones", () => {
  it("10 digits is a phone", () => {
    expect(redact("cell 4165550142")).toBe("cell [PHONE]");
  });
  it("long runs are still numbers", () => {
    expect(redact("ref 123456789012")).toBe("ref [NUMBER]");
  });
  it("labeled accounts still win", () => {
    expect(redact("Account number: 8841229017")).toBe("Account [ACCOUNT]");
  });
});
