import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// The default language is English; the stored settings are written here so that every test starts from the same known
// state. A test that checks the defaults clears the storage itself (tests/i18n.test.tsx).
beforeEach(() => {
  window.localStorage.setItem(
    "oah.settings.v1",
    JSON.stringify({ defaultCountry: "GR", defaultLanguage: "en", country: "GR", language: "en" }),
  );
});

afterEach(() => cleanup());
