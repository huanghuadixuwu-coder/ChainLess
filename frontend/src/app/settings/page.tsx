"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTokenPresent } from "@/lib/auth-token";
import { Sidebar } from "@/components/layout/sidebar";
import { SettingsShell } from "@/components/settings/settings-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChatStore } from "@/stores/chat-store";
import { usePlatformStore } from "@/stores/platform-store";

export default function SettingsPage() {
  const router = useRouter();
  const createConversation = useChatStore((state) => state.createConversation);
  const selectConversation = useChatStore((state) => state.selectConversation);
  const loadConversations = useChatStore((state) => state.loadConversations);
  const { currentUser, isLoadingUser, loadCurrentUser, loadSettings } =
    usePlatformStore();
  const hasToken = useTokenPresent();

  useEffect(() => {
    if (hasToken === null) {
      return;
    }
    if (!hasToken) {
      router.replace("/login");
      if (typeof window !== "undefined") {
        window.location.replace("/login");
      }
      return;
    }

    void loadConversations();

    void (async () => {
      const user = await loadCurrentUser();
      if (!user) {
        router.replace("/login");
        if (typeof window !== "undefined") {
          window.location.replace("/login");
        }
      }
    })();
  }, [router, loadCurrentUser, loadConversations, hasToken]);

  useEffect(() => {
    if (currentUser?.role === "admin") {
      void loadSettings();
    }
  }, [currentUser, loadSettings]);

  const handleNewChat = async () => {
    const id = await createConversation();
    await selectConversation(id);
    router.push("/chat");
  };

  if (hasToken !== true || isLoadingUser || !currentUser) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-950">
        <div className="text-zinc-400">Loading...</div>
      </div>
    );
  }

  if (currentUser && currentUser.role !== "admin") {
    return (
      <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">
        <Sidebar onNewChat={handleNewChat} />
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="w-full max-w-md bg-zinc-900 border-zinc-800">
            <CardHeader>
              <CardTitle className="text-zinc-100">No permission</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-zinc-400">
              Settings are only available to admin users.
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">
      <Sidebar onNewChat={handleNewChat} />
      <SettingsShell />
    </div>
  );
}
