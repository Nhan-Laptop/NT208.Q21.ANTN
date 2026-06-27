export const SUPPORTED_BIBLIOGRAPHY_EXTENSIONS = ["txt", "bib", "ris", "enw"] as const;
export const MAX_BIBLIOGRAPHY_FILE_BYTES = 2 * 1024 * 1024;

type SupportedBibliographyExtension = (typeof SUPPORTED_BIBLIOGRAPHY_EXTENSIONS)[number];

export class BibliographyFileImportError extends Error {
  code: "unsupported_type" | "too_large" | "read_failed";

  constructor(code: "unsupported_type" | "too_large" | "read_failed", message: string) {
    super(message);
    this.code = code;
  }
}

export interface LoadedBibliographyFile {
  fileName: string;
  fileSize: number;
  extension: SupportedBibliographyExtension;
  text: string;
  warning: string | null;
}

function normalizeLineEndings(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

async function readFileAsText(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }

  if (typeof FileReader === "undefined") {
    throw new Error("FileReader unavailable");
  }

  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("FileReader failed"));
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.readAsText(file);
  });
}

function splitBibtexEntries(text: string): string[] {
  const normalized = normalizeLineEndings(text);
  const entries: string[] = [];
  let start = -1;
  let braceDepth = 0;
  let parenDepth = 0;
  let sawOpener = false;

  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index];

    if (start === -1) {
      if (char === "@") {
        start = index;
        braceDepth = 0;
        parenDepth = 0;
        sawOpener = false;
      }
      continue;
    }

    if (char === "{") {
      braceDepth += 1;
      sawOpener = true;
    } else if (char === "}") {
      braceDepth = Math.max(0, braceDepth - 1);
    } else if (char === "(") {
      parenDepth += 1;
      sawOpener = true;
    } else if (char === ")") {
      parenDepth = Math.max(0, parenDepth - 1);
    }

    if (sawOpener && braceDepth === 0 && parenDepth === 0) {
      const entry = normalized.slice(start, index + 1).trim();
      if (entry.startsWith("@")) {
        entries.push(entry);
      }
      start = -1;
    }
  }

  if (start !== -1) {
    const trailing = normalized.slice(start).trim();
    if (trailing.startsWith("@")) {
      entries.push(trailing);
    }
  }

  return entries.filter(Boolean);
}

function parseBibtex(text: string): { text: string; warning: string | null } {
  const entries = splitBibtexEntries(text);
  if (!entries.length) {
    return {
      text: normalizeLineEndings(text).trim(),
      warning: "Loaded .bib content as raw text because entries could not be split confidently.",
    };
  }

  return {
    text: entries.join("\n\n"),
    warning: null,
  };
}

function parseRis(text: string): { text: string; warning: string | null } {
  const normalized = normalizeLineEndings(text);
  const lines = normalized.split("\n");
  const records: string[] = [];
  let current: string[] = [];
  let inRecord = false;

  for (const line of lines) {
    const trimmedLine = line.trimEnd();
    if (/^TY\s*-\s*/i.test(trimmedLine)) {
      if (current.length) {
        records.push(current.join("\n").trim());
        current = [];
      }
      inRecord = true;
      current.push(trimmedLine);
      continue;
    }

    if (!inRecord) {
      continue;
    }

    current.push(trimmedLine);
    if (/^ER\s*-\s*/i.test(trimmedLine)) {
      records.push(current.join("\n").trim());
      current = [];
      inRecord = false;
    }
  }

  if (current.length) {
    records.push(current.join("\n").trim());
  }

  if (!records.length) {
    return {
      text: normalized.trim(),
      warning: "Loaded .ris content as raw text because TY/ER records could not be split confidently.",
    };
  }

  return {
    text: records.filter(Boolean).join("\n\n"),
    warning: null,
  };
}

function parseEnw(text: string): { text: string; warning: string | null } {
  const normalized = normalizeLineEndings(text);
  const lines = normalized.split("\n");
  const records: string[] = [];
  let current: string[] = [];

  for (const line of lines) {
    const trimmedLine = line.trimEnd();
    if (/^%0\s+/i.test(trimmedLine) && current.length) {
      records.push(current.join("\n").trim());
      current = [trimmedLine];
      continue;
    }

    if (/^%0\s+/i.test(trimmedLine)) {
      current = [trimmedLine];
      continue;
    }

    if (current.length) {
      current.push(trimmedLine);
    }
  }

  if (current.length) {
    records.push(current.join("\n").trim());
  }

  if (!records.length) {
    return {
      text: normalized.trim(),
      warning: "Loaded .enw content as raw text because records could not be split confidently.",
    };
  }

  return {
    text: records.filter(Boolean).join("\n\n"),
    warning: null,
  };
}

function getSupportedExtension(fileName: string): SupportedBibliographyExtension | null {
  const extension = fileName.split(".").pop()?.trim().toLowerCase() ?? "";
  return SUPPORTED_BIBLIOGRAPHY_EXTENSIONS.find((candidate) => candidate === extension) ?? null;
}

export function estimateCitationCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;

  const nonEmptyLines = trimmed
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const numberedLines = nonEmptyLines.filter((line) => /^(\[\d+\]|\d+[.)])\s+/.test(line));
  const blocks = trimmed
    .split(/\n\s*\n+/)
    .map((block) => block.trim())
    .filter(Boolean);

  if (numberedLines.length >= 2) return numberedLines.length;
  if (nonEmptyLines.length >= 3) return nonEmptyLines.length;
  return Math.max(blocks.length, nonEmptyLines.length, 1);
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export async function loadBibliographyFile(file: File): Promise<LoadedBibliographyFile> {
  const extension = getSupportedExtension(file.name);
  if (!extension) {
    throw new BibliographyFileImportError(
      "unsupported_type",
      "Unsupported file type. Please upload .txt, .bib, .ris, or .enw.",
    );
  }

  if (file.size > MAX_BIBLIOGRAPHY_FILE_BYTES) {
    throw new BibliographyFileImportError(
      "too_large",
      `File is too large. Please keep bibliography files under ${formatFileSize(MAX_BIBLIOGRAPHY_FILE_BYTES)}.`,
    );
  }

  let rawText = "";
  try {
    rawText = await readFileAsText(file);
  } catch {
    throw new BibliographyFileImportError(
      "read_failed",
      "Could not read this file in the browser. Try saving it as plain text and upload again.",
    );
  }

  const normalizedText = normalizeLineEndings(rawText).trim();
  if (!normalizedText) {
    return {
      fileName: file.name,
      fileSize: file.size,
      extension,
      text: "",
      warning: null,
    };
  }

  const parsed = extension === "txt"
    ? { text: normalizedText, warning: null }
    : extension === "bib"
      ? parseBibtex(normalizedText)
      : extension === "ris"
        ? parseRis(normalizedText)
        : parseEnw(normalizedText);

  return {
    fileName: file.name,
    fileSize: file.size,
    extension,
    text: parsed.text,
    warning: parsed.warning,
  };
}
