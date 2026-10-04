// Interface translations: extract the keys from the source, or check the locale files against them.
//
//   node scripts/i18n.mjs extract   writes src/lib/locales/_keys.json (every English text shown through t() or msg())
//   node scripts/i18n.mjs check [code ...]   (all languages, or only the codes given) fails if a locale file misses a key, holds an unknown key, or changes a {placeholder}
//
// The key of a text is the English text itself. Only literals in double quotes are read (the lint rule of the project
// keeps them that way); a text built at run time must be declared with msg() somewhere, see src/lib/constants.ts.
import { readFileSync, readdirSync, statSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const SRC = "src";
const LOCALES = join(SRC, "lib", "locales");
const KEYS_FILE = join(LOCALES, "_keys.json");
const CODES = [
  "bg", "cs", "da", "de", "el", "es-ES", "es-MX", "et", "fi", "fr", "ga", "hr", "hu", "it",
  "lt", "lv", "mt", "nb", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
];

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "locales" ? [] : walk(path);
    return /\.(ts|tsx)$/.test(name) && !name.endsWith("api-types.ts") ? [path] : [];
  });
}

export function extractKeys() {
  const found = new Set();
  const re = /\b(?:t|msg)\(\s*"((?:[^"\\\n]|\\.)*)"/g;
  for (const file of walk(SRC)) {
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(re)) found.add(JSON.parse(`"${m[1]}"`));
  }
  return [...found].sort((a, b) => a.localeCompare(b, "en"));
}

const placeholders = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");

function check(only) {
  const codes = only.length ? only : CODES;
  const keys = JSON.parse(readFileSync(KEYS_FILE, "utf8"));
  const current = extractKeys();
  let problems = 0;
  const fail = (msg) => {
    problems += 1;
    console.error(msg);
  };
  if (JSON.stringify(keys) !== JSON.stringify(current)) fail("_keys.json is out of date: run `node scripts/i18n.mjs extract`.");
  for (const code of codes) {
    const file = join(LOCALES, `${code}.json`);
    if (!existsSync(file)) {
      fail(`${code}: file missing`);
      continue;
    }
    const dict = JSON.parse(readFileSync(file, "utf8"));
    for (const key of keys) {
      const value = dict[key];
      if (typeof value !== "string" || value.trim() === "") fail(`${code}: missing "${key.slice(0, 60)}"`);
      else {
        if (placeholders(value) !== placeholders(key)) fail(`${code}: placeholders differ in "${key.slice(0, 60)}"`);
        if (/<[a-zA-Z/!]|https?:|www\./i.test(value) && !/<[a-zA-Z/!]|https?:|www\./i.test(key)) fail(`${code}: markup or link in "${key.slice(0, 60)}"`);
      }
    }
    for (const key of Object.keys(dict)) if (!keys.includes(key)) fail(`${code}: unknown key "${key.slice(0, 60)}"`);
  }
  if (problems) {
    console.error(`${problems} problem(s).`);
    process.exit(1);
  }
  console.log(`i18n ok: ${keys.length} texts in ${codes.length} language(s): ${codes.join(", ")}.`);
}

const command = process.argv[2];
if (command === "extract") {
  const keys = extractKeys();
  writeFileSync(KEYS_FILE, JSON.stringify(keys, null, 2) + "\n");
  console.log(`${keys.length} texts written to ${KEYS_FILE}`);
} else if (command === "check") {
  check(process.argv.slice(3));
} else {
  console.error("usage: node scripts/i18n.mjs extract | check [code ...]");
  process.exit(2);
}
