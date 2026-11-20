"use client";

import { useState } from "react";

export function LogoutButton() {
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      window.location.assign("/login");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="logout-button" disabled={busy} onClick={signOut} type="button">
      {busy ? "Signing out..." : "Sign out"}
    </button>
  );
}
