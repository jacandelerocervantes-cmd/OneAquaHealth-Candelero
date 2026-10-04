"use client";

import type { CountriesResponse, LanguagesResponse } from "@/lib/api";
import { updateSettings, useSettings } from "@/lib/client/settings-store";
import { useApi } from "@/lib/client/use-api";
import { ABOUT_TEXT, ATTRIBUTIONS } from "@/lib/attributions";
import { COUNTRY_NAMES, FIXED_NOTICE, USER_LABEL } from "@/lib/constants";
import { countryName, useT } from "@/lib/i18n";
import PageHeader from "./page-header";
import { Notice } from "./ui";

export default function SettingsView() {
  const settings = useSettings();
  const t = useT();
  const countries = useApi<CountriesResponse>("/countries");
  const languages = useApi<LanguagesResponse>("/languages");
  const codes = countries.status === "ready" ? countries.data.countries.map((c) => c.code) : [settings.defaultCountry];
  const langs = languages.status === "ready" ? languages.data.languages : [];

  return (
    <>
      <PageHeader title={t("Settings")} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
          <section aria-labelledby="prefs" className="space-y-4">
            <h2 id="prefs" className="text-base font-semibold">{t("Preferences")}</h2>
            <p className="text-sm text-muted">{t("Signed in as {user}. Preferences are kept in this browser only.", { user: t(USER_LABEL) })}</p>
            <div>
              <label htmlFor="default-language" className="block text-sm">{t("Default language")}</label>
              <select
                id="default-language"
                data-testid="default-language"
                value={settings.defaultLanguage}
                onChange={(e) => updateSettings({ defaultLanguage: e.target.value, language: e.target.value })}
                className="mt-1 w-full max-w-xs rounded-lg border border-line bg-surface px-3 py-2"
              >
                {langs.length === 0 ? <option value={settings.defaultLanguage}>{settings.defaultLanguage}</option> : null}
                {langs.map((l) => (
                  <option key={l.code} value={l.code}>{l.endonym}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="default-country" className="block text-sm">{t("Default country")}</label>
              <select
                id="default-country"
                data-testid="default-country"
                value={settings.defaultCountry}
                onChange={(e) => updateSettings({ defaultCountry: e.target.value, country: e.target.value })}
                className="mt-1 w-full max-w-xs rounded-lg border border-line bg-surface px-3 py-2"
              >
                {codes.map((code) => (
                  <option key={code} value={code}>{countryName(code, settings.language, COUNTRY_NAMES)}</option>
                ))}
              </select>
            </div>
          </section>

          <section aria-labelledby="about" className="space-y-4" data-testid="about-attributions">
            <h2 id="about" className="text-base font-semibold">{t("About and attributions")}</h2>
            <p className="text-sm">{t(ABOUT_TEXT)}</p>
            <ul className="space-y-3">
              {ATTRIBUTIONS.map((a) => (
                <li key={a.name} className="rounded-lg border border-line bg-surface px-4 py-3 text-sm">
                  <p className="font-medium">
                    <a href={a.href} target="_blank" rel="noopener noreferrer" className="text-accent underline">{a.name}</a>
                  </p>
                  <p>{a.credit}</p>
                  <p className="text-muted">{t(a.note)}</p>
                </li>
              ))}
            </ul>
          </section>

          <Notice tone="info" title={t("Notice")}>{t(FIXED_NOTICE)}</Notice>
        </div>
      </div>
    </>
  );
}
