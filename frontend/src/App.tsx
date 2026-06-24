import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { TerminologyProvider } from "@/contexts/TerminologyContext";
import Schedule from "./pages/Schedule";
import Coaches from "./pages/Coaches";
import CoachDetail from "./pages/CoachDetail";
import Teams from "./pages/Teams";
import TeamDetail from "./pages/TeamDetail";
import Players from "./pages/Players";
import PlayerDetail from "./pages/PlayerDetail";
import Broadcasts from "./pages/Broadcasts";
import Content from "./pages/Content";
import Locations from "./pages/Locations";
import LocationDetail from "./pages/LocationDetail";
import Reports from "./pages/Reports";
import Reminders from "./pages/Reminders";
import SuperAdmin from "./pages/SuperAdmin";
import OrgSettings from "./pages/OrgSettings";
import NotFound from "./pages/NotFound";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import CheckIn from "./pages/CheckIn";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

const AppRoutes = () => (
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route path="/forgot-password" element={<ForgotPassword />} />
    <Route path="/reset-password" element={<ResetPassword />} />
    <Route path="/check-in/:token" element={<CheckIn />} />
    <Route path="/" element={<ProtectedRoute><Schedule /></ProtectedRoute>} />
    <Route path="/coaches" element={<ProtectedRoute><Coaches /></ProtectedRoute>} />
    <Route path="/coaches/:id" element={<ProtectedRoute><CoachDetail /></ProtectedRoute>} />
    <Route path="/teams" element={<ProtectedRoute><Teams /></ProtectedRoute>} />
    <Route path="/teams/:id" element={<ProtectedRoute><TeamDetail /></ProtectedRoute>} />
    <Route path="/players" element={<ProtectedRoute><Players /></ProtectedRoute>} />
    <Route path="/players/:id" element={<ProtectedRoute><PlayerDetail /></ProtectedRoute>} />
    <Route path="/broadcasts" element={<ProtectedRoute><Broadcasts /></ProtectedRoute>} />
    <Route path="/content" element={<ProtectedRoute><Content /></ProtectedRoute>} />
    <Route path="/locations" element={<ProtectedRoute><Locations /></ProtectedRoute>} />
    <Route path="/locations/:id" element={<ProtectedRoute><LocationDetail /></ProtectedRoute>} />
    <Route path="/reports" element={<ProtectedRoute><Reports /></ProtectedRoute>} />
    <Route path="/reminders" element={<ProtectedRoute><Reminders /></ProtectedRoute>} />
    <Route path="/super-admin" element={<ProtectedRoute><SuperAdmin /></ProtectedRoute>} />
    <Route path="/settings" element={<ProtectedRoute><OrgSettings /></ProtectedRoute>} />
    <Route path="*" element={<NotFound />} />
  </Routes>
);

const App = () => (
  <TooltipProvider>
    <Toaster />
    <BrowserRouter>
      <AuthProvider>
        <TerminologyProvider>
          <AppRoutes />
        </TerminologyProvider>
      </AuthProvider>
    </BrowserRouter>
  </TooltipProvider>
);

export default App;
