import { ApiReferenceReact } from '@scalar/api-reference-react';
// Scalar's structural stylesheet is imported by the consuming page, not here:
// this island renders client:only, so Astro can't trace a CSS import made inside
// the component during the static build and the API reference would ship unstyled.

export default function ScalarReference() {
	return (
		<ApiReferenceReact
			configuration={{
				url: '/openapi.json',
				layout: 'modern',
				// Reference only — hide the API-client workbench chrome. Search,
				// method badges, and client-library snippets stay.
				hideClientButton: true,
				hideTestRequestButton: true,
				hideDarkModeToggle: true,
				hideDownloadButton: false,
				// Tokens are mapped to the Tidings palette in
				// styles/starlight-overrides.css (--scalar-*).
				theme: 'none',
				withDefaultFonts: false,
			}}
		/>
	);
}
