"""Optional EXTERNAL context around a site (docs/external_context.md).

Two providers, both read-only and called from the backend only, behind a cache and a process-wide budget:

* Open-Meteo: ERA5 reanalysis weather (MODELLED, not measured) and GloFAS river discharge (MODELLED, not a gauge);
* GBIF: opportunistic species occurrence records near a site (not monitoring).

Nothing here is a measurement of the site, nothing is merged with the EEA or sandbox data, and a provider that fails,
times out or is over budget produces an ``external-unavailable`` result, never an error that blocks a core feature.
"""
