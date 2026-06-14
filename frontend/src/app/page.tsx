"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = api.getToken();
    const destination = token ? "/chat" : "/login";
    if (token) {
      router.replace(destination);
    } else {
      router.replace(destination);
    }
    if (typeof window !== "undefined") {
      window.location.replace(destination);
    }
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center bg-zinc-950">
      <div className="text-zinc-400">Loading...</div>
    </div>
  );
}
