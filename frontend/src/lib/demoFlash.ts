const FLASH_KEY = "demo-flash-message";

export function setDemoFlash(message: string): void {
  try {
    window.sessionStorage.setItem(FLASH_KEY, message);
  } catch {
    // ignore
  }
}

export function readAndClearDemoFlash(): string | null {
  let raw: string | null = null;
  try {
    raw = window.sessionStorage.getItem(FLASH_KEY);
  } catch {
    raw = null;
  }
  if (raw) {
    try {
      window.sessionStorage.removeItem(FLASH_KEY);
    } catch {
      // ignore
    }
  }
  return raw;
}
