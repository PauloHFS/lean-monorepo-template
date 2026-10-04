/**
 * Reexports limpos do schema OpenAPI gerado.
 * Use estes tipos no app; o resto de `schema` é detalhe de paths/operations.
 *
 * Regenerar: `just web-types`.
 */
import type { components } from "./schema";

export type UserOut = components["schemas"]["UserOut"];
export type RegisterIn = components["schemas"]["RegisterIn"];
export type LoginIn = components["schemas"]["LoginIn"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type EnqueueEmailIn = components["schemas"]["EnqueueEmailIn"];
export type EnqueueEmailOut = components["schemas"]["EnqueueEmailOut"];
export type HTTPValidationError = components["schemas"]["HTTPValidationError"];
export type ValidationError = components["schemas"]["ValidationError"];