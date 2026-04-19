import { Navigate, Route, Routes } from "react-router-dom";
import { ProfileProvider } from "./state/profile";
import Welcome from "./pages/Welcome";
import Discover from "./pages/Discover";
import Configure from "./pages/Configure";
import Practice from "./pages/Practice";
import Done from "./pages/Done";

export default function App() {
  return (
    <ProfileProvider>
      <Routes>
        <Route path="/" element={<Welcome />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/configure" element={<Configure />} />
        <Route path="/practice" element={<Practice />} />
        <Route path="/done" element={<Done />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ProfileProvider>
  );
}
