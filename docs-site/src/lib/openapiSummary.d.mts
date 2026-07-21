export interface EndpointSummary {
	method: string;
	path: string;
	summary: string;
}

export interface EndpointGroup {
	tag: string;
	endpoints: EndpointSummary[];
}

/** Group an OpenAPI spec's operations by first tag, in declared-then-encountered order. */
export declare function endpointGroups(spec: unknown): EndpointGroup[];

/** Render an OpenAPI spec into machine-readable markdown (C5 shape). */
export declare function openapiToMarkdown(spec: unknown): string;
