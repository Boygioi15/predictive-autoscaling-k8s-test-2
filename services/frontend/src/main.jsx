import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./main.css";
import RootLayout from "./Rootlayout";
import PrimePage from "./pages/PrimePage/PrimePage";
import TextPage from "./pages/TextPage/TextPage";
import IOPage from "./pages/IOPage/IOPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<RootLayout />}>
          {/* Mặc định redirect về trang Prime */}
          <Route index element={<Navigate to="/prime" replace />} />

          <Route path="prime" element={<PrimePage />} />
          <Route path="text" element={<TextPage />} />
          <Route path="io" element={<IOPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
createRoot(document.getElementById("root")).render(<App />);
