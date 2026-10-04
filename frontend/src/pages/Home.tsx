import { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useTranslation } from "react-i18next";
import "leaflet/dist/leaflet.css";
import { getSites, type Site, type UiStatus } from "../api";

const STATUS_COLOR: Record<UiStatus, string> = {
  good: "#3b9c3b",
  moderate: "#c9922b",
  poor: "#c23b3b",
  unavailable: "#9a9a94",
};

const STATUS_LABEL_KEY: Record<UiStatus, string> = {
  good: "statusGood",
  moderate: "statusModerate",
  poor: "statusPoor",
  unavailable: "statusUnavailable",
};

export default function Home() {
  const { t } = useTranslation();
  const [sites, setSites] = useState<Site[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    setSites(null);
    getSites()
      .then((data) => setSites(data.sites))
      .catch(() => setError(t("loadError")));
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, []);

  if (error) {
    return (
      <div className="state-message">
        <p>{error}</p>
        <button onClick={load}>{t("retry")}</button>
      </div>
    );
  }

  if (!sites) {
    return (
      <div className="state-message">
        <p>{t("loading")}</p>
      </div>
    );
  }

  const center: [number, number] = sites.length > 0 ? [sites[0].latitude, sites[0].longitude] : [20, 0];

  return (
    <div className="home">
      <header className="home-header">
        <h1>{t("appName")}</h1>
        <p>{t("appTagline")}</p>
      </header>
      <MapContainer center={center} zoom={sites.length > 0 ? 5 : 2} className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {sites.map((site) => (
          <CircleMarker
            key={site.id}
            center={[site.latitude, site.longitude]}
            radius={9}
            pathOptions={{
              color: STATUS_COLOR[site.ui_status],
              fillColor: STATUS_COLOR[site.ui_status],
              fillOpacity: 0.85,
            }}
          >
            <Popup>
              <strong>{site.name}</strong>
              <br />
              {site.status === "evaluated" ? (
                <>
                  {t(STATUS_LABEL_KEY[site.ui_status])} &middot; {t("wqiLabel")} {Math.round(site.ccme_wqi ?? 0)}
                  {site.confidence === "low_confidence" && (
                    <>
                      <br />
                      <em>{t("lowConfidence")}</em>
                    </>
                  )}
                </>
              ) : (
                t("statusUnavailable")
              )}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
