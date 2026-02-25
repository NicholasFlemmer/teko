import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { MapPin, Clock, CheckCircle2, XCircle, Loader2, Navigation } from "lucide-react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:5002";

type Status = "loading" | "ready" | "locating" | "submitting" | "success" | "too-far" | "error" | "expired" | "used";

interface SessionInfo {
  id: string;
  date: string;
  start_time: string;
  end_time: string;
  address: string;
  location: { latitude: number; longitude: number };
}

interface CheckInResult {
  location_verification: {
    distance: number;
    within_radius: boolean;
    allowed_radius: number;
  };
}

export default function CheckIn() {
  const { token } = useParams<{ token: string }>();
  const [status, setStatus] = useState<Status>("loading");
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [coachName, setCoachName] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<CheckInResult | null>(null);

  useEffect(() => {
    fetchCheckInInfo();
  }, [token]);

  async function fetchCheckInInfo() {
    try {
      const res = await fetch(`${API_URL}/api/sessions/check-in/${token}`);
      const data = await res.json();

      if (!res.ok) {
        if (data.error?.includes("expired")) {
          setStatus("expired");
        } else if (data.error?.includes("already been used")) {
          setStatus("used");
        } else {
          setError(data.error || "Invalid check-in link");
          setStatus("error");
        }
        return;
      }

      setSession(data.session);
      setCoachName(data.coach?.name || "Coach");
      setStatus("ready");
    } catch {
      setError("Unable to connect. Please check your internet connection.");
      setStatus("error");
    }
  }

  async function handleCheckIn() {
    setStatus("locating");

    if (!navigator.geolocation) {
      setError("Your browser doesn't support location services. Please use a modern browser.");
      setStatus("error");
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        setStatus("submitting");
        try {
          const res = await fetch(`${API_URL}/api/sessions/check-in/${token}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              location: {
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
              },
            }),
          });

          const data = await res.json();

          if (!res.ok) {
            setError(data.error || "Check-in failed");
            setStatus("error");
            return;
          }

          setResult(data);
          if (data.location_verification?.within_radius) {
            setStatus("success");
          } else {
            setStatus("too-far");
          }
        } catch {
          setError("Unable to submit check-in. Please try again.");
          setStatus("error");
        }
      },
      (geoError) => {
        if (geoError.code === geoError.PERMISSION_DENIED) {
          setError("Location access denied. Please enable location services in your browser settings and try again.");
        } else if (geoError.code === geoError.POSITION_UNAVAILABLE) {
          setError("Unable to determine your location. Please try again outdoors.");
        } else {
          setError("Location request timed out. Please try again.");
        }
        setStatus("error");
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  function formatDate(dateStr: string) {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-ZA", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  }

  function formatDistance(meters: number) {
    if (meters < 1000) return `${Math.round(meters)}m`;
    return `${(meters / 1000).toFixed(1)}km`;
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4 py-8">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-primary">Teko</h1>
          <p className="text-sm text-muted-foreground">Coach Check-in</p>
        </div>

        {status === "loading" && (
          <Card>
            <CardContent className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </CardContent>
          </Card>
        )}

        {status === "ready" && session && (
          <Card>
            <CardHeader className="pb-3">
              <h2 className="text-lg font-semibold">Hi {coachName}!</h2>
              <p className="text-sm text-muted-foreground">
                Confirm your attendance by checking in at the session location.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-lg bg-muted/50 p-3 space-y-2">
                <div className="flex items-start gap-2">
                  <Clock className="h-4 w-4 mt-0.5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">{formatDate(session.date)}</p>
                    <p className="text-sm text-muted-foreground">{session.start_time} - {session.end_time}</p>
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <MapPin className="h-4 w-4 mt-0.5 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">{session.address}</p>
                </div>
              </div>

              <Button onClick={handleCheckIn} className="w-full" size="lg">
                <Navigation className="h-4 w-4 mr-2" />
                Check In Now
              </Button>

              <p className="text-xs text-muted-foreground text-center">
                You must be within 100m of the session location to check in.
              </p>
            </CardContent>
          </Card>
        )}

        {(status === "locating" || status === "submitting") && (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12 space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-sm text-muted-foreground">
                {status === "locating" ? "Getting your location..." : "Verifying location..."}
              </p>
            </CardContent>
          </Card>
        )}

        {status === "success" && result && (
          <Card>
            <CardContent className="flex flex-col items-center py-8 space-y-4">
              <div className="rounded-full bg-green-100 p-3">
                <CheckCircle2 className="h-10 w-10 text-green-600" />
              </div>
              <div className="text-center space-y-1">
                <h2 className="text-lg font-semibold">Checked In!</h2>
                <p className="text-sm text-muted-foreground">
                  You're {formatDistance(result.location_verification.distance)} from the venue. Have a great session!
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {status === "too-far" && result && (
          <Card>
            <CardContent className="flex flex-col items-center py-8 space-y-4">
              <div className="rounded-full bg-orange-100 p-3">
                <MapPin className="h-10 w-10 text-orange-600" />
              </div>
              <div className="text-center space-y-1">
                <h2 className="text-lg font-semibold">Too Far Away</h2>
                <p className="text-sm text-muted-foreground">
                  You're {formatDistance(result.location_verification.distance)} from the venue.
                  You need to be within {formatDistance(result.location_verification.allowed_radius)}.
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                Your check-in was recorded but flagged as out of range.
              </p>
            </CardContent>
          </Card>
        )}

        {status === "expired" && (
          <Card>
            <CardContent className="flex flex-col items-center py-8 space-y-4">
              <div className="rounded-full bg-muted p-3">
                <Clock className="h-10 w-10 text-muted-foreground" />
              </div>
              <div className="text-center space-y-1">
                <h2 className="text-lg font-semibold">Link Expired</h2>
                <p className="text-sm text-muted-foreground">
                  This check-in link has expired. Please contact your administrator.
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {status === "used" && (
          <Card>
            <CardContent className="flex flex-col items-center py-8 space-y-4">
              <div className="rounded-full bg-green-100 p-3">
                <CheckCircle2 className="h-10 w-10 text-green-600" />
              </div>
              <div className="text-center space-y-1">
                <h2 className="text-lg font-semibold">Already Checked In</h2>
                <p className="text-sm text-muted-foreground">
                  You've already used this check-in link.
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {status === "error" && (
          <Card>
            <CardContent className="flex flex-col items-center py-8 space-y-4">
              <div className="rounded-full bg-destructive/10 p-3">
                <XCircle className="h-10 w-10 text-destructive" />
              </div>
              <div className="text-center space-y-1">
                <h2 className="text-lg font-semibold">Something went wrong</h2>
                <p className="text-sm text-muted-foreground">{error}</p>
              </div>
              <Button variant="outline" onClick={() => { setStatus("ready"); setError(""); }}>
                Try Again
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
