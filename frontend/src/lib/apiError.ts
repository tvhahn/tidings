// Typed error thrown by the real API client (lib/api.ts). Carries the
// backend's unified `{error, code, details}` body so UI surfaces can show
// the human-readable message the API already produced instead of
// "API error: 500 Internal Server Error". Lives outside api.ts so demo
// builds (which alias api.ts -> demoApi.ts) can share it without affecting
// the export-parity contract between those two modules.
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}
