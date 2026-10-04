import type { components } from "./api-types";

/** Shorthand for a schema generated from docs/openapi.json. */
export type Schema<N extends keyof components["schemas"]> = components["schemas"][N];

export type ChatRequest = Schema<"ChatRequest">;
export type ChatResponse = Schema<"ChatResponse">;
export type ChatTurn = Schema<"ChatTurn">;
export type CatalogResponse = Schema<"CatalogResponse">;
export type CatalogIndex = Schema<"CatalogIndex">;
export type CatalogFamily = Schema<"CatalogFamily">;
export type CountriesResponse = Schema<"CountriesResponse">;
export type LanguagesResponse = Schema<"LanguagesResponse">;
export type LanguageEntry = Schema<"LanguageEntry">;
export type SitesResponse = Schema<"SitesResponse">;
export type Site = Schema<"Site">;
export type Origin = Schema<"ChatResponse">["origin"];
export type IndexId = CatalogIndex["id"];
export type ChatIndex = NonNullable<ChatRequest["index"]>;

/** The error body the backend returns for every non-2xx answer. */
export type ErrorBody = Schema<"ErrorResponse">;
