import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// The app starts in es-MX; the tests read English texts, so every test starts with English selected.
// A test that checks the defaults clears the storage itself.
beforeEach(() => {
  window.localStorage.setItem(
    "oah.settings.v1",
    JSON.stringify({ defaultCountry: "GR", defaultLanguage: "en", country: "GR", language: "en" }),
  );
});

afterEach(() => cleanup());
