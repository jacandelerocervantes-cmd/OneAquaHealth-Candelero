/** Security headers of the web app (docs/predeploy_checklist.md section 3). Pure, so tests can pin them. */

export const OSM_TILE_HOST = "https://tile.openstreetmap.org";

export function buildCsp(nonce: string, dev = false): string {
  const directives = [
    "default-src 'self'",
    // A nonce for the inline scripts the framework emits; no 'unsafe-eval' outside development.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    // Leaflet and the framework set inline style attributes.
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: ${OSM_TILE_HOST}`,
    "font-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ];
  return directives.join("; ");
}

export function securityHeaders(nonce: string, dev = false): Record<string, string> {
  return {
    "Content-Security-Policy": buildCsp(nonce, dev),
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  };
}
