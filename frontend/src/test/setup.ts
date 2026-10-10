import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "../i18n";
import { setLocale, STORAGE_KEY } from "../i18n";

// The tests are written for the French interface: whatever language the test browser reports,
// each one starts in French with nothing remembered.
beforeEach(async () => {
  window.localStorage.removeItem(STORAGE_KEY);
  await setLocale("fr");
  window.localStorage.removeItem(STORAGE_KEY);
});

afterEach(async () => {
  cleanup();
  await setLocale("fr");
  window.localStorage.removeItem(STORAGE_KEY);
});
