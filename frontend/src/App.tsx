import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Home from "./pages/Home";
import "./App.css";

function LanguageSwitcher() {
  const { i18n } = useTranslation();
  return (
    <div className="language-switcher">
      <button onClick={() => i18n.changeLanguage("en")} disabled={i18n.language === "en"}>
        EN
      </button>
      <button onClick={() => i18n.changeLanguage("es")} disabled={i18n.language === "es"}>
        ES
      </button>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <LanguageSwitcher />
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
