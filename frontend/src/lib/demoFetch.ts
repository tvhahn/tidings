export class DemoModeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DemoModeError";
  }
}

export class DemoFixtureMissingError extends Error {
  readonly slug: string;
  constructor(slug: string) {
    super(`Demo fixture missing: ${slug}`);
    this.name = "DemoFixtureMissingError";
    this.slug = slug;
  }
}

export async function loadFixture<T>(slug: string): Promise<T> {
  const url = `/demo-data/${slug}.json`;
  const res = await fetch(url);
  if (res.status === 404) {
    throw new DemoFixtureMissingError(slug);
  }
  if (!res.ok) {
    throw new Error(`Fixture load failed: ${res.status} ${res.statusText} (${slug})`);
  }
  return res.json() as Promise<T>;
}
