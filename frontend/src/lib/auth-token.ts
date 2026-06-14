"use client";

import { useSyncExternalStore } from "react";
import { api, TOKEN_CHANGE_EVENT } from "@/lib/api";

const subscribe = (onStoreChange: () => void) => {
  if (typeof window === "undefined") {
    return () => {};
  }

  window.addEventListener("storage", onStoreChange);
  window.addEventListener(TOKEN_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(TOKEN_CHANGE_EVENT, onStoreChange);
  };
};

const getSnapshot = () => {
  if (typeof window === "undefined") {
    return null;
  }
  return Boolean(api.getToken());
};

const getServerSnapshot = () => null;

export function useTokenPresent() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
