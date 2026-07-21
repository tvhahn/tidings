import { describe, expect, it } from "vitest";
import { formatBytes, isImageContentType, isPdfContentType } from "@/lib/attachments";

describe("formatBytes", () => {
  it("returns 0 B for zero or invalid sizes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-5)).toBe("0 B");
    expect(formatBytes(Number.NaN)).toBe("0 B");
  });

  it("keeps bytes below 1 KiB whole", () => {
    expect(formatBytes(1)).toBe("1 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });

  it("scales into KB/MB/GB with at most one decimal", () => {
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10 MB");
    expect(formatBytes(1024 * 1024 * 1024)).toBe("1 GB");
  });
});

describe("content-type predicates", () => {
  it("recognizes images", () => {
    expect(isImageContentType("image/jpeg")).toBe(true);
    expect(isImageContentType("image/png")).toBe(true);
    expect(isImageContentType("application/pdf")).toBe(false);
  });

  it("recognizes pdfs", () => {
    expect(isPdfContentType("application/pdf")).toBe(true);
    expect(isPdfContentType("image/png")).toBe(false);
  });
});
