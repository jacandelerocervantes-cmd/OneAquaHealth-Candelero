import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const resources = {
  en: {
    translation: {
      appName: "OneAquaHealth",
      appTagline: "Urban stream monitoring sites",
      statusGood: "Good",
      statusModerate: "Moderate",
      statusPoor: "Poor",
      statusUnavailable: "No water data",
      wqiLabel: "WQI",
      lowConfidence: "Low confidence",
      loading: "Loading sites...",
      loadError: "Could not load sites. Is the API running?",
      retry: "Retry",
    },
  },
  es: {
    translation: {
      appName: "OneAquaHealth",
      appTagline: "Sitios de monitoreo de arroyos urbanos",
      statusGood: "Bueno",
      statusModerate: "Moderado",
      statusPoor: "Pobre",
      statusUnavailable: "Sin datos de agua",
      wqiLabel: "WQI",
      lowConfidence: "Confianza baja",
      loading: "Cargando sitios...",
      loadError: "No se pudo cargar los sitios. ¿Esta corriendo la API?",
      retry: "Reintentar",
    },
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
