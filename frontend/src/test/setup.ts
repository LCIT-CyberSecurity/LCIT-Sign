import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "../i18n";
import { setLocale, STORAGE_KEY } from "../i18n";

afterEach(async () => {
  cleanup();
  // Every test starts, as a fresh installation does, in French with nothing remembered.
  await setLocale("fr");
  window.localStorage.removeItem(STORAGE_KEY);
});
